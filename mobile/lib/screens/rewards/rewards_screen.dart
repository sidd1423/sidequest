import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/app_scope.dart';
import '../../models/rewards.dart';
import '../../theme.dart';

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
                  const Center(child: Icon(Icons.workspace_premium_outlined, size: 48)),
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
                  const SizedBox(height: 10),
                  GridView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: rewards.badges.length,
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 3,
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 0.78,
                    ),
                    itemBuilder: (context, i) => _BadgeTile(badge: rewards.badges[i]),
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
            if (rewards.spendablePoints != rewards.points)
              Text('${rewards.spendablePoints} left to spend on streak freezes', key: const Key('spendable_points'),
                  style: text.bodySmall?.copyWith(color: colors.onPrimaryContainer)),
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
    Widget stat(IconData icon, String value, String label, String key, [VoidCallback? onTap]) => Expanded(
          child: SizedBox(
            height: 124,
            child: Card(
              key: Key(key),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: onTap,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(icon),
                      const SizedBox(height: 6),
                      Text(value, style: Theme.of(context).textTheme.titleLarge),
                      const SizedBox(height: 2),
                      Text(
                        label,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        stat(Icons.local_fire_department_outlined, '${AppScope.of(context).streak.current}', 'day streak',
            'stat_streak', () => Navigator.of(context).pushNamed(AppRoutes.streak)),
        const SizedBox(width: 10),
        stat(Icons.check_circle_outline, '${rewards.completed}', 'completed', 'stat_completed'),
        const SizedBox(width: 10),
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
      child: Card(
        key: Key('badge_${badge.id}'),
        color: earned ? colors.secondaryContainer : colors.surface,
        elevation: 0,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 10, 8, 8),
          child: Column(
            children: [
              Icon(
                earned ? Icons.military_tech : Icons.lock_outline,
                size: 32,
                color: earned ? SidequestColors.ink : colors.outline,
              ),
              const SizedBox(height: 6),
              Expanded(
                child: Center(
                  child: Text(
                    badge.name,
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                ),
              ),
              Text(
                earned ? 'Earned' : '${badge.progress}/${badge.goal}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: earned ? SidequestColors.copper : colors.onSurfaceVariant,
                    ),
              ),
            ],
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
      leading: CircleAvatar(
        backgroundColor: SidequestColors.gold,
        foregroundColor: SidequestColors.ink,
        child: Text('+${entry.points}'),
      ),
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
        ListTile(dense: true, title: Text('Spend 100 points on a streak freeze (your level never goes down)')),
      ],
    );
  }
}
