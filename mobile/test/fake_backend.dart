// An in-memory stand-in for the FastAPI backend, used through http's
// MockClient so the widget tests exercise the real ApiClient + AppState.
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class FakeBackend {
  /// false = every request fails like a dropped connection.
  bool online = true;

  final users = <String, Map<String, dynamic>>{}; // id -> {id, email, name, password}
  final sessions = <String, String>{}; // token -> user id
  final preferences = <String, Map<String, dynamic>>{}; // user id -> body
  final quests = <String, List<Map<String, dynamic>>>{}; // user id -> records (newest first)
  final requests = <String>[]; // "METHOD /path" log
  final logs = <String, List<Map<String, dynamic>>>{}; // user id -> journal entries (with 'image' bytes as base64)
  int _nextLog = 1;
  Map<String, dynamic>? lastQuestSettings;

  /// Streak to return instead of the simple default (user id -> GET /streak body).
  /// Completing a quest bumps it like the real server would.
  final streakOverride = <String, Map<String, dynamic>>{};
  final streakFreezes = <String, int>{}; // bought, per user

  /// Group quests: {id, host, status open|started, members: {userId: status}, quests: {userId: questId},
  /// title, size} - like backend/parties.py.
  final parties = <Map<String, dynamic>>[];
  int _nextParty = 1;

  /// Stats the fake returns for a friend (user id -> {quests_this_week, minutes_today, current_streak}).
  final friendStats = <String, Map<String, dynamic>>{};

  /// {id, from, to, status: pending|accepted} - like backend/friends.py.
  final friendships = <Map<String, dynamic>>[];
  int _nextFriendship = 1;

  /// A friend request from [from] to [to] (as if sent from another device).
  Map<String, dynamic> addFriendship(String from, String to, {bool accepted = false}) {
    final f = {'id': _nextFriendship++, 'from': from, 'to': to, 'status': accepted ? 'accepted' : 'pending'};
    friendships.add(f);
    return f;
  }
  int _nextQuest = 1;
  int _nextToken = 1;

  late final http.Client client = MockClient(_handle);

  /// Create an account directly (as if made earlier / on another device).
  Map<String, dynamic> addUser({
    String email = 'gowtham@example.com',
    String password = 'correct horse',
    String name = 'Gowtham',
    Map<String, dynamic>? prefs,
  }) {
    final id = 'u_${users.length + 1}';
    users[id] = {'id': id, 'email': email, 'name': name, 'password': password};
    if (prefs != null) preferences[id] = prefs;
    return users[id]!;
  }

  /// A session JSON like /auth/login returns (for pre-seeding the device).
  Map<String, dynamic> sessionFor(String userId) {
    final token = 'token_${_nextToken++}';
    sessions[token] = userId;
    return {'token': token, 'token_type': 'bearer', 'user': _public(users[userId]!)};
  }

  Map<String, dynamic> addQuest(String userId, {String title = 'Bench Bird Count', Map<String, dynamic>? feedback}) {
    final record = {
      'id': _nextQuest++,
      'user_id': userId,
      'status': feedback == null ? 'suggested' : (feedback['completed'] == true ? 'completed' : 'skipped'),
      'quest': _quest(title, 10, 'easy', 2),
      'feedback': feedback,
      'created_at': DateTime.utc(2026, 10, 1).toIso8601String(),
      'model': 'fake',
    };
    quests.putIfAbsent(userId, () => []).insert(0, record);
    return record;
  }

  static Map<String, dynamic> _quest(String title, int minutes, String difficulty, int energy) => {
        'title': title,
        'summary': 'Sit outside and count every bird you see or hear.',
        'steps': ['Step outside', 'Count for five minutes', 'Note your favourite'],
        'estimated_minutes': minutes,
        'difficulty': difficulty,
        'energy_required': energy,
        'setting': 'outdoor',
        'tags': ['nature'],
        'accessibility_notes': '',
        'weather_backup': 'Find a covered bench.',
        'why_it_fits': 'You like nature.',
      };

  Map<String, dynamic> _public(Map<String, dynamic> u) =>
      {'id': u['id'], 'email': u['email'], 'name': u['name'], 'created_at': '2026-10-01T00:00:00Z'};

  http.Response _json(Object? body, [int status = 200]) =>
      http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

  http.Response _error(int status, String detail) => _json({'detail': detail}, status);

  /// A journal entry as the API returns it: no image bytes, just has_photo.
  static Map<String, dynamic> _publicLog(Map<String, dynamic> l) =>
      {...l, 'has_photo': l['image'] != null}..remove('image');

  Future<http.Response> _handle(http.Request request) async {
    if (!online) throw http.ClientException('Connection refused', request.url);
    final path = request.url.path;
    requests.add('${request.method} $path');
    final body = request.body.isEmpty ? null : jsonDecode(request.body);

    // --- auth -------------------------------------------------------------
    if (path == '/auth/signup' && request.method == 'POST') {
      final b = body as Map<String, dynamic>;
      final email = (b['email'] as String).trim().toLowerCase();
      if (users.values.any((u) => u['email'] == email)) {
        return _error(409, 'An account with this email already exists');
      }
      final u = addUser(email: email, password: b['password'] as String, name: (b['name'] as String?) ?? '');
      return _json(sessionFor(u['id'] as String), 201);
    }
    if (path == '/auth/login' && request.method == 'POST') {
      final b = body as Map<String, dynamic>;
      final email = (b['email'] as String).trim().toLowerCase();
      final matches = users.values.where((u) => u['email'] == email && u['password'] == b['password']);
      if (matches.isEmpty) return _error(401, 'Wrong email or password');
      return _json(sessionFor(matches.first['id'] as String));
    }

    final auth = request.headers['Authorization'] ?? '';
    final userId = auth.startsWith('Bearer ') ? sessions[auth.substring(7)] : null;
    if (userId == null) return _error(401, 'Log in again - your session is missing or has expired');

    if (path == '/auth/logout') {
      sessions.remove(auth.substring(7));
      return http.Response('', 204);
    }
    if (path == '/auth/me' && request.method == 'DELETE') {
      final b = body as Map<String, dynamic>;
      if (users[userId]!['password'] != b['password']) return _error(403, 'Wrong password');
      users.remove(userId);
      sessions.removeWhere((_, uid) => uid == userId);
      preferences.remove(userId);
      quests.remove(userId);
      logs.remove(userId);
      return http.Response('', 204);
    }
    if (path == '/auth/me' && request.method == 'PATCH') {
      final u = users[userId]!;
      final b = body as Map<String, dynamic>;
      if (b['name'] != null) u['name'] = b['name'];
      if (b['email'] != null) u['email'] = (b['email'] as String).toLowerCase();
      return _json(_public(u));
    }

    // --- /users/{id}/... ----------------------------------------------------
    final segments = request.url.pathSegments;
    if (segments.length < 3 || segments[0] != 'users') return _error(404, 'Not found');
    if (segments[1] != userId) return _error(403, 'You can only access your own data');

    if (segments[2] == 'rewards') {
      // Simplified stand-in for backend/rewards.py: 10 points per completed quest.
      final done = (quests[userId] ?? []).where((q) => q['status'] == 'completed').toList();
      final points = done.length * 10;
      return _json({
        'points': points,
        'level': points >= 50 ? 2 : 1,
        'level_name': points >= 50 ? 'Stroller' : 'Homebody',
        'level_floor': points >= 50 ? 50 : 0,
        'next_level_at': points >= 50 ? 150 : 50,
        'next_level_name': points >= 50 ? 'Wanderer' : 'Stroller',
        'current_streak': done.isEmpty ? 0 : 1,
        'best_streak': done.isEmpty ? 0 : 1,
        'completed': done.length,
        'minutes_outside': 0,
        'photos': 0,
        'badges': [
          {'id': 'first_quest', 'name': 'First steps', 'description': 'Complete your first quest',
           'earned': done.isNotEmpty, 'progress': done.isEmpty ? 0 : 1, 'goal': 1},
        ],
        'recent': [
          for (final q in done)
            {'quest_id': q['id'], 'title': (q['quest'] as Map<String, dynamic>)['title'], 'points': 10,
             'reasons': ['+10 easy quest'], 'date': q['created_at']},
        ],
      });
    }
    if (segments[2] == 'streak') {
      if (segments.length == 4 && segments[3] == 'freeze' && request.method == 'POST') {
        final current = _streak(userId);
        final points = current['spendable_points'] as int;
        if ((current['freezes'] as int) >= 2) {
          return _error(409, "You already have 2 streak freezes - that's the most you can hold");
        }
        if (points < 100) return _error(409, 'A streak freeze costs 100 points - you have $points');
        streakFreezes[userId] = (streakFreezes[userId] ?? 0) + 1;
        final o = streakOverride[userId];
        if (o != null) o['freezes'] = (o['freezes'] as int) + 1;
        return _json(_streak(userId), 201);
      }
      return _json(_streak(userId));
    }
    if (segments[2] == 'friends') return _friendsRoute(request, segments, userId, body);
    if (segments[2] == 'parties') return _partiesRoute(request, segments, userId, body);
    if (segments[2] == 'stats') {
      final list = quests[userId] ?? [];
      return _json({
        'completed': list.where((q) => q['status'] == 'completed').length,
        'generated': list.length,
        'minutes_outside': 0,
      });
    }
    if (segments[2] == 'logs' && segments.length == 5 && segments[4] == 'photo') {
      final id = int.parse(segments[3]);
      final matches = (logs[userId] ?? []).where((l) => l['id'] == id && l['image'] != null);
      if (matches.isEmpty) return _error(404, 'Photo not found');
      return http.Response.bytes(base64Decode(matches.first['image'] as String), 200,
          headers: {'content-type': matches.first['mime'] as String});
    }
    if (segments[2] == 'logs' && segments.length == 4 && request.method == 'DELETE') {
      logs[userId]?.removeWhere((l) => l['client_id'] == segments[3]);
      return http.Response('', 204);
    }
    if (segments[2] == 'quests' && segments.length == 5 && segments[4] == 'logs') {
      final qid = int.parse(segments[3]);
      if (!(quests[userId] ?? []).any((q) => q['id'] == qid)) return _error(404, 'Quest not found');
      final mine = logs.putIfAbsent(userId, () => []);
      if (request.method == 'GET') {
        return _json([
          for (final l in mine.where((l) => l['quest_id'] == qid))
            _publicLog(l),
        ]);
      }
      final b = body as Map<String, dynamic>;
      final existing = mine.where((l) => l['client_id'] == b['client_id']);
      if (existing.isNotEmpty) return _json(_publicLog(existing.first), 201);
      final entry = <String, dynamic>{
        'id': _nextLog++,
        'quest_id': qid,
        'client_id': b['client_id'],
        'kind': b['kind'],
        'text': b['text'] ?? '',
        'mime': b['mime'],
        'image': b['image_base64'],
        'created_at': b['created_at'] ?? DateTime.now().toUtc().toIso8601String(),
      };
      mine.add(entry);
      return _json(_publicLog(entry), 201);
    }
    if (segments[2] == 'preferences') {
      if (request.method == 'PUT') {
        preferences[userId] = body as Map<String, dynamic>;
        return _json({...preferences[userId]!, 'user_id': userId});
      }
      final p = preferences[userId];
      return p == null ? _error(404, 'No preferences saved for this user') : _json({...p, 'user_id': userId});
    }
    if (segments[2] == 'quests' && segments.length == 3) {
      if (request.method == 'GET') return _json([for (final q in quests[userId] ?? []) _withParty(q)]);
      if (preferences[userId] == null) return _error(404, 'Save preferences before generating a quest');
      final s = (body as Map<String, dynamic>?) ?? const {};
      lastQuestSettings = s;
      final n = _nextQuest;
      final record = addQuest(userId, title: 'Quest #$n');
      record['quest'] = _quest(
        'Quest #$n',
        (s['duration_minutes'] as int?) ?? 15,
        (s['difficulty'] as String?) ?? 'moderate',
        (s['energy_level'] as int?) ?? 3,
      );
      return _json(record, 201);
    }
    if (segments[2] == 'quests' && segments.length == 5 && segments[4] == 'feedback') {
      final id = int.parse(segments[3]);
      final list = quests[userId] ?? [];
      final matches = list.where((q) => q['id'] == id);
      if (matches.isEmpty) return _error(404, 'Quest not found');
      final record = matches.first;
      final fb = body as Map<String, dynamic>;
      final newlyCompleted = fb['completed'] == true && record['status'] != 'completed';
      record['completed_at'] = fb.remove('completed_at'); // like the server: not part of the feedback
      record['feedback'] = fb;
      record['status'] = fb['completed'] == true ? 'completed' : 'skipped';
      final o = streakOverride[userId];
      if (newlyCompleted && o != null && o['extended_today'] != true) {
        o['current'] = (o['current'] as int) + 1;
        o['extended_today'] = true;
        if ((o['current'] as int) % 7 == 0 && (o['freezes'] as int) < 2) o['freezes'] = (o['freezes'] as int) + 1;
        o['completed_days'] = [...o['completed_days'] as List<dynamic>, o['today']];
      }
      return _json(record);
    }
    return _error(404, 'Not found');
  }
}

extension on FakeBackend {
  Map<String, dynamic> _withParty(Map<String, dynamic> q) {
    for (final p in parties) {
      if ((p['quests'] as Map<String, dynamic>).containsValue(q['id'])) {
        final members = p['members'] as Map<String, dynamic>;
        return {
          ...q,
          'party': {
            'party_id': p['id'],
            'host_id': p['host'],
            'size': p['size'],
            'members': [
              for (final e in members.entries) {'user_id': e.key, 'name': users[e.key]!['name'], 'status': e.value},
            ],
          },
        };
      }
    }
    return q;
  }

  Map<String, dynamic> _partyJson(Map<String, dynamic> p, String viewer) {
    final members = p['members'] as Map<String, dynamic>;
    final quests = p['quests'] as Map<String, dynamic>;
    return {
      'id': p['id'],
      'host_id': p['host'],
      'host_name': users[p['host']]!['name'],
      'status': p['status'],
      'created_at': '2026-10-01T00:00:00Z',
      'members': [
        for (final e in members.entries)
          {'user_id': e.key, 'name': users[e.key]!['name'], 'email': users[e.key]!['email'], 'status': e.value,
           'is_host': e.key == p['host']},
      ],
      'joined': members.values.where((s) => s == 'joined').length,
      'size': p['size'],
      'my_status': viewer == p['host'] ? 'host' : members[viewer],
      'my_quest_id': quests[viewer],
      'quest_title': p['title'],
      'settings': p['settings'],
    };
  }

  http.Response _partiesRoute(http.Request request, List<String> segments, String userId, dynamic body) {
    // GET /users/{id}/parties
    if (segments.length == 3 && request.method == 'GET') {
      return _json([
        for (final p in parties.reversed)
          if ((p['members'] as Map<String, dynamic>).containsKey(userId) &&
              (p['members'] as Map<String, dynamic>)[userId] != 'declined')
            _partyJson(p, userId),
      ]);
    }
    // POST /users/{id}/parties {friend_ids, settings}
    if (segments.length == 3 && request.method == 'POST') {
      final b = body as Map<String, dynamic>;
      final p = <String, dynamic>{
        'id': _nextParty++,
        'host': userId,
        'status': 'open',
        'members': <String, dynamic>{userId: 'joined', for (final f in b['friend_ids'] as List<dynamic>) f as String: 'invited'},
        'quests': <String, dynamic>{},
        'title': null,
        'size': null,
        'settings': b['settings'],
      };
      parties.add(p);
      return _json(_partyJson(p, userId), 201);
    }
    final matches = parties.where((p) => p['id'] == int.parse(segments[3]) &&
        (p['members'] as Map<String, dynamic>).containsKey(userId));
    if (matches.isEmpty) return _error(404, 'Group quest not found');
    final p = matches.first;
    final members = p['members'] as Map<String, dynamic>;
    if (segments.length == 4 && request.method == 'DELETE') {
      if (p['host'] != userId) return _error(403, 'Only the host can cancel the group quest');
      parties.remove(p);
      return http.Response('', 204);
    }
    final action = segments[4];
    if (action == 'join' || action == 'decline') {
      if (members[userId] != 'invited') return _error(409, 'You already ${members[userId]} this group quest');
      members[userId] = action == 'join' ? 'joined' : 'declined';
      if (action == 'join' && p['status'] == 'started') {
        (p['quests'] as Map<String, dynamic>)[userId] = addQuest(userId, title: p['title'] as String)['id'];
      }
      return _json(_partyJson(p, userId));
    }
    if (action == 'start') {
      if (p['host'] != userId) return _error(403, 'Only the host can start the group quest');
      final joined = [for (final e in members.entries) if (e.value == 'joined') e.key];
      if (joined.length < 2) return _error(409, 'Wait until at least one friend has joined');
      p['status'] = 'started';
      p['title'] = 'Group Quest #${p['id']}';
      p['size'] = joined.length;
      for (final m in joined) {
        (p['quests'] as Map<String, dynamic>)[m] = addQuest(m, title: p['title'] as String)['id'];
      }
      return _json(_partyJson(p, userId));
    }
    return _error(404, 'Not found');
  }

  Map<String, dynamic> _person(String id) =>
      {'user_id': id, 'name': users[id]!['name'], 'email': users[id]!['email']};

  http.Response _friendsRoute(http.Request request, List<String> segments, String userId, dynamic body) {
    Map<String, dynamic>? pair(String a, String b) {
      final m = friendships.where((f) => (f['from'] == a && f['to'] == b) || (f['from'] == b && f['to'] == a));
      return m.isEmpty ? null : m.first;
    }

    String other(Map<String, dynamic> f) => (f['from'] == userId ? f['to'] : f['from']) as String;
    final created = DateTime.utc(2026, 10, 1).toIso8601String();

    // GET /users/{id}/friends
    if (segments.length == 3 && request.method == 'GET') {
      final mine = friendships.where((f) => (f['from'] == userId || f['to'] == userId) && users.containsKey(other(f)));
      return _json({
        'friends': [
          for (final f in mine.where((f) => f['status'] == 'accepted'))
            {
              ..._person(other(f)),
              'since': created,
              'completed': (quests[other(f)] ?? []).where((q) => q['status'] == 'completed').length,
              'points': 0,
              'level_name': 'Homebody',
              'current_streak': 0,
              'quests_this_week': 0,
              'minutes_today': 0,
              ...?friendStats[other(f)],
            },
        ],
        'incoming': [
          for (final f in mine.where((f) => f['status'] == 'pending' && f['to'] == userId))
            {'request_id': f['id'], 'person': _person(f['from'] as String), 'created_at': created},
        ],
        'outgoing': [
          for (final f in mine.where((f) => f['status'] == 'pending' && f['from'] == userId))
            {'request_id': f['id'], 'person': _person(f['to'] as String), 'created_at': created},
        ],
      });
    }
    // POST /users/{id}/friends/requests {email}
    if (segments.length == 4 && segments[3] == 'requests' && request.method == 'POST') {
      final email = ((body as Map<String, dynamic>)['email'] as String).trim().toLowerCase();
      final matches = users.values.where((u) => u['email'] == email);
      if (matches.isEmpty) return _error(404, "There's no Sidequest account with that email");
      final to = matches.first['id'] as String;
      if (to == userId) return _error(422, "That's your own email");
      final existing = pair(userId, to);
      if (existing != null) {
        if (existing['status'] == 'accepted') return _error(409, "You're already friends");
        if (existing['from'] == userId) return _error(409, 'You already sent them a friend request');
        existing['status'] = 'accepted';
        return _json({'status': 'accepted', 'request_id': existing['id'], 'person': _person(to)}, 201);
      }
      final f = addFriendship(userId, to);
      return _json({'status': 'pending', 'request_id': f['id'], 'person': _person(to)}, 201);
    }
    // POST .../requests/{rid}/accept|decline, DELETE .../requests/{rid}
    if (segments.length >= 5 && segments[3] == 'requests') {
      final rid = int.parse(segments[4]);
      final mineToAnswer = segments.length == 6;
      final matches = friendships.where((f) =>
          f['id'] == rid && f['status'] == 'pending' && f[mineToAnswer ? 'to' : 'from'] == userId);
      if (matches.isEmpty) return _error(404, 'Friend request not found');
      final f = matches.first;
      if (mineToAnswer && segments[5] == 'accept') {
        f['status'] = 'accepted';
      } else {
        friendships.remove(f);
      }
      return http.Response('', 204);
    }
    // DELETE /users/{id}/friends/{friend_id}
    if (segments.length == 4 && request.method == 'DELETE') {
      final f = pair(userId, segments[3]);
      if (f == null || f['status'] != 'accepted') return _error(404, "You're not friends with this person");
      friendships.remove(f);
      return http.Response('', 204);
    }
    return _error(404, 'Not found');
  }

  /// Simplified backend/streak.py: 1-day streak once anything is completed;
  /// 10 points per completed quest, 100 per freeze bought.
  Map<String, dynamic> _streak(String userId) {
    final spent = (streakFreezes[userId] ?? 0) * 100;
    final done = (quests[userId] ?? []).where((q) => q['status'] == 'completed').length;
    final override = streakOverride[userId];
    final today = fakeToday();
    final base = override ??
        {
          'current': done > 0 ? 1 : 0,
          'best': done > 0 ? 1 : 0,
          'extended_today': done > 0,
          'freezes': streakFreezes[userId] ?? 0,
          'next_milestone': 3,
          'lost_streak': 0,
          'today': today,
          'completed_days': [if (done > 0) today],
          'frozen_days': <String>[],
        };
    final points = done * 10 - spent;
    return {
      ...base,
      'max_freezes': 2,
      'freeze_cost': 100,
      'freeze_every': 7,
      'spendable_points': points,
      'can_buy_freeze': (base['freezes'] as int) < 2 && points >= 100,
      'milestones': [3, 7, 14, 30, 50, 100, 180, 365, 500, 1000],
    };
  }
}

/// Today's date like the server sends it (YYYY-MM-DD, the device's time zone).
String fakeToday([int daysAgo = 0]) {
  final now = DateTime.now();
  final d = DateTime(now.year, now.month, now.day - daysAgo);
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

/// Preferences body a returning user already has on the server.
const savedPrefs = <String, dynamic>{
  'interests': ['nature'],
  'custom_interests': <String>[],
  'difficulty': 'easy',
  'energy_level': 2,
  'availability': {'duration_minutes': 15},
  'accessibility': {'needs': <String>[], 'notes': ''},
  'environment': {'surroundings': <String>[], 'crowd_tolerance': 'quiet', 'group_size': 'solo', 'max_travel_km': 1.0},
  'weather': {'avoid': <String>[], 'min_temp_c': 5, 'max_temp_c': 30},
};
