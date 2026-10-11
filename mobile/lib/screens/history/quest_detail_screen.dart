import 'package:flutter/material.dart';

import '../../data/app_scope.dart';
import '../../models/generated_quest.dart';
import '../../models/quest_record.dart';
import '../../widgets/quest_journal.dart';
import '../quest/quest_card.dart';
import '../quest/quest_feedback_form.dart';
import '../streak/streak_celebration_screen.dart';
import 'quest_history_screen.dart';

/// One past quest: the full quest card, its quest log (notes + photos), how
/// it went, and a rating form if you haven't rated it yet (all work offline -
/// they sync later).
/// Pushed on the root navigator, so it has a back button instead of the bottom bar.
class QuestDetailScreen extends StatelessWidget {
  const QuestDetailScreen({super.key, required this.questId});

  final int questId;

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
                QuestCard(quest: record.quest, party: record.party),
                const SizedBox(height: 16),
                QuestJournal(questId: record.id),
                const SizedBox(height: 16),
                if (record.feedback == null)
                  QuestFeedbackForm(
                    estimatedMinutes: record.quest.minutes,
                    onSubmit: (QuestFeedback f) async {
                      final wasExtended = state.streak.extendedToday;
                      await state.sendFeedback(record.id, f);
                      if (context.mounted && f.completed) {
                        await StreakCelebrationScreen.showIfExtended(context, wasExtended: wasExtended);
                      }
                    },
                  )
                else
                  _HowItWent(record: record),
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
