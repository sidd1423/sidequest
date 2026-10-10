import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../data/app_scope.dart';
import '../models/journal_entry.dart';

/// A picked photo, ready to upload.
class PickedPhoto {
  const PickedPhoto(this.bytes, this.mime);

  final Uint8List bytes;
  final String mime;
}

typedef PhotoPicker = Future<PickedPhoto?> Function({required bool camera});

/// Notes and photos for one quest ("Quest log"). Shown under the active quest
/// on the Quest tab and on each quest's detail page. Everything is saved on
/// the device first and uploaded when online.
class QuestJournal extends StatefulWidget {
  const QuestJournal({super.key, required this.questId});

  final int questId;

  /// Swappable in tests (the real picker needs the platform).
  static PhotoPicker pickPhoto = _pickWithImagePicker;

  static const maxPhotoBytes = 5 * 1024 * 1024; // same limit as the backend

  /// Camera on phones; on desktop/web only the gallery/file picker.
  static bool get cameraAvailable =>
      !kIsWeb && (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS);

  @override
  State<QuestJournal> createState() => _QuestJournalState();
}

Future<PickedPhoto?> _pickWithImagePicker({required bool camera}) async {
  final file = await ImagePicker().pickImage(
    source: camera ? ImageSource.camera : ImageSource.gallery,
    maxWidth: 1600, // keeps uploads small (a few hundred KB)
    maxHeight: 1600,
    imageQuality: 80,
  );
  if (file == null) return null;
  final name = file.name.toLowerCase();
  final mime = file.mimeType ??
      (name.endsWith('.png')
          ? 'image/png'
          : name.endsWith('.webp')
              ? 'image/webp'
              : name.endsWith('.gif')
                  ? 'image/gif'
                  : name.endsWith('.heic')
                      ? 'image/heic'
                      : 'image/jpeg');
  return PickedPhoto(await file.readAsBytes(), mime);
}

class _QuestJournalState extends State<QuestJournal> {
  final _note = TextEditingController();
  bool _picking = false;

  @override
  void initState() {
    super.initState();
    // Pick up notes/photos added on another device.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) AppScope.read(context).loadJournal(widget.questId);
    });
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _addNote() async {
    final text = _note.text.trim();
    if (text.isEmpty) return;
    _note.clear();
    FocusScope.of(context).unfocus();
    await AppScope.read(context).addNote(widget.questId, text);
  }

  Future<void> _addPhoto({required bool camera}) async {
    final state = AppScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _picking = true);
    try {
      final photo = await QuestJournal.pickPhoto(camera: camera);
      if (photo == null) return;
      if (photo.bytes.length > QuestJournal.maxPhotoBytes) {
        messenger.showSnackBar(const SnackBar(content: Text('That photo is too big (max 5 MB).')));
        return;
      }
      await state.addPhoto(widget.questId, photo.bytes, photo.mime, caption: _note.text);
      _note.clear();
    } on Object catch (e) {
      messenger.showSnackBar(SnackBar(content: Text("Couldn't add the photo: $e")));
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final entries = AppScope.of(context).journal(widget.questId);
    final photos = entries.where((e) => e.isPhoto).toList();
    final notes = entries.where((e) => !e.isPhoto).toList();
    return Card(
      key: const Key('quest_journal'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Quest log', style: theme.textTheme.titleMedium),
            Text(
              'Notes and photos from your quest - just for you.',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
            if (photos.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [for (final p in photos) _PhotoTile(entry: p)],
              ),
            ],
            for (final n in notes) _NoteTile(entry: n),
            const SizedBox(height: 12),
            TextField(
              key: const Key('journal_note_field'),
              controller: _note,
              minLines: 1,
              maxLines: 4,
              maxLength: 2000,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                labelText: 'Add a note',
                hintText: 'What did you see? How did it go?',
                counterText: '',
              ),
              onSubmitted: (_) => _addNote(),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.tonalIcon(
                  key: const Key('add_note_button'),
                  onPressed: _addNote,
                  icon: const Icon(Icons.edit_note),
                  label: const Text('Save note'),
                ),
                OutlinedButton.icon(
                  key: const Key('add_photo_button'),
                  onPressed: _picking ? null : () => _addPhoto(camera: false),
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Add photo'),
                ),
                if (QuestJournal.cameraAvailable)
                  OutlinedButton.icon(
                    key: const Key('take_photo_button'),
                    onPressed: _picking ? null : () => _addPhoto(camera: true),
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: const Text('Take photo'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

String _when(DateTime t) {
  final local = t.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} ${two(local.hour)}:${two(local.minute)}';
}

class _NoteTile extends StatelessWidget {
  const _NoteTile({required this.entry});

  final JournalEntry entry;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      key: Key('journal_note_${entry.clientId}'),
      contentPadding: EdgeInsets.zero,
      leading: Icon(entry.pending ? Icons.cloud_upload_outlined : Icons.sticky_note_2_outlined),
      title: Text(entry.text),
      subtitle: Text(_when(entry.createdAt) + (entry.pending ? ' · waiting to sync' : '')),
      trailing: IconButton(
        key: Key('delete_entry_${entry.clientId}'),
        tooltip: 'Delete note',
        icon: const Icon(Icons.delete_outline),
        onPressed: () => AppScope.read(context).deleteJournalEntry(entry),
      ),
    );
  }
}

class _PhotoTile extends StatefulWidget {
  const _PhotoTile({required this.entry});

  final JournalEntry entry;

  @override
  State<_PhotoTile> createState() => _PhotoTileState();
}

class _PhotoTileState extends State<_PhotoTile> {
  Future<Uint8List?>? _bytes;

  JournalEntry get entry => widget.entry;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _bytes ??= AppScope.read(context).photoBytes(entry); // load once, not on every rebuild
  }

  @override
  void didUpdateWidget(_PhotoTile old) {
    super.didUpdateWidget(old);
    // Uploaded meanwhile (or replaced): keep showing what we have unless it was empty.
    if (old.entry.clientId != entry.clientId) _bytes = AppScope.read(context).photoBytes(entry);
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.read(context);
    return SizedBox(
      key: Key('journal_photo_${entry.clientId}'),
      width: 120,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Stack(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: SizedBox.square(
                  dimension: 120,
                  child: FutureBuilder<Uint8List?>(
                    future: _bytes,
                    builder: (context, snap) {
                      final bytes = snap.data;
                      if (bytes != null) {
                        return GestureDetector(
                          onTap: () => _showFull(context, bytes),
                          child: Image.memory(bytes, fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const _PhotoPlaceholder()),
                        );
                      }
                      return const _PhotoPlaceholder();
                    },
                  ),
                ),
              ),
              Positioned(
                right: 0,
                top: 0,
                child: IconButton.filledTonal(
                  key: Key('delete_entry_${entry.clientId}'),
                  tooltip: 'Delete photo',
                  iconSize: 18,
                  icon: const Icon(Icons.close),
                  onPressed: () => state.deleteJournalEntry(entry),
                ),
              ),
              if (entry.pending)
                const Positioned(
                  left: 4,
                  bottom: 4,
                  child: Tooltip(message: 'Waiting to sync', child: Icon(Icons.cloud_upload_outlined, size: 18)),
                ),
            ],
          ),
          if (entry.text.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(entry.text, maxLines: 2, overflow: TextOverflow.ellipsis),
            ),
        ],
      ),
    );
  }

  void _showFull(BuildContext context, Uint8List bytes) {
    showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        child: InteractiveViewer(child: Image.memory(bytes)),
      ),
    );
  }
}

class _PhotoPlaceholder extends StatelessWidget {
  const _PhotoPlaceholder();

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: const Center(child: Icon(Icons.image_outlined)),
    );
  }
}
