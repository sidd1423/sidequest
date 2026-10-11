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

/// One past quest (finished or given up): the full quest card, how it went,
/// the album, the route and the quest log. A given-up quest can be resumed
/// (clock carries on from the time recorded); a completed quest's log is
/// read-only.
/// Pushed on the root navigator, so it has a back button instead of the bottom bar.
class QuestDetailScreen extends StatelessWidget {
  const QuestDetailScreen({super.key, required this.questId});

  final int questId;

  Future<void> _resume(BuildContext context) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    if (!await confirmQuitCurrentQuest(context, exceptQuestId: questId)) return;
    await state.resumeGivenUp(questId);
    // Done (or given up again) -> back to History, not to this page.
    await navigator.pushReplacementNamed(AppRoutes.questRun, arguments: questId);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final matches = state.quests.where((q) => q.id == questId);
    final record = matches.isEmpty ? null : matches.first;
    final completed = record?.status == QuestStatus.completed;
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
                QuestJournal(questId: record.id, readOnly: completed),
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
    final f = record.feedback!;
    final parts = <String>[statusLabel(record.status)];
    if (f.rating != null) parts.add('★' * f.rating!);
    if (f.timeLoggedMinutes > 0) parts.add('${f.timeLoggedMinutes} min');
    return Card(
      key: const Key('quest_detail_feedback'),
      child: ListTile(
        leading: Icon(record.feedbackPending ? Icons.cloud_upload_outlined : Icons.rate_review_outlined),
        title: Text(parts.join(' · ')),
        subtitle: Text([
          if (f.comment.isNotEmpty) '"${f.comment}"',
          if (record.feedbackPending) 'Waiting to sync',
        ].join('\n').ifEmpty('No comment')),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => isEmpty ? fallback : this;
}
