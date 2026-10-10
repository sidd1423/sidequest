import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../models/generated_quest.dart';
import '../../models/preference_options.dart';
import '../../models/quest_record.dart';
import '../auth/auth_scaffold.dart' show AuthError;
import 'quest_card.dart';
import 'quest_feedback_form.dart';

/// Quest tab (home).
///
/// 1. Pick this quest's settings: minutes, who's with you, difficulty,
///    energy, distance.
/// 2. Tap Generate - only then does the quest card appear.
/// 3. Rate it under the card ("How did it go?").
///
/// Interests, accessibility, surroundings and weather come from the profile
/// (set at sign-up / Edit account). Generating needs a connection (Gemma runs
/// on the server); rating works offline and syncs later.
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
  String _group = 'solo';

  QuestRecord? _record;
  QuestFeedback? _feedback;
  bool _generating = false;
  String? _error;
  final _cardKey = GlobalKey();

  Future<void> _generate() async {
    setState(() {
      _generating = true;
      _error = null;
    });
    try {
      final record = await AppScope.read(context).generateQuest(QuestSettings(
        minutes: _minutes,
        difficulty: _difficulty,
        energy: _energy.round(),
        distanceKm: _distanceKm,
        group: _group,
      ));
      if (!mounted) return;
      setState(() {
        _record = record;
        _feedback = null;
      });
    } on OfflineException catch (e) {
      if (mounted) setState(() => _error = '${e.message} New quests need a connection - your history still works offline.');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = "Couldn't get a quest: ${e.message}");
    } finally {
      if (mounted) setState(() => _generating = false);
    }
    if (_record == null || _error != null) return;
    // Bring the new card into view.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final cardContext = _cardKey.currentContext;
      if (cardContext != null && mounted) {
        Scrollable.ensureVisible(cardContext, duration: const Duration(milliseconds: 300));
      }
    });
  }

  Future<void> _submitFeedback(QuestFeedback feedback) async {
    final state = AppScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _feedback = feedback);
    await state.sendFeedback(_record!.id, feedback); // saved on the device; sent now or when online
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(state.isOnline
            ? 'Thanks! Your next quest will take this into account.'
            : "Saved - it'll sync when you're back online."),
      ));
  }

  bool _isPending(int questId) =>
      AppScope.of(context).quests.any((q) => q.id == questId && q.feedbackPending);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final record = _record;
    final quest = record?.quest;
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

          heading("Who's with you?"),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final o in groupOptions)
                ChoiceChip(
                  key: Key('group_${o.value}'),
                  label: Text(o.label),
                  selected: _group == o.value,
                  onSelected: (_) => setState(() => _group = o.value),
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
            onPressed: _generating ? null : _generate,
            icon: _generating
                ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.auto_awesome),
            label: Text(_generating
                ? 'Asking Gemma... (10-60 s)'
                : quest == null
                    ? 'Generate sidequest'
                    : 'Generate another'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            AuthError(_error!, key: const Key('generate_error')),
          ],

          // --- Result: only after Generate ------------------------------
          if (record != null && quest != null) ...[
            const SizedBox(height: 24),
            QuestCard(key: _cardKey, quest: quest),
            const SizedBox(height: 16),
            if (_feedback == null)
              QuestFeedbackForm(
                // New key per quest so the form resets for each one.
                key: ValueKey('feedback_form_${record.id}'),
                estimatedMinutes: quest.minutes,
                onSubmit: _submitFeedback,
              )
            else
              _FeedbackSummary(feedback: _feedback!, pending: _isPending(record.id)),
          ],
        ],
      ),
    );
  }
}

class _FeedbackSummary extends StatelessWidget {
  const _FeedbackSummary({required this.feedback, required this.pending});

  final QuestFeedback feedback;
  final bool pending;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[feedback.completed ? '✅ Completed' : "⏭️ Didn't finish"];
    if (feedback.rating != null) parts.add('★' * feedback.rating!);
    if (feedback.timeLoggedMinutes > 0) parts.add('${feedback.timeLoggedMinutes} min logged');
    return Card(
      key: const Key('feedback_summary'),
      child: ListTile(
        leading: Icon(pending ? Icons.cloud_upload_outlined : Icons.thumb_up_alt_outlined),
        trailing: pending ? const Tooltip(message: 'Waiting to sync', child: Icon(Icons.schedule)) : null,
        title: Text(parts.join(' · ')),
        subtitle: Text(feedback.comment.isEmpty ? 'Thanks for the feedback!' : '"${feedback.comment}"'),
      ),
    );
  }
}
