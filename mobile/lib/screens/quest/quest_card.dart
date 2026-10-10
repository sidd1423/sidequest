import 'package:flutter/material.dart';

import '../../models/generated_quest.dart';
import '../../models/preference_options.dart';

/// The generated quest: title, summary, quick facts, steps and notes.
class QuestCard extends StatelessWidget {
  const QuestCard({super.key, required this.quest});

  final GeneratedQuest quest;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final difficulty = difficultyOptions.firstWhere(
      (o) => o.value == quest.difficulty,
      orElse: () => difficultyOptions.first,
    );
    return Card(
      key: const Key('quest_card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(quest.title, style: theme.textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(quest.summary),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(avatar: const Icon(Icons.timer_outlined, size: 18), label: Text('${quest.minutes} min')),
                Chip(avatar: const Icon(Icons.terrain, size: 18), label: Text(difficulty.label)),
                Chip(
                  avatar: const Icon(Icons.bolt, size: 18),
                  label: Text('Energy: ${energyLabels[quest.energy] ?? quest.energy}'),
                ),
                if (quest.distanceKm != null)
                  Chip(
                    avatar: const Icon(Icons.place_outlined, size: 18),
                    label: Text('≤ ${quest.distanceKm!.toStringAsFixed(1)} km'),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            Text('Steps', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            for (var i = 0; i < quest.steps.length; i++)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: CircleAvatar(radius: 14, child: Text('${i + 1}')),
                title: Text(quest.steps[i]),
              ),
            if (quest.accessibilityNotes.isNotEmpty) _Note(icon: Icons.accessible, text: quest.accessibilityNotes),
            if (quest.weatherBackup.isNotEmpty) _Note(icon: Icons.umbrella_outlined, text: quest.weatherBackup),
            if (quest.whyItFits.isNotEmpty) _Note(icon: Icons.lightbulb_outline, text: quest.whyItFits),
          ],
        ),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}
