/// A quest shown on the Quest page after tapping Generate, plus the
/// per-quest settings it was generated with. Placeholder content for now -
/// will come from POST /users/{id}/quests.
class GeneratedQuest {
  const GeneratedQuest({
    required this.title,
    required this.summary,
    required this.steps,
    required this.minutes,
    required this.difficulty,
    required this.energy,
    required this.distanceKm,
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
  final double distanceKm;
  final String accessibilityNotes;
  final String weatherBackup;
  final String whyItFits;
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
}
