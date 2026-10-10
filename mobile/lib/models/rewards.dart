/// Points, level, streaks and badges (GET /users/{id}/rewards).
/// The rules live on the server: backend/rewards.py.
class Rewards {
  const Rewards({
    required this.points,
    required this.level,
    required this.levelName,
    required this.levelFloor,
    required this.nextLevelAt,
    required this.nextLevelName,
    required this.currentStreak,
    required this.bestStreak,
    required this.completed,
    required this.minutesOutside,
    required this.photos,
    required this.badges,
    required this.recent,
  });

  final int points;
  final int level;
  final String levelName;
  final int levelFloor;
  final int? nextLevelAt;
  final String? nextLevelName;
  final int currentStreak;
  final int bestStreak;
  final int completed;
  final int minutesOutside;
  final int photos;
  final List<RewardBadge> badges;
  final List<PointsEntry> recent;

  /// 0..1 progress from this level to the next (1 at the top level).
  double get levelProgress {
    final next = nextLevelAt;
    if (next == null || next <= levelFloor) return 1;
    return ((points - levelFloor) / (next - levelFloor)).clamp(0.0, 1.0);
  }

  int get earnedBadges => badges.where((b) => b.earned).length;

  factory Rewards.fromJson(Map<String, dynamic> json) => Rewards(
        points: (json['points'] as num).toInt(),
        level: (json['level'] as num).toInt(),
        levelName: json['level_name'] as String,
        levelFloor: (json['level_floor'] as num).toInt(),
        nextLevelAt: (json['next_level_at'] as num?)?.toInt(),
        nextLevelName: json['next_level_name'] as String?,
        currentStreak: (json['current_streak'] as num).toInt(),
        bestStreak: (json['best_streak'] as num).toInt(),
        completed: (json['completed'] as num).toInt(),
        minutesOutside: (json['minutes_outside'] as num).toInt(),
        photos: (json['photos'] as num).toInt(),
        badges: [for (final b in json['badges'] as List<dynamic>) RewardBadge.fromJson(b as Map<String, dynamic>)],
        recent: [for (final e in json['recent'] as List<dynamic>) PointsEntry.fromJson(e as Map<String, dynamic>)],
      );

  Map<String, dynamic> toJson() => {
        'points': points,
        'level': level,
        'level_name': levelName,
        'level_floor': levelFloor,
        'next_level_at': nextLevelAt,
        'next_level_name': nextLevelName,
        'current_streak': currentStreak,
        'best_streak': bestStreak,
        'completed': completed,
        'minutes_outside': minutesOutside,
        'photos': photos,
        'badges': [for (final b in badges) b.toJson()],
        'recent': [for (final e in recent) e.toJson()],
      };
}

class RewardBadge {
  const RewardBadge({
    required this.id,
    required this.name,
    required this.description,
    required this.earned,
    required this.progress,
    required this.goal,
  });

  final String id;
  final String name;
  final String description;
  final bool earned;
  final int progress;
  final int goal;

  factory RewardBadge.fromJson(Map<String, dynamic> json) => RewardBadge(
        id: json['id'] as String,
        name: json['name'] as String,
        description: json['description'] as String,
        earned: json['earned'] as bool,
        progress: (json['progress'] as num).toInt(),
        goal: (json['goal'] as num).toInt(),
      );

  Map<String, dynamic> toJson() =>
      {'id': id, 'name': name, 'description': description, 'earned': earned, 'progress': progress, 'goal': goal};
}

class PointsEntry {
  const PointsEntry({
    required this.questId,
    required this.title,
    required this.points,
    required this.reasons,
    required this.date,
  });

  final int questId;
  final String title;
  final int points;
  final List<String> reasons;
  final DateTime date;

  factory PointsEntry.fromJson(Map<String, dynamic> json) => PointsEntry(
        questId: (json['quest_id'] as num).toInt(),
        title: json['title'] as String,
        points: (json['points'] as num).toInt(),
        reasons: [for (final r in json['reasons'] as List<dynamic>) r as String],
        date: DateTime.tryParse(json['date'] as String? ?? '') ?? DateTime.now(),
      );

  Map<String, dynamic> toJson() => {
        'quest_id': questId,
        'title': title,
        'points': points,
        'reasons': reasons,
        'date': date.toIso8601String(),
      };
}
