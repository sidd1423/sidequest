/// Placeholder quest data so the History and detail screens have something to
/// show. Will be replaced by quests from the backend (GET /users/{id}/quests).
class SampleQuest {
  const SampleQuest({
    required this.id,
    required this.title,
    required this.summary,
    required this.minutes,
    required this.status,
    this.rating,
    this.steps = const [],
  });

  final int id;
  final String title;
  final String summary;
  final int minutes;
  final QuestStatus status;
  final int? rating;
  final List<String> steps;
}

enum QuestStatus { suggested, completed, skipped }

const sampleQuests = <SampleQuest>[
  SampleQuest(
    id: 3,
    title: 'Rainbow Photo Walk',
    summary: 'Photograph something of every colour of the rainbow within 15 minutes.',
    minutes: 15,
    status: QuestStatus.suggested,
    steps: ['Step outside', 'Find red, orange, yellow, green, blue and purple', 'Pick a favourite'],
  ),
  SampleQuest(
    id: 2,
    title: 'Bench Bird Count',
    summary: 'Sit outside for 5 minutes and count every bird you see or hear.',
    minutes: 10,
    status: QuestStatus.completed,
    rating: 5,
    steps: ['Find a bench', 'Count birds for 5 minutes', 'Spot one up close'],
  ),
  SampleQuest(
    id: 1,
    title: 'Stair Sprint',
    summary: 'Climb an outdoor staircase five times and time the last climb.',
    minutes: 15,
    status: QuestStatus.skipped,
    rating: 2,
    steps: ['Find stairs nearby', 'Climb five times', 'Time the last one'],
  ),
];
