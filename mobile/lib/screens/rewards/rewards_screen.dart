import 'package:flutter/material.dart';

import '../../data/app_scope.dart';
import '../../models/rewards.dart';

/// Rewards tab: points, level, streak, badges and what earned the points.
/// Loaded from the server when the tab opens (and on pull-to-refresh); the
/// last copy is kept on the device for offline use.
class RewardsScreen extends StatefulWidget {
  const RewardsScreen({super.key});

  @override
  State<RewardsScreen> createState() => _RewardsScreenState();
}

class _RewardsScreenState extends State<RewardsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) AppScope.read(context).loadRewards();
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final rewards = state.rewards;
    return Scaffold(
      appBar: AppBar(title: const Text('Rewards')),
      body: RefreshIndicator(
        onRefresh: state.loadRewards,
        child: ListView(
          key: const Key('rewards_screen'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: rewards == null
              ? [
                  const SizedBox(height: 120),
                  const Center(child: Icon(Icons.emoji_events_outlined, size: 48)),
                  const SizedBox(height: 12),
                  Center(
                    child: Text(
                      state.isOnline ? 'Loading your points...' : 'Connect to see your points.',
                      key: const Key('rewards_empty'),
                    ),
                  ),
                ]
              : [
                  _LevelCard(rewards: rewards),
                  const SizedBox(height: 12),
                  _StatsRow(rewards: rewards),
                  const SizedBox(height: 24),
                  Text('Badges (${rewards.earnedBadges}/${rewards.badges.length})',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [for (final b in rewards.badges) _BadgeTile(badge: b)],
                  ),
                  const SizedBox(height: 24),
                  Text('Recent points', style: Theme.of(context).textTheme.titleMedium),
                  if (rewards.recent.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text('Complete a quest to earn your first points.'),
                    ),
                  for (final e in rewards.recent) _PointsTile(entry: e),
                  const SizedBox(height: 24),
                  const _HowPointsWork(),
                ],
        ),
      ),
    );
  }
}

class _LevelCard extends StatelessWidget {
  const _LevelCard({required this.rewards});

  final Rewards rewards;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final next = rewards.nextLevelAt;
    return Card(
      key: const Key('level_card'),
      color: colors.primaryContainer,
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${rewards.points}', key: const Key('points_total'),
                style: text.displaySmall?.copyWith(color: colors.onPrimaryContainer, fontWeight: FontWeight.bold)),
            Text('points', style: text.titleMedium?.copyWith(color: colors.onPrimaryContainer)),
            const SizedBox(height: 16),
            Text('Level ${rewards.level} · ${rewards.levelName}', key: const Key('level_name'),
                style: text.titleLarge?.copyWith(color: colors.onPrimaryContainer)),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                key: const Key('level_progress'),
                value: rewards.levelProgress,
                minHeight: 10,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              next == null
                  ? 'Top level reached!'
                  : '${next - rewards.points} points to ${rewards.nextLevelName}',
              style: text.bodyMedium?.copyWith(color: colors.onPrimaryContainer),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  const _StatsRow({required this.rewards});

  final Rewards rewards;

  @override
  Widget build(BuildContext context) {
    Widget stat(IconData icon, String value, String label, String key) => Expanded(
          child: Card(
            key: Key(key),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
              child: Column(
                children: [
                  Icon(icon),
                  const SizedBox(height: 4),
                  Text(value, style: Theme.of(context).textTheme.titleLarge),
                  Text(label, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ),
        );
    return Row(
      children: [
        stat(Icons.local_fire_department_outlined, '${rewards.currentStreak}', 'day streak', 'stat_streak'),
        stat(Icons.check_circle_outline, '${rewards.completed}', 'completed', 'stat_completed'),
        stat(Icons.timer_outlined, '${rewards.minutesOutside}', 'min outside', 'stat_minutes'),
      ],
    );
  }
}

class _BadgeTile extends StatelessWidget {
  const _BadgeTile({required this.badge});

  final RewardBadge badge;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final earned = badge.earned;
    return Tooltip(
      message: badge.description,
      child: SizedBox(
        key: Key('badge_${badge.id}'),
        width: 104,
        child: Card(
          color: earned ? colors.secondaryContainer : colors.surfaceContainerHighest,
          elevation: 0,
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Column(
              children: [
                Icon(earned ? Icons.military_tech : Icons.lock_outline,
                    size: 32, color: earned ? colors.onSecondaryContainer : colors.outline),
                const SizedBox(height: 4),
                Text(badge.name, textAlign: TextAlign.center, maxLines: 2,
                    style: Theme.of(context).textTheme.labelLarge),
                if (!earned)
                  Text('${badge.progress}/${badge.goal}', style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _PointsTile extends StatelessWidget {
  const _PointsTile({required this.entry});

  final PointsEntry entry;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      key: Key('points_entry_${entry.questId}'),
      contentPadding: EdgeInsets.zero,
      leading: CircleAvatar(child: Text('+${entry.points}')),
      title: Text(entry.title),
      subtitle: Text(entry.reasons.join(' · ')),
    );
  }
}

class _HowPointsWork extends StatelessWidget {
  const _HowPointsWork();

  @override
  Widget build(BuildContext context) {
    return const ExpansionTile(
      key: Key('how_points_work'),
      tilePadding: EdgeInsets.zero,
      title: Text('How points work'),
      children: [
        ListTile(dense: true, title: Text('Complete a quest: 10 easy · 20 moderate · 35 challenging · 50 extreme')),
        ListTile(dense: true, title: Text('+1 per minute outside (up to 30)')),
        ListTile(dense: true, title: Text('+5 for a photo, +2 for a note in the quest log')),
        ListTile(dense: true, title: Text("+5 for giving a quest a go, even if you didn't finish")),
        ListTile(dense: true, title: Text('+10 for every day in a row you complete a quest')),
      ],
    );
  }
}
