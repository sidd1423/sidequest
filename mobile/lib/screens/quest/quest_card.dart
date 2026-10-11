import 'package:flutter/material.dart';

import '../../models/generated_quest.dart';
import '../../models/location.dart';
import '../../models/party.dart';
import '../../models/preference_options.dart';
import 'party_section.dart' show PartyMembers;

/// The generated quest: title, summary, quick facts, steps and notes.
class QuestCard extends StatelessWidget {
  const QuestCard({super.key, required this.quest, this.party, this.conditions, this.showSteps = true});

  final GeneratedQuest quest;

  /// Set for a group quest: who it's for and who's in.
  final PartyTag? party;

  /// Place + weather when it was generated (null if location was off).
  final QuestConditions? conditions;

  /// false before the quest is started: steps are revealed one at a time.
  final bool showSteps;

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
            if (conditions != null && conditions!.summary.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                conditions!.summary,
                key: const Key('quest_conditions'),
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
            if (party != null) ...[
              const SizedBox(height: 8),
              Row(
                key: const Key('group_quest_banner'),
                children: [
                  Icon(Icons.groups, color: theme.colorScheme.primary),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Group quest for ${party!.size} people · ${party!.joined} in',
                      style: theme.textTheme.titleSmall?.copyWith(color: theme.colorScheme.primary),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              PartyMembers(members: party!.members),
            ],
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
            if (showSteps) ...[
              Text('Steps', style: theme.textTheme.titleSmall),
              const SizedBox(height: 4),
              for (var i = 0; i < quest.steps.length; i++)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: CircleAvatar(radius: 14, child: Text('${i + 1}')),
                  title: Text(quest.steps[i]),
                ),
            ] else
              Row(
                key: const Key('steps_hidden'),
                children: [
                  Icon(Icons.lock_outline, size: 20, color: theme.colorScheme.onSurfaceVariant),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${quest.steps.length} ${quest.steps.length == 1 ? 'step' : 'steps'} - '
                      "you'll see them one at a time once you start.",
                      style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ),
                ],
              ),
            if (quest.accessibilityNotes.isNotEmpty) _Note(icon: Icons.accessible, text: quest.accessibilityNotes),
            if (quest.weatherBackup.isNotEmpty) _Note(icon: Icons.umbrella_outlined, text: quest.weatherBackup),
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
