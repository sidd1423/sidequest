import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../models/account.dart';
import '../models/generated_quest.dart';
import '../models/profile_preferences.dart';
import '../models/quest_record.dart';
import 'api_client.dart';
import 'key_value_store.dart';

/// Everything the app knows about the signed-in user, kept on the device so
/// the app works offline.
///
/// Offline-first:
/// - The session token lives in secure storage, so the app opens straight
///   into your account with no connection.
/// - Your profile and quest history are cached on the device and shown from
///   the cache; they refresh from the server whenever it's reachable.
/// - Changes made offline (preferences, quest feedback) are saved locally
///   right away and queued in an *outbox*, then sent when back online
///   ([sync] runs on app start, when the app comes back to the foreground,
///   on pull-to-refresh, and after any request that reaches the server).
/// - Only these need a connection: signing up, logging in, editing name/email
///   and generating a new quest (Gemma runs on the server).
class AppState extends ChangeNotifier {
  AppState({required this.api, required KeyValueStore cache, required KeyValueStore secure})
      : _cache = cache,
        _secure = secure;

  final ApiClient api;
  final KeyValueStore _cache;
  final KeyValueStore _secure;

  static const _sessionKey = 'session';

  Session? _session;
  ProfilePreferences? _profile;
  List<QuestRecord> _quests = const [];
  List<Map<String, dynamic>> _outbox = [];
  bool _online = true;
  Future<void>? _syncInFlight;
  bool _sessionExpired = false;
  String? _lastSyncError;

  Session? get session => _session;
  Account? get account => _session?.account;
  bool get isLoggedIn => _session != null;

  /// Saved quest preferences (null until set up).
  ProfilePreferences? get profile => _profile;

  /// Newest first.
  List<QuestRecord> get quests => List.unmodifiable(_quests);

  /// Last request reached the server.
  bool get isOnline => _online;
  bool get isSyncing => _syncInFlight != null;

  /// Changes waiting to be sent to the server.
  int get pendingChanges => _outbox.length;

  /// The server rejected the saved session (expired or logged out elsewhere).
  /// Cached data stays; logging in again sends any queued changes.
  bool get sessionExpired => _sessionExpired;
  String? get lastSyncError => _lastSyncError;

  String _key(String name) => '$name:${_session!.account.id}';

  // ---------------------------------------------------------------------------
  // Start-up
  // ---------------------------------------------------------------------------

  /// Load the saved session and cached data. Local only - never waits for the
  /// network, so the app opens instantly (and offline).
  Future<void> restore() async {
    final raw = await _secure.read(_sessionKey);
    if (raw == null) return;
    try {
      _session = Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on Object {
      await _secure.delete(_sessionKey); // corrupt - start over
      return;
    }
    api.token = _session!.token;
    await _loadCache();
    notifyListeners();
  }

  Future<void> _loadCache() async {
    try {
      await _readCache();
    } on Object {
      // Corrupt cache (e.g. from an older app version): start clean, the
      // server copy is pulled on the next sync.
      for (final name in ['profile', 'quests', 'outbox']) {
        await _cache.delete(_key(name));
      }
      _profile = null;
      _quests = const [];
      _outbox = [];
    }
  }

  Future<void> _readCache() async {
    final profile = await _cache.read(_key('profile'));
    _profile = profile == null ? null : ProfilePreferences.fromJson(jsonDecode(profile) as Map<String, dynamic>);
    final quests = await _cache.read(_key('quests'));
    _quests = quests == null
        ? []
        : [for (final q in jsonDecode(quests) as List<dynamic>) QuestRecord.fromJson(q as Map<String, dynamic>)];
    final outbox = await _cache.read(_key('outbox'));
    _outbox = outbox == null
        ? []
        : [for (final op in jsonDecode(outbox) as List<dynamic>) op as Map<String, dynamic>];
  }

  Future<void> _saveCache() async {
    if (_session == null) return;
    if (_profile != null) await _cache.write(_key('profile'), jsonEncode(_profile!.toJson()));
    await _cache.write(_key('quests'), jsonEncode([for (final q in _quests) q.toJson()]));
    await _cache.write(_key('outbox'), jsonEncode(_outbox));
  }

  // ---------------------------------------------------------------------------
  // Auth (needs a connection)
  // ---------------------------------------------------------------------------

  Future<void> signUp({required String name, required String email, required String password}) async {
    final json = await _call(() => api.post('/auth/signup', {'name': name, 'email': email, 'password': password}));
    await _startSession(Session.fromJson(json as Map<String, dynamic>));
  }

  Future<void> logIn({required String email, required String password}) async {
    final json = await _call(() => api.post('/auth/login', {'email': email, 'password': password}));
    await _startSession(Session.fromJson(json as Map<String, dynamic>));
    await sync(); // send anything queued before the session expired, then pull the latest
  }

  Future<void> _startSession(Session session) async {
    _session = session;
    _sessionExpired = false;
    api.token = session.token;
    await _secure.write(_sessionKey, jsonEncode(session.toJson()));
    await _loadCache(); // same user on this device before? keep their cache + outbox
    notifyListeners();
  }

  /// Log out and remove this user's data from the device. Unsynced changes
  /// are lost - the Account screen warns about that first.
  Future<void> logOut() async {
    final session = _session;
    if (session == null) return;
    try {
      await api.post('/auth/logout');
    } on Object {
      // Offline or already expired - the token is forgotten locally anyway.
    }
    for (final name in ['profile', 'quests', 'outbox']) {
      await _cache.delete('$name:${session.account.id}');
    }
    await _secure.delete(_sessionKey);
    api.token = null;
    _session = null;
    _profile = null;
    _quests = const [];
    _outbox = [];
    _sessionExpired = false;
    _lastSyncError = null;
    notifyListeners();
  }

  /// Change name/email (needs a connection).
  Future<void> updateAccount({required String name, required String email}) async {
    final current = _session!.account;
    final changes = <String, dynamic>{
      if (name.trim() != current.name) 'name': name.trim(),
      if (email.trim().toLowerCase() != current.email) 'email': email.trim(),
    };
    if (changes.isEmpty) return;
    final json = await _call(() => api.patch('/auth/me', changes));
    _session = _session!.copyWith(account: Account.fromJson(json as Map<String, dynamic>));
    await _secure.write(_sessionKey, jsonEncode(_session!.toJson()));
    notifyListeners();
  }

  // ---------------------------------------------------------------------------
  // Preferences & feedback (work offline)
  // ---------------------------------------------------------------------------

  /// Save the "set once" preferences: on the device now, on the server now
  /// or as soon as it's reachable.
  Future<void> saveProfile(ProfilePreferences preferences) async {
    _profile = preferences.copy();
    _outbox.removeWhere((op) => op['type'] == 'preferences'); // only the latest matters
    _outbox.add({'type': 'preferences', 'body': _profile!.toJson()});
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false)); // don't make the screen wait on a slow connection
  }

  /// Rate a quest: shown right away, sent now or when back online.
  Future<void> sendFeedback(int questId, QuestFeedback feedback) async {
    _outbox.removeWhere((op) => op['type'] == 'feedback' && op['quest_id'] == questId);
    _outbox.add({'type': 'feedback', 'quest_id': questId, 'body': feedback.toJson()});
    _quests = [for (final q in _quests) q.id == questId ? q.withFeedback(feedback, pending: true) : q];
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false));
  }

  // ---------------------------------------------------------------------------
  // Quests (generating needs a connection)
  // ---------------------------------------------------------------------------

  /// Ask the server (Gemma) for a new quest with this quest's settings.
  /// Throws [OfflineException] when offline.
  Future<QuestRecord> generateQuest(QuestSettings settings) async {
    await sync(refresh: false); // make sure the server has the latest preferences + ratings
    final userId = _session!.account.id;
    final json = await _call(
      () => api.post('/users/$userId/quests', settings.toJson(), ApiClient.generateTimeout),
    );
    final record = QuestRecord.fromJson(json as Map<String, dynamic>, distanceKm: settings.distanceKm);
    _quests = [record, ..._quests.where((q) => q.id != record.id)];
    await _saveCache();
    notifyListeners();
    return record;
  }

  /// Send queued changes, then (if [refresh]) pull the latest profile and
  /// quests. Safe to call any time; does nothing useful offline. If a sync is
  /// already running, waits for it and then runs again so nothing is skipped.
  Future<void> sync({bool refresh = true}) async {
    while (_syncInFlight != null) {
      await _syncInFlight;
    }
    if (_session == null) return;
    final run = _sync(refresh);
    _syncInFlight = run;
    notifyListeners();
    try {
      await run;
    } finally {
      _syncInFlight = null;
      notifyListeners();
    }
  }

  Future<void> _sync(bool refresh) async {
    final session = _session!;
    final userId = session.account.id;
    bool stillCurrent() => _session?.token == session.token; // logged out / switched user meanwhile?
    String? dropped;
    try {
      while (_outbox.isNotEmpty && stillCurrent()) {
        final op = _outbox.first;
        try {
          if (op['type'] == 'preferences') {
            await _call(() => api.put('/users/$userId/preferences', op['body']));
          } else if (op['type'] == 'feedback') {
            await _call(() => api.post('/users/$userId/quests/${op['quest_id']}/feedback', op['body']));
          }
        } on ApiException catch (e) {
          // Retry later: expired session, rate limits, timeouts, server trouble.
          if (e.isUnauthorized || e.statusCode == 408 || e.statusCode == 429 || e.statusCode >= 500) rethrow;
          // Any other 4xx will never be accepted - drop it so it doesn't block the rest.
          dropped = "A change couldn't be saved: ${e.message}";
        }
        if (!stillCurrent()) return;
        _outbox.remove(op); // this exact item - newer edits may have been queued meanwhile
        if (op['type'] == 'feedback') _markSynced(op['quest_id'] as int);
        await _saveCache();
      }
      if (refresh && stillCurrent()) await _refresh(session);
      if (stillCurrent()) _lastSyncError = dropped;
    } on OfflineException {
      // Stay queued; try again later.
    } on ApiException catch (e) {
      if (!e.isUnauthorized && stillCurrent()) _lastSyncError = e.message;
    }
    if (stillCurrent()) await _saveCache();
  }

  /// Feedback for [questId] reached the server, unless a newer rating is still queued.
  void _markSynced(int questId) {
    if (_outbox.any((op) => op['type'] == 'feedback' && op['quest_id'] == questId)) return;
    _quests = [
      for (final q in _quests)
        q.id == questId && q.feedback != null ? q.withFeedback(q.feedback!) : q,
    ];
  }

  Future<void> _refresh(Session session) async {
    final userId = session.account.id;
    ProfilePreferences? profile = _profile;
    try {
      final prefs = await _call(() => api.get('/users/$userId/preferences'));
      profile = ProfilePreferences.fromJson(prefs as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode != 404) rethrow; // 404 = not set up yet (keep any local copy)
    }
    final list = await _call(() => api.get('/users/$userId/quests?limit=50')) as List<dynamic>;
    if (_session?.token != session.token) return; // logged out while we were waiting

    // A preferences edit queued meanwhile wins over what the server had.
    final queuedPrefs = _outbox.any((op) => op['type'] == 'preferences');
    if (!queuedPrefs) _profile = profile;

    final distances = {for (final q in _quests) q.id: q.quest.distanceKm}; // the server doesn't store it
    final pending = {
      for (final op in _outbox)
        if (op['type'] == 'feedback') op['quest_id'] as int: QuestFeedback.fromJson(op['body'] as Map<String, dynamic>),
    };
    final fresh = <QuestRecord>[];
    for (final item in list) {
      final json = item as Map<String, dynamic>;
      final q = QuestRecord.fromJson(json, distanceKm: distances[(json['id'] as num).toInt()]);
      final local = pending[q.id];
      fresh.add(local == null ? q : q.withFeedback(local, pending: true));
    }
    _quests = fresh;
  }

  /// Runs a request, tracking online/offline and expired sessions.
  Future<dynamic> _call(Future<dynamic> Function() request) async {
    try {
      final result = await request();
      _setOnline(true);
      return result;
    } on OfflineException {
      _setOnline(false);
      rethrow;
    } on ApiException catch (e) {
      _setOnline(true);
      if (e.isUnauthorized && _session != null && api.token != null) {
        _sessionExpired = true;
        notifyListeners();
      }
      rethrow;
    }
  }

  void _setOnline(bool online) {
    if (_online == online) return;
    _online = online;
    notifyListeners();
  }
}
