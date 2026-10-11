import 'package:flutter/material.dart';

import '../../models/generated_quest.dart';

/// "How did it go?" - rating form shown under the quest card.
///
/// Completed it / Didn't finish, 1-5 stars (required if completed, optional
/// if not), time spent (defaults to the estimate, or 0 if not finished) and
/// an optional comment. Mirrors the backend's feedback fields.
///
/// After a timed quest ([timeSpentMinutes] from the timer) the time starts
/// at what was measured and doesn't change with the outcome.
class QuestFeedbackForm extends StatefulWidget {
  const QuestFeedbackForm({
    super.key,
    required this.estimatedMinutes,
    required this.onSubmit,
    this.initialCompleted = true,
    this.timeSpentMinutes,
  });

  final int estimatedMinutes;
  final ValueChanged<QuestFeedback> onSubmit;
  final bool initialCompleted;
  final int? timeSpentMinutes;

  @override
  State<QuestFeedbackForm> createState() => _QuestFeedbackFormState();
}

class _QuestFeedbackFormState extends State<QuestFeedbackForm> {
  late bool _completed = widget.initialCompleted;
  int? _rating;
  late final _timeController = TextEditingController(
      text: '${widget.timeSpentMinutes ?? (widget.initialCompleted ? widget.estimatedMinutes : 0)}');
  final _commentController = TextEditingController();

  @override
  void dispose() {
    _timeController.dispose();
    _commentController.dispose();
    super.dispose();
  }

  void _setCompleted(bool completed) {
    setState(() {
      _completed = completed;
      // Time defaults to the estimate when done, 0 when not finished (unless it was timed).
      if (widget.timeSpentMinutes == null) _timeController.text = completed ? '${widget.estimatedMinutes}' : '0';
    });
  }

  bool get _canSubmit => !_completed || _rating != null;

  void _submit() {
    final minutes = int.tryParse(_timeController.text.trim()) ?? 0;
    widget.onSubmit(QuestFeedback(
      completed: _completed,
      rating: _rating,
      comment: _commentController.text.trim(),
      timeLoggedMinutes: minutes.clamp(0, 1440),
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
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ChoiceChip(
                  key: const Key('outcome_completed'),
                  label: const Text('Completed it'),
                  selected: _completed,
                  onSelected: (_) => _setCompleted(true),
                ),
                ChoiceChip(
                  key: const Key('outcome_not_finished'),
                  label: const Text("Didn't finish"),
                  selected: !_completed,
                  onSelected: (_) => _setCompleted(false),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(_completed ? 'Rating' : 'Rating (optional)', style: theme.textTheme.labelLarge),
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
              key: const Key('time_spent_field'),
              controller: _timeController,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: _completed ? 'Time spent (minutes)' : 'Time spent before stopping (minutes)',
                helperText: widget.timeSpentMinutes == null ? null : 'From your quest timer',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('feedback_comment'),
              controller: _commentController,
              maxLines: 2,
              decoration: InputDecoration(
                labelText: 'Comment (optional)',
                hintText: _completed ? 'What did you like or dislike?' : "Why didn't it work out?",
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
