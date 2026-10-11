import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../monitoring.dart';
import '../../models/generated_quest.dart';
import '../../models/preference_options.dart';
import '../../widgets/quest_run_widgets.dart';
import '../../widgets/streak_widgets.dart';
import '../../widgets/where_you_are_card.dart';
import '../auth/auth_scaffold.dart' show AuthError;
import 'quest_card.dart';
import 'party_section.dart';

/// Quest tab (home).
///
/// 1. Pick this quest's settings: minutes, who's with you, difficulty,
///    energy, distance.
/// 2. Tap Generate - only then does the quest card appear (it stays across
///    app restarts until you finish it).
/// 3. Tap "Start quest" (QuestRunScreen): a timer starts, the steps show one
///    at a time with a photo button each, and your route is drawn on an
///    OpenStreetMap map. Finish (last step) or give up, flick through the
///    photo album, then rate it. A completed quest leaves this screen (it's
///    in History) and the "quests completed" counter at the top goes up.
///
/// Interests and accessibility come from the profile (set at sign-up / Edit
/// account). Where you are, the weather and real places nearby come from
/// your location ("Right now" card); while doing the quest you can record
/// your route on a map. Generating needs a connection (Gemma runs on the
/// server); rating and route tracking work offline and sync later.
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

  bool _generating = false;
  String? _error;
  final _cardKey = GlobalKey();
  final _place = TextEditingController();

  @override
  void dispose() {
    _place.dispose();
    super.dispose();
  }

  /// A typed place counts only while we don't have the device's location.
  String get _typedPlace {
    final state = AppScope.read(context);
    final located = state.here != null && state.locationProblem == null;
    return located ? '' : _place.text.trim();
  }

  QuestSettings _settings() => QuestSettings(
        minutes: _minutes,
        difficulty: _difficulty,
        energy: _energy.round(),
        distanceKm: _distanceKm,
        group: _group,
      );

  Future<void> _generate() async {
    // Not finished the one you have? Ask before leaving it.
    if (!await confirmQuitCurrentQuest(context) || !mounted) return;
    setState(() {
      _generating = true;
      _error = null;
    });
    try {
      await AppScope.read(context).generateQuest(_settings().withWhere(place: _typedPlace));
    } on OfflineException catch (e, st) {
      // Only the app giving up after 360 s (slow Gemma) - not simply being offline.
      if (e.timedOut) {
        Monitoring.report(e, stackTrace: st, message: 'quest_generation_timeout',
            data: {'minutes': _minutes, 'difficulty': _difficulty, 'group': _group});
      }
      if (mounted) setState(() => _error = '${e.message} New quests need a connection - your history still works offline.');
    } on ApiException catch (e, st) {
      Monitoring.report(e, stackTrace: st, message: 'quest_generation_failed',
          data: {'status': e.statusCode, 'minutes': _minutes, 'difficulty': _difficulty, 'group': _group});
      if (mounted) setState(() => _error = "Couldn't get a quest: ${e.message}");
    } finally {
      if (mounted) setState(() => _generating = false);
    }
    if (!mounted || _error != null) return;
    // Bring the new card into view.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final cardContext = _cardKey.currentContext;
      if (cardContext != null && mounted) {
        Scrollable.ensureVisible(cardContext, duration: const Duration(milliseconds: 300));
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final record = state.activeQuest; // gone once completed
    final quest = record?.quest;
    final feedback = record?.feedback;
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
          const StreakStatusCard(),
          const SizedBox(height: 8),
          _CompletedCounter(count: state.completedCount),
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
          WhereYouAreCard(placeController: _place, distanceKm: _distanceKm),
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
          const SizedBox(height: 20),
          PartySection(settings: _settings, place: () => _typedPlace),

          // --- Result: only after Generate ------------------------------
          if (record != null && quest != null) ...[
            const SizedBox(height: 24),
            QuestCard(
              key: _cardKey,
              quest: quest,
              party: record.party,
              conditions: record.conditions,
              showSteps: false, // revealed one at a time once started
            ),
            const SizedBox(height: 12),
            if (feedback != null && state.runFor(record.id) == null) ...[
              _FeedbackSummary(feedback: feedback, pending: record.feedbackPending),
              const SizedBox(height: 12),
            ],
            QuestStartButton(key: ValueKey('start_${record.id}'), record: record),
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
    final parts = <String>[feedback.completed ? '✅ Completed' : '⏸️ Gave up'];
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

/// "N quests completed" at the top of the Quest screen.
class _CompletedCounter extends StatelessWidget {
  const _CompletedCounter({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    return Card(
      key: const Key('completed_counter'),
      color: colors.primaryContainer,
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Icon(Icons.emoji_events, color: colors.onPrimaryContainer, size: 32),
            const SizedBox(width: 12),
            Text('$count', key: const Key('completed_count'),
                style: text.headlineMedium?.copyWith(color: colors.onPrimaryContainer)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                count == 1 ? 'quest completed' : 'quests completed',
                style: text.titleMedium?.copyWith(color: colors.onPrimaryContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
