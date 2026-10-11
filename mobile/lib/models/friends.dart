/// Friends (GET /users/{id}/friends). Rules live in backend/friends.py.
class Person {
  const Person({required this.userId, required this.name, required this.email});

  final String userId;
  final String name;
  final String email;

  /// Name if they set one, otherwise their email.
  String get displayName => name.trim().isEmpty ? email : name;

  String get initial => displayName.isEmpty ? '?' : displayName.substring(0, 1).toUpperCase();

  factory Person.fromJson(Map<String, dynamic> json) => Person(
        userId: json['user_id'] as String,
        name: (json['name'] as String?) ?? '',
        email: json['email'] as String,
      );

  Map<String, dynamic> toJson() => {'user_id': userId, 'name': name, 'email': email};
}

class Friend extends Person {
  const Friend({
    required super.userId,
    required super.name,
    required super.email,
    required this.since,
    this.completed = 0,
    this.questsThisWeek = 0,
    this.minutesToday = 0,
    this.points = 0,
    this.levelName = '',
    this.currentStreak = 0,
  });

  final DateTime since;
  final int completed;
  final int questsThisWeek; // completed since Monday
  final int minutesToday; // time logged on quests today
  final int points;
  final String levelName;
  final int currentStreak;

  factory Friend.fromJson(Map<String, dynamic> json) => Friend(
        userId: json['user_id'] as String,
        name: (json['name'] as String?) ?? '',
        email: json['email'] as String,
        since: DateTime.tryParse(json['since'] as String? ?? '') ?? DateTime.now(),
        completed: (json['completed'] as num?)?.toInt() ?? 0,
        questsThisWeek: (json['quests_this_week'] as num?)?.toInt() ?? 0,
        minutesToday: (json['minutes_today'] as num?)?.toInt() ?? 0,
        points: (json['points'] as num?)?.toInt() ?? 0,
        levelName: (json['level_name'] as String?) ?? '',
        currentStreak: (json['current_streak'] as num?)?.toInt() ?? 0,
      );

  @override
  Map<String, dynamic> toJson() => {
        ...super.toJson(),
        'since': since.toIso8601String(),
        'completed': completed,
        'quests_this_week': questsThisWeek,
        'minutes_today': minutesToday,
        'points': points,
        'level_name': levelName,
        'current_streak': currentStreak,
      };
}

class FriendRequest {
  const FriendRequest({required this.id, required this.person, required this.createdAt});

  final int id;
  final Person person; // the other person
  final DateTime createdAt;

  factory FriendRequest.fromJson(Map<String, dynamic> json) => FriendRequest(
        id: (json['request_id'] as num).toInt(),
        person: Person.fromJson(json['person'] as Map<String, dynamic>),
        createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
      );

  Map<String, dynamic> toJson() =>
      {'request_id': id, 'person': person.toJson(), 'created_at': createdAt.toIso8601String()};
}

class FriendsData {
  const FriendsData({this.friends = const [], this.incoming = const [], this.outgoing = const []});

  final List<Friend> friends;
  final List<FriendRequest> incoming; // waiting for you to accept
  final List<FriendRequest> outgoing; // you asked, waiting for them

  factory FriendsData.fromJson(Map<String, dynamic> json) => FriendsData(
        friends: [for (final f in json['friends'] as List<dynamic>? ?? const []) Friend.fromJson(f as Map<String, dynamic>)],
        incoming: [
          for (final r in json['incoming'] as List<dynamic>? ?? const []) FriendRequest.fromJson(r as Map<String, dynamic>)
        ],
        outgoing: [
          for (final r in json['outgoing'] as List<dynamic>? ?? const []) FriendRequest.fromJson(r as Map<String, dynamic>)
        ],
      );

  Map<String, dynamic> toJson() => {
        'friends': [for (final f in friends) f.toJson()],
        'incoming': [for (final r in incoming) r.toJson()],
        'outgoing': [for (final r in outgoing) r.toJson()],
      };
}
