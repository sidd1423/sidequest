import 'generated_quest.dart';

/// Group quests with friends (backend/parties.py): the host invites friends,
/// they join, the host starts it and everyone who joined gets the same quest.
class PartyMember {
  const PartyMember({required this.userId, required this.name, required this.status, this.isHost = false});

  final String userId;
  final String name;
  final String status; // invited | joined | declined
  final bool isHost;

  bool get joined => status == 'joined';

  factory PartyMember.fromJson(Map<String, dynamic> json) => PartyMember(
        userId: json['user_id'] as String,
        name: (json['name'] as String?) ?? '',
        status: json['status'] as String,
        isHost: (json['is_host'] as bool?) ?? false,
      );

  Map<String, dynamic> toJson() => {'user_id': userId, 'name': name, 'status': status, 'is_host': isHost};
}

/// On a quest that belongs to a group quest (QuestRecord.party).
class PartyTag {
  const PartyTag({required this.partyId, required this.hostId, required this.size, required this.members});

  final int partyId;
  final String hostId;
  final int size; // people the quest was made for
  final List<PartyMember> members;

  int get joined => members.where((m) => m.joined).length;

  factory PartyTag.fromJson(Map<String, dynamic> json) {
    final hostId = json['host_id'] as String;
    return PartyTag(
      partyId: (json['party_id'] as num).toInt(),
      hostId: hostId,
      size: (json['size'] as num).toInt(),
      members: [
        for (final m in json['members'] as List<dynamic>)
          PartyMember.fromJson({...m as Map<String, dynamic>, 'is_host': m['user_id'] == hostId}),
      ],
    );
  }

  Map<String, dynamic> toJson() => {
        'party_id': partyId,
        'host_id': hostId,
        'size': size,
        'members': [for (final m in members) m.toJson()],
      };
}

/// GET /users/{id}/parties item.
class Party {
  const Party({
    required this.id,
    required this.hostId,
    required this.hostName,
    required this.status,
    required this.members,
    required this.joined,
    required this.myStatus,
    this.size,
    this.myQuestId,
    this.questTitle,
    this.settings,
  });

  final int id;
  final String hostId;
  final String hostName;
  final String status; // open | started
  final List<PartyMember> members; // host first
  final int joined; // people in, host included
  final String myStatus; // host | invited | joined | declined
  final int? size;
  final int? myQuestId;
  final String? questTitle;
  final Map<String, dynamic>? settings; // QuestSettings JSON

  bool get isOpen => status == 'open';
  bool get isHost => myStatus == 'host';
  bool get isInvite => myStatus == 'invited';
  bool get canStart => isHost && isOpen && joined >= 2;
  int? get minutes => (settings?['duration_minutes'] as num?)?.toInt();

  factory Party.fromJson(Map<String, dynamic> json) => Party(
        id: (json['id'] as num).toInt(),
        hostId: json['host_id'] as String,
        hostName: (json['host_name'] as String?) ?? '',
        status: json['status'] as String,
        members: [for (final m in json['members'] as List<dynamic>) PartyMember.fromJson(m as Map<String, dynamic>)],
        joined: (json['joined'] as num).toInt(),
        myStatus: json['my_status'] as String,
        size: (json['size'] as num?)?.toInt(),
        myQuestId: (json['my_quest_id'] as num?)?.toInt(),
        questTitle: json['quest_title'] as String?,
        settings: json['settings'] as Map<String, dynamic>?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'host_id': hostId,
        'host_name': hostName,
        'status': status,
        'members': [for (final m in members) m.toJson()],
        'joined': joined,
        'my_status': myStatus,
        'size': size,
        'my_quest_id': myQuestId,
        'quest_title': questTitle,
        'settings': settings,
      };

  /// Body for POST /users/{id}/parties.
  static Map<String, dynamic> createBody(List<String> friendIds, QuestSettings settings) =>
      {'friend_ids': friendIds, 'settings': settings.toJson()};
}
