import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/app_scope.dart';
import '../../models/quest_record.dart';
import '../../models/quest_run.dart';
import '../../widgets/quest_journal.dart';
import '../../widgets/quest_run_widgets.dart';
import '../../widgets/route_tracker.dart';
import '../quest/quest_card.dart';
import 'quest_history_screen.dart';

/// One past quest (finished or given up): the full quest card, your rating,
/// the album, the route and the quest log - all to look at, not to edit
/// (they're added while doing the quest). A given-up quest can be resumed
/// (clock carries on from the time recorded).
/// Pushed on the root navigator, so it has a back button instead of the bottom bar.
class QuestDetailScreen extends StatelessWidget {
  const QuestDetailScreen({super.key, required this.questId});

  final int questId;

  Future<void> _resume(BuildContext context) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    if (!await confirmLeaveCurrentQuest(context, exceptQuestId: questId)) return;
    await state.resumeGivenUp(questId);
    // Done (or given up again) -> back to History, not to this page.
    await navigator.pushReplacementNamed(AppRoutes.questRun, arguments: questId);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final matches = state.quests.where((q) => q.id == questId);
    final record = matches.isEmpty ? null : matches.first;

    return Scaffold(
      appBar: AppBar(title: const Text('Quest')),
      body: record == null
          ? const Center(child: Text('This quest is no longer on this device.'))
          : ListView(
              key: const Key('quest_detail_screen'),
              padding: const EdgeInsets.all(16),
              children: [
                QuestCard(quest: record.quest, party: record.party, conditions: record.conditions),
                const SizedBox(height: 16),
                if (record.feedback != null) ...[
                  _HowItWent(record: record),
                  const SizedBox(height: 16),
                ],
                if (record.status == QuestStatus.skipped && state.runFor(record.id) == null) ...[
                  FilledButton.icon(
                    key: const Key('resume_from_history'),
                    style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                    onPressed: () => _resume(context),
                    icon: const Icon(Icons.play_arrow),
                    label: Text('Resume quest · from ${formatElapsed(state.recordedTime(record.id))}'),
                  ),
                  const SizedBox(height: 16),
                ],
                if (albumPhotos(state.journal(record.id)).isNotEmpty) ...[
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text('Album', style: Theme.of(context).textTheme.titleMedium),
                          const SizedBox(height: 8),
                          QuestAlbum(questId: record.id, steps: record.quest.steps),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                // Routes are recorded while doing the quest; here they're just shown.
                RouteTracker(questId: record.id, places: record.conditions?.nearby ?? const []),
                const SizedBox(height: 16),
                QuestJournal(questId: record.id, readOnly: true),
              ],
            ),
    );
  }
}

class _HowItWent extends StatelessWidget {
  const _HowItWent({required this.record});

  final QuestRecord record;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final f = record.feedback!;
    final parts = <String>[statusLabel(record.status)];
    if (f.timeLoggedMinutes > 0) parts.add('${f.timeLoggedMinutes} min');
    return Card(
      key: const Key('quest_detail_feedback'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text('Your rating', style: theme.textTheme.titleMedium)),
                if (record.feedbackPending)
                  const Tooltip(message: 'Waiting to sync', child: Icon(Icons.cloud_upload_outlined)),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              key: const Key('detail_rating_stars'),
              children: [
                for (var star = 1; star <= 5; star++)
                  Icon((f.rating ?? 0) >= star ? Icons.star : Icons.star_border,
                      color: theme.colorScheme.primary, size: 22),
                if (f.rating == null) ...[
                  const SizedBox(width: 8),
                  Text('Not rated', style: theme.textTheme.bodySmall),
                ],
              ],
            ),
            const SizedBox(height: 6),
            Text(parts.join(' · '), key: const Key('detail_outcome')),
            const SizedBox(height: 4),
            Text(f.comment.isEmpty ? 'No comment' : '"${f.comment}"', key: const Key('detail_comment')),
          ],
        ),
      ),
    );
  }
}


