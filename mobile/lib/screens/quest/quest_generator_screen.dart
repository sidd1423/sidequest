import 'package:flutter/material.dart';

import '../../models/generated_quest.dart';
import '../../models/preference_options.dart';
import '../../widgets/coming_soon.dart';
import 'quest_card.dart';
import 'quest_feedback_form.dart';

/// Quest tab (home).
///
/// 1. Pick this quest's settings: minutes, difficulty, energy, distance.
/// 2. Tap Generate - only then does the quest card appear.
/// 3. Rate it under the card ("How did it go?").
///
/// Interests, accessibility, surroundings and weather come from the profile
/// (set at sign-up / Edit account). Placeholder quest content for now.
class QuestGeneratorScreen extends StatefulWidget {
  const QuestGeneratorScreen({super.key});

  @override
  State<QuestGeneratorScreen> createState() => _QuestGeneratorScreenState();
}

class _QuestGeneratorScreenState extends State<QuestGeneratorScreen> {
  int _minutes = 15;
  String _difficulty = 'easy';
  double _energy = 3;
  double _distanceKm = 1.0;

  GeneratedQuest? _quest;
  QuestFeedback? _feedback;
  int _questCount = 0;
  final _cardKey = GlobalKey();

  void _generate() {
    // TODO: POST /users/{id}/quests with these per-quest settings.
    setState(() {
      _questCount++;
      _feedback = null;
      _quest = GeneratedQuest(
        title: 'Sample Sidequest #$_questCount',
        summary: 'A ${_difficultyLabel.toLowerCase()} $_minutes-minute quest within '
            '${_distanceKm.toStringAsFixed(1)} km. The real quest will come from Gemma.',
        steps: const ['Step outside', 'Follow the quest', 'Head back and rate it below'],
        minutes: _minutes,
        difficulty: _difficulty,
        energy: _energy.round(),
        distanceKm: _distanceKm,
        weatherBackup: 'If the weather turns, find a covered spot nearby and keep going.',
        whyItFits: 'Placeholder - Gemma will explain why this suits you.',
      );
    });
    // Bring the new card into view.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final cardContext = _cardKey.currentContext;
      if (cardContext != null && mounted) {
        Scrollable.ensureVisible(cardContext, duration: const Duration(milliseconds: 300));
      }
    });
  }

  String get _difficultyLabel =>
      difficultyOptions.firstWhere((o) => o.value == _difficulty).label;

  void _submitFeedback(QuestFeedback feedback) {
    // TODO: POST /users/{id}/quests/{questId}/feedback
    setState(() => _feedback = feedback);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('Thanks! Your next quest will take this into account.')));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final quest = _quest;
    Widget heading(String text) => Padding(
          padding: const EdgeInsets.only(top: 20, bottom: 8),
          child: Text(text, style: theme.textTheme.titleMedium),
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Sidequest')),
      body: ListView(
        key: const Key('quest_generator_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          const ComingSoonBanner(message: 'Layout only - quests are placeholders for now'),
          const SizedBox(height: 16),
          Text('Got a few minutes?', style: theme.textTheme.headlineSmall),
          const SizedBox(height: 4),
          Text(
            'Set up this quest, then get something quick to do outside right now.',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),

          // --- Per-quest settings ----------------------------------------
          heading('How many minutes do you have?'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final m in minuteOptions)
                ChoiceChip(
                  key: Key('minutes_$m'),
                  label: Text('$m min'),
                  selected: _minutes == m,
                  onSelected: (_) => setState(() => _minutes = m),
                ),
            ],
          ),

          heading('Difficulty'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final o in difficultyOptions)
                ChoiceChip(
                  key: Key('difficulty_${o.value}'),
                  label: Text(o.label),
                  selected: _difficulty == o.value,
                  onSelected: (_) => setState(() => _difficulty = o.value),
                ),
            ],
          ),

          heading('Energy right now: ${energyLabels[_energy.round()]}'),
          Slider(
            key: const Key('energy_slider'),
            value: _energy,
            min: 1,
            max: 5,
            divisions: 4,
            label: energyLabels[_energy.round()],
            onChanged: (v) => setState(() => _energy = v),
          ),

          heading('How far will you go? ${_distanceKm.toStringAsFixed(1)} km'),
          Slider(
            key: const Key('distance_slider'),
            value: _distanceKm,
            min: 0,
            max: maxDistanceKm,
            divisions: 10,
            label: '${_distanceKm.toStringAsFixed(1)} km',
            onChanged: (v) => setState(() => _distanceKm = v),
          ),

          const SizedBox(height: 16),
          FilledButton.icon(
            key: const Key('generate_button'),
            onPressed: _generate,
            icon: const Icon(Icons.auto_awesome),
            label: Text(quest == null ? 'Generate sidequest' : 'Generate another'),
          ),

          // --- Result: only after Generate ------------------------------
          if (quest != null) ...[
            const SizedBox(height: 24),
            QuestCard(key: _cardKey, quest: quest),
            const SizedBox(height: 16),
            if (_feedback == null)
              QuestFeedbackForm(
                // New key per quest so the form resets for each one.
                key: ValueKey('feedback_form_$_questCount'),
                estimatedMinutes: quest.minutes,
                onSubmit: _submitFeedback,
              )
            else
              _FeedbackSummary(feedback: _feedback!),
          ],
        ],
      ),
    );
  }
}

class _FeedbackSummary extends StatelessWidget {
  const _FeedbackSummary({required this.feedback});

  final QuestFeedback feedback;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[feedback.completed ? '✅ Completed' : "⏭️ Didn't finish"];
    if (feedback.rating != null) parts.add('★' * feedback.rating!);
    if (feedback.timeLoggedMinutes > 0) parts.add('${feedback.timeLoggedMinutes} min logged');
    return Card(
      key: const Key('feedback_summary'),
      child: ListTile(
        leading: const Icon(Icons.thumb_up_alt_outlined),
        title: Text(parts.join(' · ')),
        subtitle: Text(feedback.comment.isEmpty ? 'Thanks for the feedback!' : '"${feedback.comment}"'),
      ),
    );
  }
}
