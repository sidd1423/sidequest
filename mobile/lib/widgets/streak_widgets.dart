import 'package:flutter/material.dart';

import '../app_routes.dart';
import '../data/app_scope.dart';
import '../models/streak.dart';

/// Streak orange (the flame), and the "frozen day" blue.
const streakOrange = Color(0xFFCC6F00);
const freezeBlue = Color(0xFF3D6B8A);

/// A flame that's lit once today's quest is done, grey until then.
class StreakFlame extends StatelessWidget {
  const StreakFlame({super.key, required this.lit, this.size = 32});

  final bool lit;
  final double size;

  @override
  Widget build(BuildContext context) => Icon(
        lit ? Icons.local_fire_department : Icons.local_fire_department_outlined,
        size: size,
        color: lit ? streakOrange : Theme.of(context).colorScheme.outline,
      );
}

/// What to tell the user about today, Duolingo-style.
String streakMessage(StreakInfo s, DateTime now) {
  if (s.extendedToday) {
    final next = s.nextMilestone;
    return next == null
        ? "Today's done - see you tomorrow!"
        : "Today's done! ${next - s.current} more ${next - s.current == 1 ? 'day' : 'days'} to $next.";
  }
  if (s.current > 0) {
    final hoursLeft = 24 - now.hour;
    return now.hour >= 18
        ? 'Only $hoursLeft ${hoursLeft == 1 ? 'hour' : 'hours'} left! Complete a quest to keep your streak.'
        : 'Complete a quest today to keep your streak going.';
  }
  if (s.lostStreak > 0) return 'You lost your ${s.lostStreak}-day streak. Start a new one today!';
  return 'Complete a quest today to start a streak.';
}

/// The streak card at the top of the Quest tab. Tap for the full streak page.
class StreakStatusCard extends StatelessWidget {
  const StreakStatusCard({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final s = state.streak;
    final now = state.clock();
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final urgent = s.atRisk && now.hour >= 18;
    final background = urgent
        ? colors.errorContainer
        : s.atRisk
            ? colors.tertiaryContainer
            : colors.surfaceContainerHigh;
    final foreground = urgent
        ? colors.onErrorContainer
        : s.atRisk
            ? colors.onTertiaryContainer
            : colors.onSurface;
    return Card(
      key: const Key('streak_card'),
      color: background,
      elevation: 0,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).pushNamed(AppRoutes.streak),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(
            children: [
              StreakFlame(lit: s.extendedToday, size: 40),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      s.current == 1 ? '1 day streak' : '${s.current} day streak',
                      key: const Key('streak_count'),
                      style: text.titleLarge?.copyWith(color: foreground, fontWeight: FontWeight.bold),
                    ),
                    Text(
                      streakMessage(s, now),
                      key: Key(s.atRisk ? 'streak_at_risk' : 'streak_message'),
                      style: text.bodyMedium?.copyWith(color: foreground),
                    ),
                  ],
                ),
              ),
              if (s.freezes > 0) ...[
                const SizedBox(width: 8),
                Tooltip(
                  message: '${s.freezes} streak ${s.freezes == 1 ? 'freeze' : 'freezes'}',
                  child: Row(
                    key: const Key('streak_card_freezes'),
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.ac_unit, color: freezeBlue, size: 20),
                      Text('${s.freezes}', style: text.labelLarge?.copyWith(color: foreground)),
                    ],
                  ),
                ),
              ],
              Icon(Icons.chevron_right, color: foreground),
            ],
          ),
        ),
      ),
    );
  }
}

/// The last 7 days (ending today) as circles: done, frozen, missed, today.
class WeekStrip extends StatelessWidget {
  const WeekStrip({super.key, required this.streak});

  final StreakInfo streak;

  static const _letters = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final today = streak.today;
    final days = [for (var i = 6; i >= 0; i--) DateTime(today.year, today.month, today.day - i)];
    return Row(
      key: const Key('week_strip'),
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: [
        for (final d in days)
          Column(
            children: [
              Text(_letters[d.weekday - 1], style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 4),
              _DayDot(
                done: streak.completedDays.contains(d),
                frozen: streak.frozenDays.contains(d),
                isToday: d == today,
                outline: colors.outlineVariant,
              ),
            ],
          ),
      ],
    );
  }
}

class _DayDot extends StatelessWidget {
  const _DayDot({required this.done, required this.frozen, required this.isToday, required this.outline});

  final bool done;
  final bool frozen;
  final bool isToday;
  final Color outline;

  @override
  Widget build(BuildContext context) {
    final color = done ? streakOrange : (frozen ? freezeBlue : null);
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color,
        border: color == null ? Border.all(color: isToday ? streakOrange : outline, width: 2) : null,
      ),
      child: done
          ? const Icon(Icons.check, size: 18, color: Colors.white)
          : frozen
              ? const Icon(Icons.ac_unit, size: 16, color: Colors.white)
              : null,
    );
  }
}
