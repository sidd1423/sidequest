import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/app_scope.dart';
import '../../models/quest_record.dart';
import '../home_shell.dart';

/// History tab: your previous quests, newest first. Read from the on-device
/// cache (works offline); pull down to refresh from the server.
class QuestHistoryScreen extends StatelessWidget {
  const QuestHistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final quests = state.quests;
    return Scaffold(
      appBar: AppBar(title: const Text('Your quests')),
      body: RefreshIndicator(
        onRefresh: state.sync,
        child: quests.isEmpty
            ? _EmptyHistory(onGetQuest: () => HomeShell.of(context)?.selectTab(HomeTab.quest))
            : ListView(
                key: const Key('quest_history_screen'),
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                children: [
                  for (final quest in quests)
                    Card(
                      child: ListTile(
                        key: Key('history_quest_${quest.id}'),
                        leading: _StatusIcon(quest.status),
                        title: Text(quest.title),
                        subtitle: Text(_subtitle(quest)),
                        trailing: quest.feedbackPending
                            ? const Tooltip(message: 'Waiting to sync', child: Icon(Icons.cloud_upload_outlined))
                            : const Icon(Icons.chevron_right),
                        onTap: () => Navigator.of(context).pushNamed(AppRoutes.questDetail, arguments: quest.id),
                      ),
                    ),
                ],
              ),
      ),
    );
  }

  static String _subtitle(QuestRecord q) {
    final parts = <String>['${q.quest.minutes} min', statusLabel(q.status)];
    if (q.rating != null) parts.add('★' * q.rating!);
    if (q.route != null && q.route!.distanceM > 0) parts.add('🗺 ${q.route!.label.split(' · ').first}');
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
    // Scrollable so pull-to-refresh works on an empty list too.
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        key: const Key('quest_history_empty'),
        physics: const AlwaysScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
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
          ),
        ),
      ),
    );
  }
}
