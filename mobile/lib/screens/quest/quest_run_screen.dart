import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';

import '../../data/app_scope.dart';
import '../../models/generated_quest.dart';
import '../../models/location.dart';
import '../../models/quest_record.dart';
import '../../models/quest_run.dart';
import '../../widgets/quest_journal.dart';
import '../../widgets/quest_run_widgets.dart';
import '../../widgets/route_map.dart';
import '../streak/streak_celebration_screen.dart';
import 'quest_feedback_form.dart';

/// Doing a quest: one step at a time, with a timer and the route on an
/// OpenStreetMap map (recording starts with the quest). Take a photo at any
/// step. "Finish quest" on the last step - or "Give up" any time - stops the
/// clock and shows the album of photos, then the rating (time pre-filled
/// from the timer).
///
/// Pushed on the root navigator (arg: quest id). Leaving it doesn't stop
/// anything: the Quest tab shows "Continue quest" with the clock still going.
class QuestRunScreen extends StatefulWidget {
  const QuestRunScreen({super.key, required this.questId});

  final int questId;

  @override
  State<QuestRunScreen> createState() => _QuestRunScreenState();
}

class _QuestRunScreenState extends State<QuestRunScreen> {
  bool _picking = false;
  QuestRun? _lastRun; // kept while the rating is sent (the run is cleared then)

  int get questId => widget.questId;

  Future<void> _takePhoto(int stepIndex) async {
    final state = AppScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _picking = true);
    try {
      final photo = await QuestJournal.pickPhoto(camera: QuestJournal.cameraAvailable);
      if (photo == null) return;
      if (photo.bytes.length > QuestJournal.maxPhotoBytes) {
        messenger.showSnackBar(const SnackBar(content: Text('That photo is too big (max 5 MB).')));
        return;
      }
      await state.addPhoto(questId, photo.bytes, photo.mime, step: stepIndex + 1);
    } on Object catch (e) {
      messenger.showSnackBar(SnackBar(content: Text("Couldn't add the photo: $e")));
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  Future<void> _giveUp() async {
    final state = AppScope.read(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Give up on this quest?'),
        content: const Text("The timer stops. You can still look at your photos and say how it went."),
        actions: [
          TextButton(
            key: const Key('give_up_cancel'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep going'),
          ),
          TextButton(
            key: const Key('give_up_confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Give up'),
          ),
        ],
      ),
    );
    if (ok == true) await state.endQuest(gaveUp: true);
  }

  Future<void> _submit(QuestFeedback feedback) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final wasExtended = state.streak.extendedToday;
    await state.sendFeedback(questId, feedback); // saved on the device; sent now or when online
    final synced = state.isOnline ? '' : " It'll sync when you're back online.";
    final message = feedback.completed
        ? "Quest complete! That's ${state.completedCount} so far - it's in History now.$synced"
        : 'Thanks! Your next quest will take this into account.$synced';
    // The celebration first, so the snackbar doesn't cover its Continue button.
    if (mounted && feedback.completed) await StreakCelebrationScreen.showIfExtended(context, wasExtended: wasExtended);
    if (mounted) navigator.pop();
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final matches = state.quests.where((q) => q.id == questId);
    final record = matches.isEmpty ? null : matches.first;
    final run = state.runFor(questId) ?? _lastRun;
    _lastRun = run;
    if (record == null || run == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Quest')),
        body: const Center(child: Text("This quest isn't in progress.", key: Key('run_missing'))),
      );
    }
    final steps = record.quest.steps.isEmpty ? const ['Head outside and enjoy it.'] : record.quest.steps;
    return Scaffold(
      appBar: AppBar(
        title: Text(record.quest.title, overflow: TextOverflow.ellipsis),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Chip(
                avatar: Icon(run.ended ? Icons.timer_off_outlined : Icons.timer_outlined, size: 18),
                label: RunClock(run: run, textKey: const Key('run_clock')),
              ),
            ),
          ),
        ],
      ),
      body: run.ended
          ? _EndedView(record: record, run: run, steps: steps, onSubmit: _submit)
          : _StepView(
              record: record,
              run: run,
              steps: steps,
              picking: _picking,
              onPhoto: () => _takePhoto(run.step.clamp(0, steps.length - 1)),
              onGiveUp: _giveUp,
            ),
    );
  }
}

class _StepView extends StatelessWidget {
  const _StepView({
    required this.record,
    required this.run,
    required this.steps,
    required this.picking,
    required this.onPhoto,
    required this.onGiveUp,
  });

  final QuestRecord record;
  final QuestRun run;
  final List<String> steps;
  final bool picking;
  final VoidCallback onPhoto;
  final VoidCallback onGiveUp;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final i = run.step.clamp(0, steps.length - 1);
    final last = i == steps.length - 1;
    final stepPhotos = [for (final p in albumPhotos(state.journal(record.id))) if (p.step == i + 1) p];
    final quest = record.quest;

    return ListView(
      key: const Key('quest_run_screen'),
      padding: const EdgeInsets.all(16),
      children: [
        Text('Step ${i + 1} of ${steps.length}', key: const Key('run_step_label'), style: theme.textTheme.labelLarge),
        const SizedBox(height: 6),
        LinearProgressIndicator(key: const Key('run_progress'), value: (i + 1) / steps.length),
        const SizedBox(height: 16),
        Card(
          color: theme.colorScheme.primaryContainer,
          elevation: 0,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: Text(
                steps[i],
                key: ValueKey('run_step_$i'),
                style: theme.textTheme.titleLarge?.copyWith(color: theme.colorScheme.onPrimaryContainer),
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),

        // --- Photo for this step ------------------------------------------
        if (stepPhotos.isNotEmpty) ...[
          SizedBox(
            height: 88,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: stepPhotos.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, n) => ClipRRect(
                key: Key('run_photo_${stepPhotos[n].clientId}'),
                borderRadius: BorderRadius.circular(8),
                child: SizedBox.square(dimension: 88, child: QuestPhoto(entry: stepPhotos[n])),
              ),
            ),
          ),
          const SizedBox(height: 8),
        ],
        OutlinedButton.icon(
          key: const Key('run_photo_button'),
          onPressed: picking ? null : onPhoto,
          icon: Icon(QuestJournal.cameraAvailable ? Icons.photo_camera_outlined : Icons.add_photo_alternate_outlined),
          label: Text(stepPhotos.isEmpty ? 'Take a photo of this step' : 'Take another photo'),
        ),
        const SizedBox(height: 16),

        // --- Back / Next / Finish ----------------------------------------
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                key: const Key('run_prev'),
                onPressed: i == 0 ? null : () => state.setQuestStep(i - 1),
                icon: const Icon(Icons.arrow_back),
                label: const Text('Back'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 2,
              child: last
                  ? FilledButton.icon(
                      key: const Key('run_finish'),
                      onPressed: () => state.endQuest(gaveUp: false),
                      icon: const Icon(Icons.flag),
                      label: const Text('Finish quest'),
                    )
                  : FilledButton.icon(
                      key: const Key('run_next'),
                      onPressed: () => state.setQuestStep(i + 1),
                      icon: const Icon(Icons.arrow_forward),
                      label: const Text('Next step'),
                    ),
            ),
          ],
        ),
        const SizedBox(height: 20),

        _LiveMap(questId: record.id, conditions: record.conditions),

        if (quest.accessibilityNotes.isNotEmpty || quest.weatherBackup.isNotEmpty) ...[
          const SizedBox(height: 12),
          if (quest.accessibilityNotes.isNotEmpty) _Note(icon: Icons.accessible, text: quest.accessibilityNotes),
          if (quest.weatherBackup.isNotEmpty) _Note(icon: Icons.umbrella_outlined, text: quest.weatherBackup),
        ],
        const SizedBox(height: 16),
        Center(
          child: TextButton.icon(
            key: const Key('run_give_up'),
            style: TextButton.styleFrom(foregroundColor: theme.colorScheme.error),
            onPressed: onGiveUp,
            icon: const Icon(Icons.close),
            label: const Text('Give up'),
          ),
        ),
      ],
    );
  }
}

/// The OpenStreetMap map, following you while the quest runs.
class _LiveMap extends StatelessWidget {
  const _LiveMap({required this.questId, required this.conditions});

  final int questId;
  final QuestConditions? conditions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final points = state.route(questId);
    final tracking = state.isTracking(questId);
    final error = state.trackingError;
    final places = conditions?.nearby ?? const <NearbyPlace>[];
    final here = state.here;
    final lat = here?.lat ?? conditions?.lat;
    final lon = here?.lon ?? conditions?.lon;
    final center = lat != null && lon != null ? LatLng(lat, lon) : null;
    return Card(
      key: const Key('run_map_card'),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(tracking ? Icons.navigation : Icons.map_outlined, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(child: Text('Map', style: theme.textTheme.titleMedium)),
                if (points.isNotEmpty)
                  Text(RouteSummary.measure(points).label, key: const Key('route_summary'),
                      style: theme.textTheme.titleSmall),
              ],
            ),
            const SizedBox(height: 8),
            if (points.isNotEmpty || tracking || center != null)
              RouteMap(points: points, live: tracking, places: places, height: 260, center: center),
            if (tracking && points.isEmpty) ...[
              const SizedBox(height: 8),
              const Text('Finding you on the map...', key: Key('route_waiting')),
            ],
            if (!tracking) ...[
              const SizedBox(height: 8),
              Text(
                error ?? 'Your route isn\'t being recorded.',
                key: const Key('run_map_message'),
                style: TextStyle(color: error == null ? null : theme.colorScheme.error),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  key: const Key('run_map_retry'),
                  onPressed: () => state.startTracking(questId),
                  icon: const Icon(Icons.my_location),
                  label: const Text('Show me on the map'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// After "Finish quest" / "Give up": time, route, the photo album, and the rating.
class _EndedView extends StatelessWidget {
  const _EndedView({required this.record, required this.run, required this.steps, required this.onSubmit});

  final QuestRecord record;
  final QuestRun run;
  final List<String> steps;
  final ValueChanged<QuestFeedback> onSubmit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final points = state.route(record.id);
    final now = state.clock();
    final facts = [
      'Time: ${formatElapsed(run.elapsed(now))}',
      if (run.gaveUp) 'stopped at step ${run.step + 1} of ${steps.length}',
      if (points.isNotEmpty) 'walked ${RouteSummary.measure(points).label}',
    ];
    return ListView(
      key: const Key('quest_run_done'),
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: run.gaveUp ? theme.colorScheme.surfaceContainerHigh : theme.colorScheme.primaryContainer,
          elevation: 0,
          child: ListTile(
            leading: Icon(run.gaveUp ? Icons.directions_walk : Icons.emoji_events, size: 36),
            title: Text(
              run.gaveUp ? 'You gave it a go' : 'Quest complete!',
              key: const Key('run_done_title'),
              style: theme.textTheme.titleLarge,
            ),
            subtitle: Text(facts.join(' · '), key: const Key('run_total_time')),
          ),
        ),
        const SizedBox(height: 16),
        Text('Your album', style: theme.textTheme.titleMedium),
        const SizedBox(height: 8),
        QuestAlbum(questId: record.id, steps: steps),
        if (points.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('Your route', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          RouteMap(points: points, places: record.conditions?.nearby ?? const []),
        ],
        const SizedBox(height: 16),
        QuestFeedbackForm(
          key: ValueKey('run_feedback_${record.id}_${run.gaveUp}'),
          estimatedMinutes: record.quest.minutes,
          initialCompleted: !run.gaveUp,
          timeSpentMinutes: run.minutes(now),
          onSubmit: onSubmit,
        ),
        const SizedBox(height: 8),
        Center(
          child: TextButton.icon(
            key: const Key('run_resume'),
            onPressed: () => state.resumeQuest(),
            icon: const Icon(Icons.undo),
            label: const Text('Oops - keep going'),
          ),
        ),
      ],
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
