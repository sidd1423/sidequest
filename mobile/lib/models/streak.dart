/// Duolingo-style daily streak (GET /users/{id}/streak).
/// The rules live on the server: backend/streak.py. The app keeps the last
/// copy and rolls it forward by itself (new day, quest completed offline) so
/// the flame is right even without a connection.
class StreakInfo {
  const StreakInfo({
    required this.current,
    required this.best,
    required this.extendedToday,
    required this.freezes,
    required this.maxFreezes,
    required this.freezeCost,
    required this.freezeEvery,
    required this.spendablePoints,
    required this.nextMilestone,
    required this.milestones,
    required this.lostStreak,
    required this.today,
    required this.completedDays,
    required this.frozenDays,
  });

  /// Before anything has been loaded.
  factory StreakInfo.empty(DateTime today) => StreakInfo(
        current: 0,
        best: 0,
        extendedToday: false,
        freezes: 0,
        maxFreezes: 2,
        freezeCost: 100,
        freezeEvery: 7,
        spendablePoints: 0,
        nextMilestone: 3,
        milestones: defaultMilestones,
        lostStreak: 0,
        today: dateOnly(today),
        completedDays: const <DateTime>{},
        frozenDays: const <DateTime>{},
      );

  static const defaultMilestones = [3, 7, 14, 30, 50, 100, 180, 365, 500, 1000];

  final int current;
  final int best;
  final bool extendedToday;
  final int freezes;
  final int maxFreezes;
  final int freezeCost;
  final int freezeEvery;
  final int spendablePoints;
  final int? nextMilestone;
  final List<int> milestones;
  final int lostStreak;

  /// The user's local date these numbers are for.
  final DateTime today;
  final Set<DateTime> completedDays;
  final Set<DateTime> frozenDays;

  /// A streak is running but today isn't done yet.
  bool get atRisk => current > 0 && !extendedToday;

  bool get canBuyFreeze => freezes < maxFreezes && spendablePoints >= freezeCost;

  /// Today's count is a milestone (3, 7, 14, 30 ... days).
  bool get isMilestone => extendedToday && milestones.contains(current);

  /// 0..1 progress from the previous milestone to the next one.
  double get milestoneProgress {
    final next = nextMilestone;
    if (next == null) return 1;
    final previous = milestones.where((m) => m <= current).fold<int>(0, (a, b) => b > a ? b : a);
    if (next <= previous) return 1;
    return ((current - previous) / (next - previous)).clamp(0.0, 1.0);
  }

  /// Days until the free freeze (one every [freezeEvery] streak days).
  int get daysToFreeFreeze => freezeEvery - (current % freezeEvery);

  static DateTime dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

  /// This copy rolled forward to [now] (the user's local time): days that
  /// passed since the server's copy use a freeze or break the streak, exactly
  /// like the server would.
  StreakInfo asOf(DateTime now) {
    final target = dateOnly(now);
    if (!target.isAfter(today)) return this;
    var cur = current;
    var held = freezes;
    var lost = lostStreak;
    final frozen = {...frozenDays};
    // Every day from the copy's "today" up to yesterday has now ended.
    for (var day = today; day.isBefore(target); day = _nextDay(day)) {
      final done = completedDays.contains(day);
      if (done || cur == 0) continue;
      if (held > 0) {
        held--;
        frozen.add(day);
      } else {
        lost = cur;
        cur = 0;
      }
    }
    return _copy(
      current: cur,
      extendedToday: completedDays.contains(target),
      freezes: held,
      lostStreak: cur < lost ? lost : 0,
      today: target,
      frozenDays: frozen,
    );
  }

  /// A quest completed at [now] (shown right away, even offline).
  StreakInfo withCompletion(DateTime now) {
    final rolled = asOf(now);
    if (rolled.extendedToday) return rolled;
    final cur = rolled.current + 1;
    var held = rolled.freezes;
    if (cur % freezeEvery == 0 && held < maxFreezes) held++;
    return rolled._copy(
      current: cur,
      best: cur > best ? cur : best,
      extendedToday: true,
      freezes: held,
      nextMilestone: _nextMilestoneAfter(cur),
      lostStreak: cur > rolled.lostStreak ? 0 : rolled.lostStreak,
      completedDays: {...rolled.completedDays, rolled.today},
    );
  }

  int? _nextMilestoneAfter(int value) {
    for (final m in milestones) {
      if (m > value) return m;
    }
    return null;
  }

  static DateTime _nextDay(DateTime d) => DateTime(d.year, d.month, d.day + 1);

  StreakInfo _copy({
    int? current,
    int? best,
    bool? extendedToday,
    int? freezes,
    int? nextMilestone,
    int? lostStreak,
    DateTime? today,
    Set<DateTime>? completedDays,
    Set<DateTime>? frozenDays,
  }) =>
      StreakInfo(
        current: current ?? this.current,
        best: best ?? this.best,
        extendedToday: extendedToday ?? this.extendedToday,
        freezes: freezes ?? this.freezes,
        maxFreezes: maxFreezes,
        freezeCost: freezeCost,
        freezeEvery: freezeEvery,
        spendablePoints: spendablePoints,
        nextMilestone: nextMilestone ?? this.nextMilestone,
        milestones: milestones,
        lostStreak: lostStreak ?? this.lostStreak,
        today: today ?? this.today,
        completedDays: completedDays ?? this.completedDays,
        frozenDays: frozenDays ?? this.frozenDays,
      );

  static DateTime _parseDay(Object? value) {
    final d = DateTime.parse(value as String);
    return DateTime(d.year, d.month, d.day);
  }

  static String _day(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  factory StreakInfo.fromJson(Map<String, dynamic> json) => StreakInfo(
        current: (json['current'] as num).toInt(),
        best: (json['best'] as num).toInt(),
        extendedToday: json['extended_today'] as bool,
        freezes: (json['freezes'] as num).toInt(),
        maxFreezes: (json['max_freezes'] as num?)?.toInt() ?? 2,
        freezeCost: (json['freeze_cost'] as num?)?.toInt() ?? 100,
        freezeEvery: (json['freeze_every'] as num?)?.toInt() ?? 7,
        spendablePoints: (json['spendable_points'] as num?)?.toInt() ?? 0,
        nextMilestone: (json['next_milestone'] as num?)?.toInt(),
        milestones: [for (final m in (json['milestones'] as List<dynamic>? ?? defaultMilestones)) (m as num).toInt()],
        lostStreak: (json['lost_streak'] as num?)?.toInt() ?? 0,
        today: _parseDay(json['today']),
        completedDays: {for (final d in json['completed_days'] as List<dynamic>? ?? const []) _parseDay(d)},
        frozenDays: {for (final d in json['frozen_days'] as List<dynamic>? ?? const []) _parseDay(d)},
      );

  Map<String, dynamic> toJson() => {
        'current': current,
        'best': best,
        'extended_today': extendedToday,
        'at_risk': atRisk,
        'freezes': freezes,
        'max_freezes': maxFreezes,
        'freeze_cost': freezeCost,
        'freeze_every': freezeEvery,
        'spendable_points': spendablePoints,
        'can_buy_freeze': canBuyFreeze,
        'next_milestone': nextMilestone,
        'milestones': milestones,
        'lost_streak': lostStreak,
        'today': _day(today),
        'completed_days': [for (final d in completedDays) _day(d)],
        'frozen_days': [for (final d in frozenDays) _day(d)],
      };
}
