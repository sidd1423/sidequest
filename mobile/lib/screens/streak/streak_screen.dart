import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../models/streak.dart';
import '../../widgets/streak_widgets.dart';

/// The full streak page (tap the streak card on the Quest tab, or the streak
/// stat on Rewards): big flame, this week, next milestone, streak freezes,
/// and a month-by-month calendar of streak days.
class StreakScreen extends StatefulWidget {
  const StreakScreen({super.key});

  @override
  State<StreakScreen> createState() => _StreakScreenState();
}

class _StreakScreenState extends State<StreakScreen> {
  late DateTime _month;
  bool _buying = false;

  @override
  void initState() {
    super.initState();
    final state = AppScope.read(context);
    final now = state.clock();
    _month = DateTime(now.year, now.month);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) state.loadStreak();
    });
  }

  Future<void> _buyFreeze() async {
    final state = AppScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _buying = true);
    String message;
    try {
      await state.buyStreakFreeze();
      message = 'Streak freeze ready! It will cover a day you miss.';
    } on OfflineException {
      message = 'Buying a streak freeze needs a connection.';
    } on ApiException catch (e) {
      message = e.message;
    } finally {
      if (mounted) setState(() => _buying = false);
    }
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final s = state.streak;
    final now = state.clock();
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Streak')),
      body: RefreshIndicator(
        onRefresh: state.loadStreak,
        child: ListView(
          key: const Key('streak_screen'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Center(child: StreakFlame(lit: s.extendedToday, size: 96)),
            Center(
              child: Text('${s.current}', key: const Key('streak_big_count'),
                  style: text.displayMedium?.copyWith(fontWeight: FontWeight.bold, color: streakOrange)),
            ),
            Center(child: Text('day streak', style: text.titleMedium)),
            const SizedBox(height: 8),
            Center(
              child: Text(streakMessage(s, now), key: const Key('streak_screen_message'),
                  textAlign: TextAlign.center, style: text.bodyLarge),
            ),
            const SizedBox(height: 4),
            Center(child: Text('Best: ${s.best} ${s.best == 1 ? 'day' : 'days'}', key: const Key('streak_best'))),
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('This week', style: text.titleMedium),
                    const SizedBox(height: 12),
                    WeekStrip(streak: s),
                  ],
                ),
              ),
            ),
            if (s.nextMilestone != null) _MilestoneCard(streak: s),
            _FreezeCard(streak: s, buying: _buying, onBuy: _buyFreeze),
            const SizedBox(height: 8),
            _Calendar(
              streak: s,
              month: _month,
              onMonth: (m) => setState(() => _month = m),
            ),
            const SizedBox(height: 8),
            _HowStreaksWork(streak: s),
          ],
        ),
      ),
    );
  }
}

class _MilestoneCard extends StatelessWidget {
  const _MilestoneCard({required this.streak});

  final StreakInfo streak;

  @override
  Widget build(BuildContext context) {
    final next = streak.nextMilestone!;
    final left = next - streak.current;
    return Card(
      key: const Key('milestone_card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.flag_outlined),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('Next milestone: $next days', style: Theme.of(context).textTheme.titleMedium),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                value: streak.milestoneProgress,
                minHeight: 10,
                color: streakOrange,
              ),
            ),
            const SizedBox(height: 6),
            Text('$left ${left == 1 ? 'day' : 'days'} to go'),
          ],
        ),
      ),
    );
  }
}

class _FreezeCard extends StatelessWidget {
  const _FreezeCard({required this.streak, required this.buying, required this.onBuy});

  final StreakInfo streak;
  final bool buying;
  final VoidCallback onBuy;

  @override
  Widget build(BuildContext context) {
    final s = streak;
    final full = s.freezes >= s.maxFreezes;
    return Card(
      key: const Key('freeze_card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text('Streak freezes', style: Theme.of(context).textTheme.titleMedium)),
                for (var i = 0; i < s.maxFreezes; i++)
                  Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: Icon(Icons.ac_unit,
                        color: i < s.freezes ? freezeBlue : Theme.of(context).colorScheme.outlineVariant),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text('${s.freezes} of ${s.maxFreezes}', key: const Key('freeze_count')),
            const SizedBox(height: 8),
            const Text('A freeze is used automatically on a day you miss, so your streak survives.'),
            const SizedBox(height: 4),
            Text(full
                ? "You're holding the most you can."
                : 'Free one in ${s.daysToFreeFreeze} streak ${s.daysToFreeFreeze == 1 ? 'day' : 'days'} '
                    '(every ${s.freezeEvery} days).'),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              key: const Key('buy_freeze_button'),
              onPressed: buying || !s.canBuyFreeze ? null : onBuy,
              icon: buying
                  ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.ac_unit),
              label: Text('Buy for ${s.freezeCost} points (you have ${s.spendablePoints})'),
            ),
          ],
        ),
      ),
    );
  }
}

/// One month: orange = completed a quest, blue = covered by a freeze.
class _Calendar extends StatelessWidget {
  const _Calendar({required this.streak, required this.month, required this.onMonth});

  final StreakInfo streak;
  final DateTime month; // first of the month
  final ValueChanged<DateTime> onMonth;

  static const _names = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final today = streak.today;
    final daysInMonth = DateTime(month.year, month.month + 1, 0).day;
    final leading = DateTime(month.year, month.month).weekday - 1; // Monday first
    final canGoForward = DateTime(month.year, month.month + 1).isBefore(DateTime(today.year, today.month + 1));
    final doneThisMonth = streak.completedDays.where((d) => d.year == month.year && d.month == month.month).length;

    return Card(
      key: const Key('streak_calendar'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            Row(
              children: [
                IconButton(
                  key: const Key('calendar_previous'),
                  tooltip: 'Previous month',
                  icon: const Icon(Icons.chevron_left),
                  onPressed: () => onMonth(DateTime(month.year, month.month - 1)),
                ),
                Expanded(
                  child: Text('${_names[month.month - 1]} ${month.year}',
                      key: const Key('calendar_month'), textAlign: TextAlign.center, style: text.titleMedium),
                ),
                IconButton(
                  key: const Key('calendar_next'),
                  tooltip: 'Next month',
                  icon: const Icon(Icons.chevron_right),
                  onPressed: canGoForward ? () => onMonth(DateTime(month.year, month.month + 1)) : null,
                ),
              ],
            ),
            Text('$doneThisMonth quest ${doneThisMonth == 1 ? 'day' : 'days'} this month', style: text.bodySmall),
            const SizedBox(height: 8),
            Row(
              children: [
                for (final l in const ['M', 'T', 'W', 'T', 'F', 'S', 'S'])
                  Expanded(child: Center(child: Text(l, style: text.labelMedium))),
              ],
            ),
            const SizedBox(height: 4),
            GridView.count(
              crossAxisCount: 7,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                for (var i = 0; i < leading; i++) const SizedBox.shrink(),
                for (var day = 1; day <= daysInMonth; day++)
                  _CalendarDay(
                    date: DateTime(month.year, month.month, day),
                    done: streak.completedDays.contains(DateTime(month.year, month.month, day)),
                    frozen: streak.frozenDays.contains(DateTime(month.year, month.month, day)),
                    isToday: DateTime(month.year, month.month, day) == today,
                    future: DateTime(month.year, month.month, day).isAfter(today),
                    colors: colors,
                  ),
              ],
            ),
            const SizedBox(height: 8),
            const Wrap(
              spacing: 16,
              children: [
                _Legend(color: streakOrange, label: 'Quest done'),
                _Legend(color: freezeBlue, label: 'Freeze used'),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CalendarDay extends StatelessWidget {
  const _CalendarDay({
    required this.date,
    required this.done,
    required this.frozen,
    required this.isToday,
    required this.future,
    required this.colors,
  });

  final DateTime date;
  final bool done;
  final bool frozen;
  final bool isToday;
  final bool future;
  final ColorScheme colors;

  @override
  Widget build(BuildContext context) {
    final fill = done ? streakOrange : (frozen ? freezeBlue : null);
    final key = 'calendar_${date.year}-${date.month}-${date.day}${done ? '_done' : frozen ? '_frozen' : ''}';
    return Padding(
      padding: const EdgeInsets.all(3),
      child: Container(
        key: Key(key),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: fill,
          border: isToday && fill == null ? Border.all(color: streakOrange, width: 2) : null,
        ),
        alignment: Alignment.center,
        child: Text(
          '${date.day}',
          style: TextStyle(
            color: fill != null ? Colors.white : (future ? colors.outline : colors.onSurface),
            fontWeight: isToday ? FontWeight.bold : FontWeight.normal,
          ),
        ),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 12, height: 12, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      );
}

class _HowStreaksWork extends StatelessWidget {
  const _HowStreaksWork({required this.streak});

  final StreakInfo streak;

  @override
  Widget build(BuildContext context) {
    return ExpansionTile(
      key: const Key('how_streaks_work'),
      tilePadding: EdgeInsets.zero,
      title: const Text('How streaks work'),
      children: [
        const ListTile(dense: true, title: Text('Complete at least one quest a day to grow your streak.')),
        const ListTile(dense: true, title: Text("Skipped quests don't count - you have to finish one.")),
        const ListTile(dense: true, title: Text('Miss a day and it goes back to 0, unless you have a streak freeze.')),
        ListTile(
          dense: true,
          title: Text('You get a free freeze every ${streak.freezeEvery} streak days, or buy one for '
              '${streak.freezeCost} points. You can hold ${streak.maxFreezes}.'),
        ),
        const ListTile(dense: true, title: Text('+10 points for every day in a row.')),
      ],
    );
  }
}
