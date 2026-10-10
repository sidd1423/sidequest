import 'package:flutter/material.dart';

import '../../widgets/coming_soon.dart';

/// Quest generator tab (home). Layout only: pick how many minutes you have,
/// tap Generate, and the quest card + "How did it go?" feedback appear here.
class QuestGeneratorScreen extends StatelessWidget {
  const QuestGeneratorScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Sidequest')),
      body: ListView(
        key: const Key('quest_generator_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          const ComingSoonBanner(),
          const SizedBox(height: 16),
          Text('Got a few minutes?', style: theme.textTheme.headlineSmall),
          const SizedBox(height: 4),
          Text(
            'Get a quick 5-30 minute quest to do outside, right now.',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 24),

          // --- Time available ------------------------------------------
          Text('How many minutes do you have?', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              for (final minutes in const [5, 10, 15, 20, 30])
                ChoiceChip(
                  label: Text('$minutes min'),
                  selected: minutes == 15,
                  onSelected: (_) => showComingSoon(context, 'Choosing your time'),
                ),
            ],
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const Key('generate_button'),
            onPressed: () => showComingSoon(context, 'Quest generation'),
            icon: const Icon(Icons.auto_awesome),
            label: const Text('Generate sidequest'),
          ),
          const SizedBox(height: 24),

          // --- Quest card placeholder ----------------------------------
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Your quest will appear here', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 8),
                  const Text('Title, summary, steps, time, difficulty, energy, accessibility notes '
                      'and a weather plan B.'),
                  const SizedBox(height: 16),
                  const Divider(),
                  const SizedBox(height: 8),
                  Text('How did it go?', style: theme.textTheme.titleMedium),
                  const SizedBox(height: 4),
                  const Text('Completed / didn\'t finish, star rating, time spent and a comment.'),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
