import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../models/sample_quest.dart';
import '../../widgets/coming_soon.dart';
import '../home_shell.dart';

/// History tab: the user's previous quests. Shows sample data for now;
/// tapping one opens its detail screen.
class QuestHistoryScreen extends StatelessWidget {
  const QuestHistoryScreen({super.key, this.quests = sampleQuests});

  final List<SampleQuest> quests;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Your quests')),
      body: quests.isEmpty
          ? _EmptyHistory(onGetQuest: () => HomeShell.of(context)?.selectTab(HomeTab.quest))
          : ListView(
              key: const Key('quest_history_screen'),
              padding: const EdgeInsets.all(16),
              children: [
                const ComingSoonBanner(message: 'Sample quests - real history comes from the backend'),
                const SizedBox(height: 8),
                for (final quest in quests)
                  Card(
                    child: ListTile(
                      key: Key('history_quest_${quest.id}'),
                      leading: _StatusIcon(quest.status),
                      title: Text(quest.title),
                      subtitle: Text(_subtitle(quest)),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.of(context).pushNamed(AppRoutes.questDetail, arguments: quest),
                    ),
                  ),
              ],
            ),
    );
  }

  static String _subtitle(SampleQuest q) {
    final parts = <String>['${q.minutes} min', statusLabel(q.status)];
    if (q.rating != null) parts.add('★' * q.rating!);
    return parts.join(' · ');
  }
}

String statusLabel(QuestStatus status) => switch (status) {
      QuestStatus.suggested => 'Not done yet',
      QuestStatus.completed => 'Completed',
      QuestStatus.skipped => "Didn't finish",
    };

class _StatusIcon extends StatelessWidget {
  const _StatusIcon(this.status);

  final QuestStatus status;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return switch (status) {
      QuestStatus.suggested => Icon(Icons.schedule, color: colors.secondary),
      QuestStatus.completed => Icon(Icons.check_circle, color: colors.primary),
      QuestStatus.skipped => Icon(Icons.remove_circle_outline, color: colors.outline),
    };
  }
}

class _EmptyHistory extends StatelessWidget {
  const _EmptyHistory({required this.onGetQuest});

  final VoidCallback onGetQuest;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.map_outlined, size: 48),
            const SizedBox(height: 12),
            const Text('No quests yet', textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('empty_history_get_quest'),
              onPressed: onGetQuest,
              child: const Text('Get your first quest'),
            ),
          ],
        ),
      ),
    );
  }
}
