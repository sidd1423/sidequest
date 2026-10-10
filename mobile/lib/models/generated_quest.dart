/// A quest from Gemma (the backend's Quest model) plus the per-quest settings
/// it was generated with.
class GeneratedQuest {
  const GeneratedQuest({
    required this.title,
    required this.summary,
    required this.steps,
    required this.minutes,
    required this.difficulty,
    required this.energy,
    this.distanceKm,
    this.tags = const [],
    this.accessibilityNotes = '',
    this.weatherBackup = '',
    this.whyItFits = '',
  });

  final String title;
  final String summary;
  final List<String> steps;
  final int minutes;
  final String difficulty; // easy | moderate | challenging | extreme
  final int energy; // 1-5
  final double? distanceKm; // the distance picked for this quest (not stored by the backend)
  final List<String> tags;
  final String accessibilityNotes;
  final String weatherBackup;
  final String whyItFits;

  /// From the backend's `quest` object.
  factory GeneratedQuest.fromJson(Map<String, dynamic> json, {double? distanceKm}) => GeneratedQuest(
        title: json['title'] as String,
        summary: json['summary'] as String,
        steps: [for (final s in json['steps'] as List<dynamic>) s as String],
        minutes: (json['estimated_minutes'] as num).toInt(),
        difficulty: json['difficulty'] as String,
        energy: (json['energy_required'] as num).toInt(),
        distanceKm: distanceKm ?? (json['_distance_km'] as num?)?.toDouble(),
        tags: [for (final t in (json['tags'] as List<dynamic>? ?? const [])) t as String],
        accessibilityNotes: (json['accessibility_notes'] as String?) ?? '',
        weatherBackup: (json['weather_backup'] as String?) ?? '',
        whyItFits: (json['why_it_fits'] as String?) ?? '',
      );

  /// For the on-device cache (backend field names, plus the distance).
  Map<String, dynamic> toJson() => {
        'title': title,
        'summary': summary,
        'steps': steps,
        'estimated_minutes': minutes,
        'difficulty': difficulty,
        'energy_required': energy,
        if (distanceKm != null) '_distance_km': distanceKm,
        'tags': tags,
        'accessibility_notes': accessibilityNotes,
        'weather_backup': weatherBackup,
        'why_it_fits': whyItFits,
      };
}

/// What the user says about a quest. Mirrors the backend's FeedbackIn.
class QuestFeedback {
  const QuestFeedback({
    required this.completed,
    this.rating,
    this.comment = '',
    this.timeLoggedMinutes = 0,
  });

  final bool completed;
  final int? rating; // 1-5; required if completed, optional otherwise
  final String comment;
  final int timeLoggedMinutes;

  factory QuestFeedback.fromJson(Map<String, dynamic> json) => QuestFeedback(
        completed: json['completed'] as bool,
        rating: (json['rating'] as num?)?.toInt(),
        comment: (json['comment'] as String?) ?? '',
        timeLoggedMinutes: (json['time_logged_minutes'] as num?)?.toInt() ?? 0,
      );

  Map<String, dynamic> toJson() => {
        'completed': completed,
        'rating': rating,
        'comment': comment,
        'time_logged_minutes': timeLoggedMinutes,
      };
}

/// The settings picked on the Quest page right before generating.
/// Sent as the body of POST /users/{id}/quests (backend QuestSettings).
class QuestSettings {
  const QuestSettings({
    required this.minutes,
    required this.difficulty,
    required this.energy,
    required this.distanceKm,
    required this.group,
  });

  final int minutes;
  final String difficulty;
  final int energy;
  final double distanceKm;
  final String group; // solo | pair | small_group | large_group

  Map<String, dynamic> toJson() => {
        'duration_minutes': minutes,
        'difficulty': difficulty,
        'energy_level': energy,
        'max_travel_km': distanceKm,
        'group_size': group,
      };
}
