import 'package:flutter/material.dart';

import '../../models/generated_quest.dart';

/// "How did it go?" - the rating at the end of a quest.
///
/// Whether it was finished comes from the button tapped (Finish quest / Give
/// up) and the time from the quest timer, so only the stars (required if
/// finished, optional if given up) and an optional comment are asked.
class QuestFeedbackForm extends StatefulWidget {
  const QuestFeedbackForm({super.key, required this.completed, required this.minutes, required this.onSubmit});

  final bool completed;
  final int minutes;
  final ValueChanged<QuestFeedback> onSubmit;

  @override
  State<QuestFeedbackForm> createState() => _QuestFeedbackFormState();
}

class _QuestFeedbackFormState extends State<QuestFeedbackForm> {
  int? _rating;
  final _commentController = TextEditingController();

  @override
  void dispose() {
    _commentController.dispose();
    super.dispose();
  }

  bool get _canSubmit => !widget.completed || _rating != null;

  void _submit() {
    widget.onSubmit(QuestFeedback(
      completed: widget.completed,
      rating: _rating,
      comment: _commentController.text.trim(),
      timeLoggedMinutes: widget.minutes.clamp(0, 1440),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      key: const Key('feedback_form'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('How did it go?', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(widget.completed ? 'Rating' : 'Rating (optional)', style: theme.textTheme.labelLarge),
            Wrap(
              children: [
                for (var star = 1; star <= 5; star++)
                  IconButton(
                    key: Key('star_$star'),
                    tooltip: '$star star${star == 1 ? '' : 's'}',
                    icon: Icon(
                      (_rating ?? 0) >= star ? Icons.star : Icons.star_border,
                      color: theme.colorScheme.primary,
                    ),
                    // Tapping the current rating again clears it.
                    onPressed: () => setState(() => _rating = _rating == star ? null : star),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('feedback_comment'),
              controller: _commentController,
              maxLines: 2,
              decoration: InputDecoration(
                labelText: 'Comment (optional)',
                hintText: widget.completed ? 'What did you like or dislike?' : "Why didn't it work out?",
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('submit_feedback_button'),
              onPressed: _canSubmit ? _submit : null,
              child: const Text('Send feedback'),
            ),
            if (!_canSubmit)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'Rate a quest you completed',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
