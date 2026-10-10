import 'package:flutter/material.dart';

import '../../models/sample_quest.dart';
import '../../widgets/coming_soon.dart';
import 'quest_history_screen.dart';

export '../../models/sample_quest.dart' show SampleQuest;

/// One past quest: details plus (later) feedback for quests you haven't rated.
/// Pushed on the root navigator, so it has a back button instead of the bottom bar.
class QuestDetailScreen extends StatelessWidget {
  const QuestDetailScreen({super.key, required this.quest});

  final SampleQuest quest;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Quest')),
      body: ListView(
        key: const Key('quest_detail_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          Text(quest.title, style: theme.textTheme.headlineSmall),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              Chip(avatar: const Icon(Icons.timer_outlined, size: 18), label: Text('${quest.minutes} min')),
              Chip(label: Text(statusLabel(quest.status))),
              if (quest.rating != null) Chip(label: Text('★' * quest.rating!)),
            ],
          ),
          const SizedBox(height: 16),
          Text(quest.summary, style: theme.textTheme.bodyLarge),
          if (quest.steps.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('Steps', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            for (var i = 0; i < quest.steps.length; i++)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: CircleAvatar(radius: 14, child: Text('${i + 1}')),
                title: Text(quest.steps[i]),
              ),
          ],
          const SizedBox(height: 24),
          if (quest.status == QuestStatus.suggested)
            OutlinedButton.icon(
              key: const Key('rate_quest_button'),
              onPressed: () => showComingSoon(context, 'Rating quests'),
              icon: const Icon(Icons.rate_review_outlined),
              label: const Text('How did it go?'),
            ),
        ],
      ),
    );
  }
}
