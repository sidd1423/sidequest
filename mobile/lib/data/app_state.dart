import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../models/account.dart';
import '../models/friends.dart';
import '../models/generated_quest.dart';
import '../models/journal_entry.dart';
import '../models/location.dart';
import '../models/party.dart';
import '../models/profile_preferences.dart';
import '../models/quest_record.dart';
import '../models/rewards.dart';
import '../models/streak.dart';
import 'api_client.dart';
import 'key_value_store.dart';
import 'location_service.dart';

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
/// - Location: each new quest sends where you are, so the server can use the
///   live weather and real places nearby. While you do a quest the app can
///   record your route (foreground GPS); it's kept on the device and uploaded
///   through the outbox like everything else.
class AppState extends ChangeNotifier {
  /// [secure] holds the login session. The app passes the same
  /// shared_preferences store as [cache]; it's a separate parameter so a
  /// Keychain/Keystore-backed store can be dropped in later.
  AppState({required this.api, required KeyValueStore cache, required KeyValueStore secure, LocationService? location})
      : _cache = cache,
        _secure = secure,
        location = location ?? DeviceLocationService();

  final ApiClient api;

  /// GPS - swappable in tests.
  final LocationService location;
  final KeyValueStore _cache;
  final KeyValueStore _secure;

  static const _sessionKey = 'session';
  static const _cacheNames = [
    'profile', 'quests', 'outbox', 'meta', 'journal', 'rewards', 'streak', 'friends', 'parties', 'routes',
  ];

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
  FriendsData _friends = const FriendsData();
  List<Party> _parties = const [];
  Set<int> _seenPartyQuests = {}; // group quests already put on the Quest screen
  int? _activeQuestId;
  Map<int, List<JournalEntry>> _journals = {};
  final Map<String, Uint8List> _photoCache = {}; // downloaded photos, by client id (memory only)

  // Location + weather (memory only) and recorded routes (cached).
  GeoPoint? _here;
  QuestConditions? _conditions;
  LocationProblem? _locationProblem;
  bool _locating = false;
  Map<int, List<GeoPoint>> _routes = {};
  int? _trackingQuestId;
  StreamSubscription<GeoPoint>? _trackSub;
  String? _trackingError;
  int _unsavedPoints = 0;

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

  /// Friends and friend requests (last copy from the server).
  FriendsData get friends => _friends;

  /// Group quests you host, joined or are invited to (newest first).
  List<Party> get parties => List.unmodifiable(_parties);

  /// Group quest invites waiting for an answer (the badge on the Quest tab).
  int get partyInvites => _parties.where((p) => p.isInvite).length;

  /// Friend requests waiting for you (the badge on the Friends tab).
  int get incomingFriendRequests => _friends.incoming.length;

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

  /// Where you are (last fix this session) and what's there: place, weather, nearby spots.
  GeoPoint? get here => _here;
  QuestConditions? get conditions => _conditions;

  /// Why we couldn't get your location last time (null = fine / not tried).
  LocationProblem? get locationProblem => _locationProblem;
  bool get isLocating => _locating;

  /// The path recorded for a quest (oldest point first).
  List<GeoPoint> route(int questId) => List.unmodifiable(_routes[questId] ?? const <GeoPoint>[]);

  /// The quest whose route is being recorded right now (null = not tracking).
  int? get trackingQuestId => _trackingQuestId;
  bool isTracking(int questId) => _trackingQuestId == questId;
  String? get trackingError => _trackingError;

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
      _friends = const FriendsData();
      _parties = const [];
      _seenPartyQuests = {};
      _routes = {};
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
    _seenPartyQuests = {for (final id in (m['party_seen'] as List<dynamic>? ?? const [])) (id as num).toInt()};
    final rewards = await _cache.read(_key('rewards'));
    _rewards = rewards == null ? null : Rewards.fromJson(jsonDecode(rewards) as Map<String, dynamic>);
    final streak = await _cache.read(_key('streak'));
    _streak = streak == null ? null : StreakInfo.fromJson(jsonDecode(streak) as Map<String, dynamic>);
    final friends = await _cache.read(_key('friends'));
    _friends = friends == null ? const FriendsData() : FriendsData.fromJson(jsonDecode(friends) as Map<String, dynamic>);
    final parties = await _cache.read(_key('parties'));
    _parties = parties == null
        ? const []
        : [for (final p in jsonDecode(parties) as List<dynamic>) Party.fromJson(p as Map<String, dynamic>)];
    final routes = await _cache.read(_key('routes'));
    _routes = {};
    if (routes != null) {
      (jsonDecode(routes) as Map<String, dynamic>).forEach((id, points) {
        _routes[int.parse(id)] = [for (final p in points as List<dynamic>) GeoPoint.fromJson(p as Map<String, dynamic>)];
      });
    }
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
      'meta:$id': jsonEncode({
        'completed': _completedCount,
        'active_quest': _activeQuestId,
        'party_seen': _seenPartyQuests.toList(),
      }),
      'journal:$id': jsonEncode([for (final list in _journals.values) for (final e in list) e.toJson()]),
      if (_rewards != null) 'rewards:$id': jsonEncode(_rewards!.toJson()),
      if (_streak != null) 'streak:$id': jsonEncode(_streak!.toJson()),
      'friends:$id': jsonEncode(_friends.toJson()),
      'parties:$id': jsonEncode([for (final p in _parties) p.toJson()]),
      'routes:$id': jsonEncode({
        for (final e in _routes.entries) '${e.key}': [for (final p in e.value) p.toJson()],
      }),
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
    await _trackSub?.cancel();
    _trackSub = null;
    _trackingQuestId = null;
    _routes = {};
    _here = null;
    _conditions = null;
    _locationProblem = null;
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
    _friends = const FriendsData();
    _parties = const [];
    _seenPartyQuests = {};
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
    if (isTracking(questId)) await stopTracking(); // done (or given up) - the route gets uploaded too
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
  ///
  /// Sends where you are (a fresh GPS fix, or [QuestSettings.place] if you
  /// typed one) so the quest fits the weather and real places nearby. If
  /// location isn't available the quest is still generated, just without that.
  Future<QuestRecord> generateQuest(QuestSettings settings) async {
    await sync(refresh: false); // make sure the server has the latest preferences + ratings
    final userId = _session!.account.id;
    final withWhere = await _withWhere(settings);
    final json = await _call(
      () => api.post('/users/$userId/quests', withWhere.toJson(), ApiClient.generateTimeout),
    );
    final record = QuestRecord.fromJson(json as Map<String, dynamic>, distanceKm: settings.distanceKm);
    _quests = [record, ..._quests.where((q) => q.id != record.id)];
    _activeQuestId = record.id;
    if (withWhere.location != null && record.conditions != null) _conditions = record.conditions; // freshest copy
    await _saveCache();
    notifyListeners();
    return record;
  }

  // ---------------------------------------------------------------------------
  // Location + live conditions
  // ---------------------------------------------------------------------------

  /// Typed place wins; otherwise a fresh fix (or the last one from the past
  /// 10 minutes if GPS is slow). No location = settings unchanged.
  Future<QuestSettings> _withWhere(QuestSettings settings) async {
    if (settings.location != null || settings.place.trim().isNotEmpty) return settings;
    final here = await _fix(ask: true);
    return here == null ? settings : settings.withWhere(location: here);
  }

  Future<GeoPoint?> _fix({required bool ask}) async {
    try {
      final p = await location.current(ask: ask);
      _here = p;
      _locationProblem = null;
      return p;
    } on LocationException catch (e) {
      // Not asked yet (quiet check when the tab opens): don't show it as a problem.
      _locationProblem = (!ask && e.problem == LocationProblem.denied) ? null : e.problem;
      final last = _here;
      final fresh = last?.time != null && clock().difference(last!.time!).inMinutes < 10;
      return fresh ? last : null;
    } on Object {
      _locationProblem = LocationProblem.unavailable;
      return null;
    } finally {
      notifyListeners();
    }
  }

  /// Find where you are and look up the weather + nearby spots there (shown
  /// above the Generate button). [ask]: show the permission prompt if needed.
  /// Quietly keeps the last copy when offline.
  Future<void> locate({bool ask = true, double maxTravelKm = 1.0}) async {
    if (_locating || _session == null) return;
    _locating = true;
    notifyListeners();
    try {
      final p = await _fix(ask: ask);
      if (p == null || _session == null) return;
      final userId = _session!.account.id;
      final json = await _call(() => api.get(
          '/users/$userId/conditions?lat=${p.lat}&lon=${p.lon}&max_travel_km=${maxTravelKm.toStringAsFixed(1)}'));
      _conditions = QuestConditions.fromJson(json as Map<String, dynamic>);
    } on OfflineException {
      // keep the last copy
    } on ApiException {
      // e.g. an older server without /conditions - the quest still gets the location
    } finally {
      _locating = false;
      notifyListeners();
    }
  }

  /// Open the system settings to turn location (permission) on.
  Future<void> openLocationSettings() =>
      location.openSettings(_locationProblem ?? LocationProblem.denied);

  // ---------------------------------------------------------------------------
  // Route tracking (works offline; uploaded through the outbox)
  // ---------------------------------------------------------------------------

  /// Start recording your path for [questId] (keeps any points recorded
  /// before, so you can pause and continue). Foreground only: the app needs to
  /// stay open while you walk.
  Future<void> startTracking(int questId) async {
    if (_trackingQuestId == questId) return;
    if (_trackingQuestId != null) await stopTracking();
    _trackingQuestId = questId;
    _trackingError = null;
    // Queued now (not only on stop) so a route survives the app being closed
    // mid-quest: whatever was saved gets uploaded on the next sync.
    _queueRouteUpload(questId);
    await _saveCache();
    notifyListeners();
    _trackSub = location.track().listen(
      (p) => _addPoint(questId, p),
      onError: (Object e) {
        _trackingError = e is LocationException ? e.message : "Couldn't track your location.";
        if (e is LocationException) _locationProblem = e.problem;
        unawaited(stopTracking());
      },
      cancelOnError: true,
    );
  }

  void _addPoint(int questId, GeoPoint p) {
    if (_trackingQuestId != questId) return;
    final points = _routes.putIfAbsent(questId, () => []);
    final stamped = p.time == null ? GeoPoint(lat: p.lat, lon: p.lon, accuracyM: p.accuracyM, time: clock()) : p;
    points.add(stamped);
    _here = stamped;
    _quests = [for (final q in _quests) q.id == questId ? q.withRoute(RouteSummary.measure(points)) : q];
    if (++_unsavedPoints >= 10) {
      _unsavedPoints = 0;
      unawaited(_saveCache()); // a crash/close loses at most a few points
    }
    notifyListeners();
  }

  /// Stop recording and upload the route (now or when back online).
  Future<void> stopTracking() async {
    final questId = _trackingQuestId;
    if (questId == null) return;
    _trackingQuestId = null;
    await _trackSub?.cancel();
    _trackSub = null;
    _unsavedPoints = 0;
    _queueRouteUpload(questId);
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false));
  }

  void _queueRouteUpload(int questId) {
    _outbox.removeWhere((op) => (op['type'] == 'route' || op['type'] == 'route_delete') && op['quest_id'] == questId);
    _outbox.add({'type': 'route', 'quest_id': questId}); // the whole route each time (PUT replaces it)
  }

  /// Throw away the recorded route for [questId] (here and on the server).
  Future<void> deleteRoute(int questId) async {
    if (isTracking(questId)) {
      _trackingQuestId = null;
      await _trackSub?.cancel();
      _trackSub = null;
    }
    _routes.remove(questId);
    _outbox.removeWhere((op) => op['type'] == 'route' && op['quest_id'] == questId);
    _outbox.add({'type': 'route_delete', 'quest_id': questId});
    _quests = [for (final q in _quests) q.id == questId ? q.withRoute(null) : q];
    await _saveCache();
    notifyListeners();
    unawaited(sync(refresh: false));
  }

  /// Download a quest's route if it was recorded on another device. Offline:
  /// shows nothing new.
  Future<void> loadRoute(int questId) async {
    final session = _session;
    if (session == null || (_routes[questId]?.isNotEmpty ?? false)) return;
    final matches = _quests.where((q) => q.id == questId);
    if (matches.isEmpty || matches.first.route == null) return; // nothing on the server
    try {
      final json = await _call(() => api.get('/users/${session.account.id}/quests/$questId/route'));
      if (_session?.token != session.token) return;
      _routes[questId] = [
        for (final p in (json as Map<String, dynamic>)['points'] as List<dynamic>)
          GeoPoint.fromJson(p as Map<String, dynamic>),
      ];
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // nothing cached
    } on ApiException {
      // deleted meanwhile
    }
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

  // ---------------------------------------------------------------------------
  // Friends (changes need a connection; the list is cached for offline)
  // ---------------------------------------------------------------------------

  /// Refresh friends + requests. Offline / old server: keeps the cached copy.
  Future<void> loadFriends() async {
    final session = _session;
    if (session == null) return;
    try {
      final json = await _call(() => api.get('/users/${session.account.id}/friends?$_tz'));
      if (_session?.token != session.token) return;
      _friends = FriendsData.fromJson(json as Map<String, dynamic>);
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // keep the cached copy
    } on ApiException {
      // keep the cached copy
    }
  }

  /// Ask someone to be friends by their account email. Returns who it went
  /// to and whether you're friends already (they had asked you first).
  /// Throws [ApiException] (404 no account with that email, 409 already
  /// friends / already asked, 422 your own email) or [OfflineException].
  Future<({Person person, bool nowFriends})> sendFriendRequest(String email) async {
    final userId = _session!.account.id;
    final json = await _call(
      () => api.post('/users/$userId/friends/requests', {'email': email.trim()}),
    ) as Map<String, dynamic>;
    await loadFriends();
    return (
      person: Person.fromJson(json['person'] as Map<String, dynamic>),
      nowFriends: json['status'] == 'accepted',
    );
  }

  /// Accept or decline a request someone sent you.
  Future<void> respondToFriendRequest(int requestId, {required bool accept}) async {
    final userId = _session!.account.id;
    await _call(() => api.post('/users/$userId/friends/requests/$requestId/${accept ? 'accept' : 'decline'}'));
    await loadFriends();
  }

  /// Take back a request you sent.
  Future<void> cancelFriendRequest(int requestId) async {
    final userId = _session!.account.id;
    await _call(() => api.delete('/users/$userId/friends/requests/$requestId'));
    await loadFriends();
  }

  Future<void> removeFriend(String friendId) async {
    final userId = _session!.account.id;
    await _call(() => api.delete('/users/$userId/friends/$friendId'));
    await loadFriends();
  }

  // ---------------------------------------------------------------------------
  // Group quests with friends (need a connection; the list is cached)
  // ---------------------------------------------------------------------------

  /// Refresh group quests. A group quest that just started (you're in it)
  /// becomes the quest on your Quest screen. Offline: keeps the cached copy.
  Future<void> loadParties({bool pullQuests = true}) async {
    final session = _session;
    if (session == null) return;
    try {
      final list = await _call(() => api.get('/users/${session.account.id}/parties')) as List<dynamic>;
      if (_session?.token != session.token) return;
      _parties = [for (final p in list) Party.fromJson(p as Map<String, dynamic>)];
      await _showStartedPartyQuests(session, pullQuests: pullQuests);
      await _saveCache();
      notifyListeners();
    } on OfflineException {
      // keep the cached copy
    } on ApiException {
      // keep the cached copy
    }
  }

  Future<void> _showStartedPartyQuests(Session session, {required bool pullQuests}) async {
    final fresh = [
      for (final p in _parties)
        if (!p.isOpen && p.myQuestId != null && !_seenPartyQuests.contains(p.myQuestId)) p.myQuestId!,
    ];
    if (fresh.isEmpty) return;
    if (pullQuests && fresh.any((id) => !_quests.any((q) => q.id == id))) {
      await _refresh(session); // the new quest copy isn't on the device yet
    }
    for (final id in fresh) {
      final matches = _quests.where((q) => q.id == id);
      if (matches.isEmpty) continue; // try again next time
      _seenPartyQuests.add(id);
      if (matches.first.status != QuestStatus.completed) _activeQuestId = id;
    }
  }

  /// Invite friends to a group quest with this quest's settings. The quest is
  /// generated when you start it ([startParty]).
  Future<Party> createParty(List<String> friendIds, QuestSettings settings) async {
    await sync(refresh: false); // the server needs your latest preferences
    final userId = _session!.account.id;
    final json = await _call(() => api.post('/users/$userId/parties', Party.createBody(friendIds, settings)));
    final party = Party.fromJson(json as Map<String, dynamic>);
    await loadParties();
    return party;
  }

  Future<void> joinParty(int partyId) => _partyAction(partyId, 'join');

  Future<void> declineParty(int partyId) => _partyAction(partyId, 'decline');

  /// Host only: Gemma makes ONE quest for everyone who joined (takes a while).
  /// Sends where you are, so the group quest fits the weather and places nearby.
  Future<void> startParty(int partyId, {String place = ''}) async {
    final where = place.trim().isNotEmpty ? null : await _fix(ask: true);
    final body = <String, dynamic>{
      if (where != null) 'location': where.toLocationJson(),
      if (where == null && place.trim().isNotEmpty) 'place': place.trim(),
    };
    await _partyAction(partyId, 'start', ApiClient.generateTimeout, body.isEmpty ? null : body);
  }

  /// Host only, before it starts.
  Future<void> cancelParty(int partyId) async {
    final userId = _session!.account.id;
    await _call(() => api.delete('/users/$userId/parties/$partyId'));
    await loadParties();
  }

  Future<void> _partyAction(int partyId, String action,
      [Duration timeout = ApiClient.defaultTimeout, Map<String, dynamic>? body]) async {
    final userId = _session!.account.id;
    await _call(() => api.post('/users/$userId/parties/$partyId/$action', body, timeout));
    await loadParties(); // a started quest lands on the Quest screen
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
          } else if (op['type'] == 'route') {
            final questId = op['quest_id'] as int;
            final points = _routes[questId] ?? const <GeoPoint>[];
            if (points.isNotEmpty) {
              final json = await _call(() => api.put(
                    '/users/$userId/quests/$questId/route',
                    {'points': [for (final p in points) p.toJson()]},
                  )) as Map<String, dynamic>;
              final summary = RouteSummary(
                distanceM: (json['distance_m'] as num).toInt(),
                durationSeconds: (json['duration_seconds'] as num).toInt(),
                points: points.length,
              );
              _quests = [for (final q in _quests) q.id == questId ? q.withRoute(summary) : q];
            }
          } else if (op['type'] == 'route_delete') {
            await _call(() => api.delete('/users/$userId/quests/${op['quest_id']}/route'));
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
        if (stillCurrent()) await loadFriends();
        if (stillCurrent()) await loadParties(pullQuests: false);
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
      var merged = local == null ? q : q.withFeedback(local, pending: true);
      final points = _routes[q.id];
      final routeQueued = _outbox.any((op) => op['type'] == 'route' && op['quest_id'] == q.id);
      if (points != null && points.isNotEmpty && (routeQueued || isTracking(q.id))) {
        merged = merged.withRoute(RouteSummary.measure(points)); // not uploaded yet
      } else if (_outbox.any((op) => op['type'] == 'route_delete' && op['quest_id'] == q.id)) {
        merged = merged.withRoute(null);
      }
      fresh.add(merged);
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
