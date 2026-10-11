import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app_routes.dart';
import '../data/app_scope.dart';
import '../models/journal_entry.dart';
import '../models/quest_record.dart';
import '../models/quest_run.dart';

/// The quest timer: ticks every second while the quest is running, frozen
/// once it's finished or given up.
class RunClock extends StatefulWidget {
  const RunClock({super.key, required this.run, this.textKey, this.style});

  final QuestRun run;
  final Key? textKey;
  final TextStyle? style;

  @override
  State<RunClock> createState() => _RunClockState();
}

class _RunClockState extends State<RunClock> {
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _syncTicker();
  }

  @override
  void didUpdateWidget(RunClock old) {
    super.didUpdateWidget(old);
    _syncTicker();
  }

  void _syncTicker() {
    if (widget.run.ended) {
      _ticker?.cancel();
      _ticker = null;
    } else {
      _ticker ??= Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final now = AppScope.read(context).clock();
    return Text(formatElapsed(widget.run.elapsed(now)), key: widget.textKey, style: widget.style);
  }
}

/// Before leaving the quest you haven't finished (generating a new one, or
/// resuming another): "Quit this quest?". true = go ahead. Nothing to ask
/// (no unfinished quest, or it's [exceptQuestId]) = true.
///
/// A quest you quit isn't shown in History (it stays in the database).
Future<bool> confirmQuitCurrentQuest(BuildContext context, {int? exceptQuestId}) async {
  final state = AppScope.read(context);
  final current = state.activeQuest;
  if (current == null || current.id == exceptQuestId) return true;
  // Already given up (and not resumed): it's safely in History.
  if (current.feedback != null && state.runFor(current.id) == null) return true;
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      key: const Key('quit_quest_dialog'),
      title: const Text('Quit your current quest?'),
      content: Text(
        'You haven\'t finished "${current.title}". If you quit, it won\'t be saved in your history.',
      ),
      actions: [
        TextButton(
          key: const Key('quit_quest_cancel'),
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Keep it'),
        ),
        TextButton(
          key: const Key('quit_quest_confirm'),
          onPressed: () => Navigator.pop(context, true),
          child: const Text('Quit it'),
        ),
      ],
    ),
  );
  return ok == true;
}

/// "Start quest" / "Continue quest" / "Rate your quest" for [record],
/// depending on where its step-by-step run is. Opens the quest screen.
class QuestStartButton extends StatelessWidget {
  const QuestStartButton({super.key, required this.record});

  final QuestRecord record;

  void _open(BuildContext context) =>
      Navigator.of(context).pushNamed(AppRoutes.questRun, arguments: record.id);

  Future<void> _start(BuildContext context) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    await state.startQuest(record.id);
    await navigator.pushNamed(AppRoutes.questRun, arguments: record.id);
  }

  @override
  Widget build(BuildContext context) {
    final run = AppScope.of(context).runFor(record.id);
    final steps = record.quest.steps.length;
    if (run == null) {
      return FilledButton.icon(
        key: const Key('start_quest_button'),
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
        onPressed: () => _start(context),
        icon: const Icon(Icons.flag_outlined),
        label: const Text('Start quest'),
      );
    }
    if (run.ended) {
      return FilledButton.icon(
        key: const Key('rate_quest_button'),
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
        onPressed: () => _open(context),
        icon: const Icon(Icons.photo_album_outlined),
        label: const Text('See your album and rate it'),
      );
    }
    return FilledButton(
      key: const Key('resume_quest_button'),
      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
      onPressed: () => _open(context),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.play_arrow),
          const SizedBox(width: 8),
          Flexible(child: Text('Continue quest · step ${run.step + 1} of $steps · ')),
          RunClock(run: run),
        ],
      ),
    );
  }
}

/// Photos of a quest, sorted by step, newest last.
List<JournalEntry> albumPhotos(List<JournalEntry> journal) {
  final photos = journal.where((e) => e.isPhoto).toList();
  photos.sort((a, b) {
    final byStep = (a.step ?? 1 << 20).compareTo(b.step ?? 1 << 20);
    return byStep != 0 ? byStep : a.createdAt.compareTo(b.createdAt);
  });
  return photos;
}

/// Swipe through a quest's photos, one at a time, each labelled with the
/// step it was taken at. Arrows too, for mouse users.
class QuestAlbum extends StatefulWidget {
  const QuestAlbum({super.key, required this.questId, required this.steps, this.height = 320});

  final int questId;
  final List<String> steps;
  final double height;

  @override
  State<QuestAlbum> createState() => _QuestAlbumState();
}

class _QuestAlbumState extends State<QuestAlbum> {
  final _pages = PageController();
  int _page = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _go(int page) =>
      _pages.animateToPage(page, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);

  String _caption(JournalEntry photo) {
    final step = photo.step;
    final parts = <String>[
      if (step != null && step >= 1 && step <= widget.steps.length) 'Step $step · ${widget.steps[step - 1]}',
      if (photo.text.isNotEmpty) photo.text,
    ];
    return parts.isEmpty ? 'From your quest log' : parts.join('\n');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final photos = albumPhotos(AppScope.of(context).journal(widget.questId));
    if (photos.isEmpty) {
      return Text('No photos this time.', key: const Key('album_empty'), style: theme.textTheme.bodyMedium);
    }
    final page = _page.clamp(0, photos.length - 1);
    return Column(
      key: const Key('quest_album'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: widget.height,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: ColoredBox(
              color: Colors.black,
              child: PageView.builder(
                key: const Key('album_pages'),
                controller: _pages,
                itemCount: photos.length,
                onPageChanged: (p) => setState(() => _page = p),
                itemBuilder: (context, i) => QuestPhoto(
                  key: ValueKey('album_photo_${photos[i].clientId}'),
                  entry: photos[i],
                  fit: BoxFit.contain,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            IconButton(
              key: const Key('album_prev'),
              tooltip: 'Previous photo',
              onPressed: page > 0 ? () => _go(page - 1) : null,
              icon: const Icon(Icons.chevron_left),
            ),
            Expanded(
              child: Column(
                children: [
                  Text('${page + 1} / ${photos.length}', key: const Key('album_position'),
                      style: theme.textTheme.labelLarge),
                  const SizedBox(height: 2),
                  Text(
                    _caption(photos[page]),
                    key: const Key('album_caption'),
                    textAlign: TextAlign.center,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            IconButton(
              key: const Key('album_next'),
              tooltip: 'Next photo',
              onPressed: page < photos.length - 1 ? () => _go(page + 1) : null,
              icon: const Icon(Icons.chevron_right),
            ),
          ],
        ),
      ],
    );
  }
}

/// One journal photo: from the device until it's uploaded, then downloaded
/// (and cached) when needed. Tap for full screen.
class QuestPhoto extends StatefulWidget {
  const QuestPhoto({super.key, required this.entry, this.fit = BoxFit.cover});

  final JournalEntry entry;
  final BoxFit fit;

  @override
  State<QuestPhoto> createState() => _QuestPhotoState();
}

class _QuestPhotoState extends State<QuestPhoto> {
  Future<Uint8List?>? _bytes;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _bytes ??= AppScope.read(context).photoBytes(widget.entry); // load once, not on every rebuild
  }

  @override
  void didUpdateWidget(QuestPhoto old) {
    super.didUpdateWidget(old);
    if (old.entry.clientId != widget.entry.clientId) _bytes = AppScope.read(context).photoBytes(widget.entry);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Uint8List?>(
      future: _bytes,
      builder: (context, snap) {
        final bytes = snap.data;
        if (bytes == null) {
          return ColoredBox(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            child: const Center(child: Icon(Icons.image_outlined)),
          );
        }
        return GestureDetector(
          onTap: () => showDialog<void>(
            context: context,
            builder: (context) => Dialog(child: InteractiveViewer(child: Image.memory(bytes))),
          ),
          child: Image.memory(bytes, fit: widget.fit, errorBuilder: (_, __, ___) => const Icon(Icons.broken_image)),
        );
      },
    );
  }
}
