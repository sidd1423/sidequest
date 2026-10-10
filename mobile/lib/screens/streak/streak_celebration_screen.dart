import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/app_scope.dart';
import '../../widgets/streak_widgets.dart';

/// Full-screen "N day streak!" shown right after the first completed quest
/// of the day (Duolingo-style). Milestones (3, 7, 14, 30 ... days) get a
/// bigger celebration.
class StreakCelebrationScreen extends StatefulWidget {
  const StreakCelebrationScreen({super.key});

  /// Call with the streak's `extendedToday` from BEFORE the quest was rated:
  /// shows the celebration if that rating just lit today's flame.
  static Future<void> showIfExtended(BuildContext context, {required bool wasExtended}) async {
    final state = AppScope.read(context);
    if (wasExtended || !state.streak.extendedToday) return;
    await Navigator.of(context).pushNamed(AppRoutes.streakCelebration);
  }

  @override
  State<StreakCelebrationScreen> createState() => _StreakCelebrationScreenState();
}

class _StreakCelebrationScreenState extends State<StreakCelebrationScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900))..forward();
  late final Animation<double> _scale = CurvedAnimation(parent: _controller, curve: Curves.elasticOut);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context).streak;
    final text = Theme.of(context).textTheme;
    final milestone = s.isMilestone;
    final next = s.nextMilestone;
    return Scaffold(
      key: const Key('streak_celebration'),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Spacer(),
              ScaleTransition(scale: _scale, child: const StreakFlame(lit: true, size: 140)),
              const SizedBox(height: 8),
              Text('${s.current}', key: const Key('celebration_count'),
                  style: text.displayLarge?.copyWith(color: streakOrange, fontWeight: FontWeight.w900)),
              Text('day streak!', style: text.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              if (milestone)
                Container(
                  key: const Key('celebration_milestone'),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: BoxDecoration(
                    color: streakOrange.withAlpha(38),
                    borderRadius: BorderRadius.circular(24),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.emoji_events, color: streakOrange),
                      const SizedBox(width: 8),
                      Text('Milestone: ${s.current} days!',
                          style: text.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
              const SizedBox(height: 12),
              Text(
                _message(s.current, milestone, next),
                textAlign: TextAlign.center,
                style: text.bodyLarge,
              ),
              const SizedBox(height: 24),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: WeekStrip(streak: s),
                ),
              ),
              if (s.freezes > 0 && s.current % s.freezeEvery == 0) ...[
                const SizedBox(height: 12),
                const Row(
                  key: Key('celebration_free_freeze'),
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.ac_unit, color: freezeBlue),
                    SizedBox(width: 8),
                    Text('You earned a free streak freeze!'),
                  ],
                ),
              ],
              const Spacer(),
              FilledButton(
                key: const Key('streak_continue'),
                style: FilledButton.styleFrom(backgroundColor: streakOrange, foregroundColor: Colors.white),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Continue'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _message(int days, bool milestone, int? next) {
    if (days == 1) return "You started a streak! Complete a quest tomorrow to keep it going.";
    if (milestone) return '$days days in a row outside. That\'s a real habit now!';
    if (next != null) return 'Keep it up - ${next - days} more ${next - days == 1 ? 'day' : 'days'} to $next.';
    return 'Another day outside. Keep it going!';
  }
}
