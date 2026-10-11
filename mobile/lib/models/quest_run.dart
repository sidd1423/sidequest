/// A quest being done step by step: when it was started (the timer), which
/// step is showing, and how it ended. Kept on the device only (in the cache
/// "meta"), so the timer keeps running if the app is closed mid-quest. What
/// the server gets is the time spent, with the rating.
class QuestRun {
  const QuestRun({
    required this.questId,
    required this.startedAt,
    this.step = 0,
    this.endedAt,
    this.gaveUp = false,
  });

  final int questId;
  final DateTime startedAt;

  /// The step on screen, 0-based.
  final int step;

  /// Set when they tapped "Finish quest" or "Give up" (the timer stops).
  final DateTime? endedAt;
  final bool gaveUp;

  bool get ended => endedAt != null;

  /// Time on the clock (stops once ended; never negative).
  Duration elapsed(DateTime now) {
    final d = (endedAt ?? now).difference(startedAt);
    return d.isNegative ? Duration.zero : d;
  }

  /// Whole minutes for the rating form. A finished quest counts at least 1.
  int minutes(DateTime now) {
    final m = (elapsed(now).inSeconds / 60).round();
    return gaveUp ? m : (m < 1 ? 1 : m);
  }

  QuestRun atStep(int step) =>
      QuestRun(questId: questId, startedAt: startedAt, step: step, endedAt: endedAt, gaveUp: gaveUp);

  QuestRun end(DateTime at, {required bool gaveUp}) =>
      QuestRun(questId: questId, startedAt: startedAt, step: step, endedAt: at, gaveUp: gaveUp);

  /// "Oops, keep going": back to the steps, the timer runs again.
  QuestRun resumed() => QuestRun(questId: questId, startedAt: startedAt, step: step);

  factory QuestRun.fromJson(Map<String, dynamic> json) => QuestRun(
        questId: (json['quest_id'] as num).toInt(),
        startedAt: DateTime.parse(json['started_at'] as String),
        step: (json['step'] as num?)?.toInt() ?? 0,
        endedAt: json['ended_at'] == null ? null : DateTime.parse(json['ended_at'] as String),
        gaveUp: (json['gave_up'] as bool?) ?? false,
      );

  Map<String, dynamic> toJson() => {
        'quest_id': questId,
        'started_at': startedAt.toUtc().toIso8601String(),
        'step': step,
        if (endedAt != null) 'ended_at': endedAt!.toUtc().toIso8601String(),
        if (gaveUp) 'gave_up': true,
      };
}

/// "4:05" or "1:02:09".
String formatElapsed(Duration d) {
  String two(int n) => n.toString().padLeft(2, '0');
  final h = d.inHours;
  final m = d.inMinutes % 60;
  final s = d.inSeconds % 60;
  return h > 0 ? '$h:${two(m)}:${two(s)}' : '$m:${two(s)}';
}
