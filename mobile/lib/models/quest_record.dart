import 'generated_quest.dart';

enum QuestStatus { suggested, completed, skipped }

/// A stored quest (backend QuestRecord): the quest, its status and feedback.
class QuestRecord {
  const QuestRecord({
    required this.id,
    required this.quest,
    required this.createdAt,
    this.status = QuestStatus.suggested,
    this.feedback,
    this.feedbackPending = false,
  });

  final int id;
  final GeneratedQuest quest;
  final QuestStatus status;
  final QuestFeedback? feedback;
  final DateTime createdAt;

  /// Feedback was given offline and hasn't reached the server yet.
  final bool feedbackPending;

  String get title => quest.title;
  int? get rating => feedback?.rating;

  QuestRecord withFeedback(QuestFeedback f, {bool pending = false}) => QuestRecord(
        id: id,
        quest: quest,
        createdAt: createdAt,
        status: f.completed ? QuestStatus.completed : QuestStatus.skipped,
        feedback: f,
        feedbackPending: pending,
      );

  factory QuestRecord.fromJson(Map<String, dynamic> json, {double? distanceKm}) {
    final fb = json['feedback'] as Map<String, dynamic>?;
    return QuestRecord(
      id: (json['id'] as num).toInt(),
      quest: GeneratedQuest.fromJson(json['quest'] as Map<String, dynamic>, distanceKm: distanceKm),
      status: QuestStatus.values.firstWhere(
        (s) => s.name == json['status'],
        orElse: () => QuestStatus.suggested,
      ),
      feedback: fb == null ? null : QuestFeedback.fromJson(fb),
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
      feedbackPending: (json['_feedback_pending'] as bool?) ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'quest': quest.toJson(),
        'status': status.name,
        'feedback': feedback?.toJson(),
        'created_at': createdAt.toIso8601String(),
        if (feedbackPending) '_feedback_pending': true,
      };
}
