import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../models/account.dart';
import '../models/generated_quest.dart';
import '../models/journal_entry.dart';
import '../models/profile_preferences.dart';
import '../models/quest_record.dart';
import '../models/rewards.dart';
import '../models/streak.dart';
import 'api_client.dart';
import 'key_value_store.dart';

/// Everything the app knows about the signed-in user, kept on the device so
/// the app works offline.
///
/// Offline-first:
/// - The session token is saved on the device (app-private storage), so the app opens straight
///   into your account with no connection.
/// - Your profile and quest history are cached on the device and shown from
///   the cache; they refresh from the server whenever it's reachable.
/// - Changes made offline (preferences, quest feedback, journal notes and
///   photos) are saved locally
///   right away and queued in an *outbox*, then sent when back online
///   ([sync] runs on app start, when the app comes back to the foreground,
///   on pull-to-refresh, and after any request that reaches the server).
/// - Only these need a connection: signing up, logging in, editing name/email
///   and generating a new quest (Gemma runs on the server).
class AppState extends ChangeNotifier {
  /// [secure] holds the login session. The app passes the same
  /// shared_preferences store as [cache]; it's a separate parameter so a
  /// Keychain/Keystore-backed store can be dropped in later.
  AppState({required this.api, required KeyValueStore cache, required KeyValueStore secure})
      : _cache = cache,
        _secure = secure;

  final ApiClient api;
  final KeyValueStore _cache;
  final KeyValueStore _secure;

  static const _sessionKey = 'session';
  static const _cacheNames = ['profile', 'quests', 'outbox', 'meta', 'journal', 'rewards', 'streak'];

  Session? _session;
  ProfilePreferences? _profile;
  List<QuestRecord> _quests = const [];
  List<Map<String, dynamic>> _outbox = [];
  bool _online = true;
  Future<void>? _syncInFlight;
  bool _sessionExpired = false;
  String? _lastSyncError;
  int _completedCount = 0;
  Rewards? _rewards;
  StreakInfo? _streak;
  int? _activeQuestId;
  Map<int, List<JournalEntry>> _journals = {};
  final Map<String, Uint8List> _photoCache = {}; // downloaded photos, by client id (memory only)

  Session? get session => _session;
  Account? get account => _session?.account;
  bool get isLoggedIn => _session != null;

  /// Saved quest preferences (null until set up).
  ProfilePreferences? get profile => _profile;

  /// Newest first.
  List<QuestRecord> get quests => List.unmodifiable(_quests);

  /// Points, level, streaks and badges (last copy from the server; null until loaded).
  Rewards? get rewards => _rewards;

  /// The daily streak, rolled forward to right now (a new day can put it at
  /// risk or use a freeze even before the server is asked). Never null.
  StreakInfo get streak => (_streak ?? StreakInfo.empty(clock())).asOf(clock());

  /// "Now" - swappable in tests.
  DateTime Function() clock = DateTime.now;

  /// Minutes east of UTC, so the server's "today" is the user's today.
  String get _tz => 'tz_offset_minutes=${clock().timeZoneOffset.inMinutes}';

  /// Total quests completed (the counter on the Quest screen).
  int get completedCount => _completedCount;

  /// The quest currently shown on the Quest screen (generated, not completed yet).
  QuestRecord? get activeQuest {
    final id = _activeQuestId;
    if (id == null) return null;
    final matches = _quests.where((q) => q.id == id && q.status != QuestStatus.completed);
    return matches.isEmpty ? null : matches.first; // completed (maybe on another device) = gone
  }

  /// Notes and photos for a quest, oldest first.
  List<JournalEntry> journal(int questId) => List.unmodifiable(_journals[questId] ?? const <JournalEntry>[]);

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
      for (final name in _cacheNames) {
        await _cache.delete(_key(name));
      }
      _profile = null;
      _quests = const [];
      _outbox = [];
      _completedCount = 0;
      _activeQuestId = null;
      _journals = {};
      _rewards = null;
      _streak = null;
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
    final meta = await _cache.read(_key('meta'));
    final m = meta == null ? const <String, dynamic>{} : jsonDecode(meta) as Map<String, dynamic>;
    _completedCount = (m['completed'] as num?)?.toInt() ?? 0;
    _activeQuestId = (m['active_quest'] as num?)?.toInt();
    final rewards = await _cache.read(_key('rewards'));
    _rewards = rewards == null ? null : Rewards.fromJson(jsonDecode(rewards) as Map<String, dynamic>);
    final streak = await _cache.read(_key('streak'));
    _streak = streak == null ? null : StreakInfo.fromJson(jsonDecode(streak) as Map<String, dynamic>);
    final journal = await _cache.read(_key('journal'));
    _journals = {};
    if (journal != null) {
      for (final e in jsonDecode(journal) as List<dynamic>) {
        final entry = JournalEntry.fromJson(e as Map<String, dynamic>);
        _journals.putIfAbsent(entry.questId, () => []).add(entry);
      }
    }
  }

  Future<void> _saveCache() async {
    final session = _session;
    if (session == null) return;
    // Snapshot first, so a logout half-way through can't mix accounts.
    final id = session.account.id;
    final values = <String, String>{
      if (_profile != null) 'profile:$id': jsonEncode(_profile!.toJson()),
      'quests:$id': jsonEncode([for (final q in _quests) q.toJson()]),
      'outbox:$id': jsonEncode(_outbox),
      'meta:$id': jsonEncode({'completed': _completedCount, 'active_quest': _activeQuestId}),
      'journal:$id': jsonEncode([for (final list in _journals.values) for (final e in list) e.toJson()]),
      if (_rewards != null) 'rewards:$id': jsonEncode(_rewards!.toJson()),
      if (_streak != null) 'streak:$id': jsonEncode(_streak!.toJson()),
    };
    for (final entry in values.entries) {
      if (_session?.token != session.token) return; // logged out meanwhile - don't write it back
      await _cache.write(entry.key, entry.value);
    }
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
    await _forget(session);
  }

  /// Delete the account and everything in it, on the server and this device.
  /// Needs a connection and the password. Throws [ApiException] (403 = wrong
  /// password) or [OfflineException].
  Future<void> deleteAccount(String password) async {
    final session = _session;
    if (session == null) return;
    await _call(() => api.delete('/auth/me', {'password': password}));
    await _forget(session);
  }

  /// Remove this account's session and cached data from the device.
  Future<void> _forget(Session session) async {
    // Forget the session first so a running sync stops writing this account's cache.
    api.token = null;
    _session = null;
    for (final name in _cacheNames) {
      await _cache.delete('$name:${session.account.id}');
    }
    await _secure.delete(_sessionKey);
    _profile = null;
    _quests = const [];
    _outbox = [];
    _completedCount = 0;
    _activeQuestId = null;
    _journals = {};
    _rewards = null;
    _streak = null;
    _photoCache.clear();
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
    final now = clock();
    _outbox.removeWhere((op) => op['type'] == 'feedback' && op['quest_id'] == questId);
    _outbox.add({
      'type': 'feedback',
      'quest_id': questId,
      // completed_at: when it really happened, even if this syncs hours later (streak day).
      'body': {...feedback.toJson(), if (feedback.completed) 'completed_at': now.toUtc().toIso8601String()},
    });
    final before = _quests.where((q) => q.id == questId);
    final wasCompleted = before.isNotEmpty && before.first.status == QuestStatus.completed;
    if (feedback.completed && !wasCompleted) {
      _streak = streak.withCompletion(now); // the flame lights up right away, even offline
    }
    if (feedback.completed && !wasCompleted) _completedCount++;
    if (!feedback.completed && wasCompleted && _completedCount > 0) _completedCount--;
    // A completed quest leaves the Quest screen (it's in History now).
    if (feedback.completed && _activeQuestId == questId) _activeQuestId = null;
    _quests = [for (final q in _quests) q.id == questId ? q.withFeedback(feedback, pending: true) : q];
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false).then((_) => loadStreak()));
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
    _activeQuestId = record.id;
    await _saveCache();
    notifyListeners();
    return record;
  }

  // ---------------------------------------------------------------------------
  // Journal: notes and photos (work offline)
  // ---------------------------------------------------------------------------

  static final _random = Random.secure();

  static String _newClientId() {
    final rand = List.generate(8, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
    return 'c${DateTime.now().millisecondsSinceEpoch.toRadixString(36)}$rand';
  }

  Future<void> addNote(int questId, String text) =>
      _addEntry(JournalEntry(clientId: _newClientId(), questId: questId, kind: 'note', text: text.trim(),
          createdAt: DateTime.now(), pending: true));

  /// [bytes] should already be resized (the picker does that); max 5 MB.
  Future<void> addPhoto(int questId, Uint8List bytes, String mime, {String caption = ''}) =>
      _addEntry(JournalEntry(clientId: _newClientId(), questId: questId, kind: 'photo', text: caption.trim(),
          mime: mime, localImageBase64: base64Encode(bytes), createdAt: DateTime.now(), pending: true));

  Future<void> _addEntry(JournalEntry entry) async {
    _journals.putIfAbsent(entry.questId, () => []).add(entry);
    _outbox.add({'type': 'log', 'quest_id': entry.questId, 'client_id': entry.clientId});
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false));
  }

  Future<void> deleteJournalEntry(JournalEntry entry) async {
    _journals[entry.questId]?.removeWhere((e) => e.clientId == entry.clientId);
    _outbox.removeWhere((op) => op['type'] == 'log' && op['client_id'] == entry.clientId);
    // Always tell the server: the upload may already be on its way. Deleting
    // something it never got is harmless.
    _outbox.add({'type': 'log_delete', 'client_id': entry.clientId});
    _photoCache.remove(entry.clientId);
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false));
  }

  /// Pull a quest's journal from the server (e.g. made on another device).
  /// Entries not uploaded yet stay. Quietly does nothing offline.
  Future<void> loadJournal(int questId) async {
    if (_session == null) return;
    final userId = _session!.account.id;
    try {
      final list = await _call(() => api.get('/users/$userId/quests/$questId/logs')) as List<dynamic>;
      final local = {for (final e in _journals[questId] ?? const <JournalEntry>[]) e.clientId: e};
      final deleting = {for (final op in _outbox) if (op['type'] == 'log_delete') op['client_id'] as String};
      final merged = <JournalEntry>[];
      for (final item in list) {
        final server = JournalEntry.fromServer(item as Map<String, dynamic>);
        if (deleting.contains(server.clientId)) continue; // deleted here, not on the server yet
        local.remove(server.clientId);
        merged.add(server);
      }
      merged.addAll(local.values.where((e) => e.pending)); // not uploaded yet
      merged.sort((a, b) => a.createdAt.compareTo(b.createdAt));
      _journals[questId] = merged;
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // show what's cached
    } on ApiException {
      // e.g. quest gone - show what's cached
    }
  }

  /// Refresh points/level/badges: sends queued changes first so they count.
  /// Offline, the last saved copy stays.
  Future<void> loadRewards() async {
    await sync(refresh: false);
    final session = _session;
    if (session == null) return;
    try {
      final json = await _call(() => api.get('/users/${session.account.id}/rewards?$_tz'));
      if (_session?.token != session.token) return;
      _rewards = Rewards.fromJson(json as Map<String, dynamic>);
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // keep the cached copy
    } on ApiException {
      // keep the cached copy
    }
  }

  /// Refresh the streak from the server (after queued changes are sent, so
  /// offline completions count). Offline / old server: keeps the local copy.
  Future<void> loadStreak() async {
    final session = _session;
    if (session == null) return;
    if (_outbox.any((op) => op['type'] == 'feedback')) return; // server doesn't know yet - keep ours
    try {
      final json = await _call(() => api.get('/users/${session.account.id}/streak?$_tz'));
      if (_session?.token != session.token) return;
      _streak = StreakInfo.fromJson(json as Map<String, dynamic>);
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // keep the local copy
    } on ApiException {
      // keep the local copy
    }
  }

  /// Spend points on a streak freeze (needs a connection). Throws
  /// [ApiException] (409 = not enough points / already holding the max) or
  /// [OfflineException].
  Future<void> buyStreakFreeze() async {
    await sync(refresh: false); // points from quests rated offline count too
    final session = _session;
    if (session == null) return;
    final json = await _call(() => api.post('/users/${session.account.id}/streak/freeze?$_tz'));
    if (_session?.token != session.token) return;
    _streak = StreakInfo.fromJson(json as Map<String, dynamic>);
    await _saveCache();
    notifyListeners();
    unawaited(loadRewards()); // spendable points changed
  }

  /// A photo's bytes: from the device if we have them, else downloaded once.
  Future<Uint8List?> photoBytes(JournalEntry entry) async {
    final local = entry.localImage;
    if (local != null) return local;
    final cached = _photoCache[entry.clientId];
    if (cached != null) return cached;
    if (entry.serverId == null || _session == null) return null;
    try {
      final bytes = await api.getBytes('/users/${_session!.account.id}/logs/${entry.serverId}/photo');
      _photoCache[entry.clientId] = bytes;
      return bytes;
    } on Object {
      return null; // offline or deleted - the UI shows a placeholder
    }
  }

  JournalEntry? _entry(int questId, String clientId) {
    final matches = (_journals[questId] ?? const <JournalEntry>[]).where((e) => e.clientId == clientId);
    return matches.isEmpty ? null : matches.first;
  }

  void _replaceEntry(JournalEntry updated) {
    final list = _journals[updated.questId];
    if (list == null) return;
    final i = list.indexWhere((e) => e.clientId == updated.clientId);
    if (i >= 0) list[i] = updated;
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
          } else if (op['type'] == 'log') {
            final entry = _entry(op['quest_id'] as int, op['client_id'] as String);
            if (entry != null) {
              final json = await _call(
                () => api.post('/users/$userId/quests/${entry.questId}/logs', entry.toUpload()),
              ) as Map<String, dynamic>;
              final image = entry.localImage;
              if (image != null) _photoCache[entry.clientId] = image; // still shows this session
              _replaceEntry(entry.uploaded((json['id'] as num).toInt()));
            }
          } else if (op['type'] == 'log_delete') {
            await _call(() => api.delete('/users/$userId/logs/${op['client_id']}'));
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
      if (refresh && stillCurrent()) {
        await _refresh(session);
        if (stillCurrent()) await loadStreak();
      }
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
    final stats = await _call(() => api.get('/users/$userId/stats')) as Map<String, dynamic>;
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
    var completed = (stats['completed'] as num?)?.toInt() ?? _completedCount;
    for (final item in list) {
      final json = item as Map<String, dynamic>;
      final q = QuestRecord.fromJson(json, distanceKm: distances[(json['id'] as num).toInt()]);
      final local = pending[q.id];
      if (local != null) {
        // Feedback not on the server yet still counts.
        final serverCompleted = q.status == QuestStatus.completed;
        if (local.completed && !serverCompleted) completed++;
        if (!local.completed && serverCompleted) completed--;
      }
      fresh.add(local == null ? q : q.withFeedback(local, pending: true));
    }
    _quests = fresh;
    _completedCount = completed < 0 ? 0 : completed;
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
