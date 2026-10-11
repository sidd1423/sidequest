import 'dart:convert';
import 'dart:typed_data';

/// A note or photo the user adds to a quest (backend `quest_logs`).
class JournalEntry {
  const JournalEntry({
    required this.clientId,
    required this.questId,
    required this.kind,
    required this.createdAt,
    this.text = '',
    this.serverId,
    this.mime,
    this.localImageBase64,
    this.pending = false,
    this.step,
  });

  /// Chosen on the device; the server uses it to ignore duplicate uploads.
  final String clientId;
  final int questId;
  final String kind; // note | photo
  final String text; // the note, or a photo caption
  final DateTime createdAt;

  /// Server row id (null until uploaded) - used to download the photo.
  final int? serverId;
  final String? mime;

  /// Photo bytes kept on the device until they've been uploaded.
  final String? localImageBase64;
  final bool pending;

  /// The quest step (1-based) a photo was taken at, for the album. null =
  /// added from the quest log, not during a step.
  final int? step;

  bool get isPhoto => kind == 'photo';
  Uint8List? get localImage => localImageBase64 == null ? null : base64Decode(localImageBase64!);

  JournalEntry uploaded(int id) => JournalEntry(
        clientId: clientId,
        questId: questId,
        kind: kind,
        createdAt: createdAt,
        text: text,
        serverId: id,
        mime: mime,
        step: step,
        // Bytes are dropped once uploaded (device storage is small, e.g. 5 MB
        // on web); the photo is downloaded from the server when needed.
      );

  /// Body for POST /users/{id}/quests/{questId}/logs.
  Map<String, dynamic> toUpload() => {
        'client_id': clientId,
        'kind': kind,
        'text': text,
        if (isPhoto) 'image_base64': localImageBase64,
        if (isPhoto) 'mime': mime,
        if (step != null) 'step': step,
        'created_at': createdAt.toUtc().toIso8601String(),
      };

  /// From the server's list (GET .../logs).
  factory JournalEntry.fromServer(Map<String, dynamic> json) => JournalEntry(
        clientId: json['client_id'] as String,
        questId: (json['quest_id'] as num).toInt(),
        kind: json['kind'] as String,
        text: (json['text'] as String?) ?? '',
        createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
        serverId: (json['id'] as num).toInt(),
        mime: json['mime'] as String?,
        step: (json['step'] as num?)?.toInt(),
      );

  factory JournalEntry.fromJson(Map<String, dynamic> json) => JournalEntry(
        clientId: json['client_id'] as String,
        questId: (json['quest_id'] as num).toInt(),
        kind: json['kind'] as String,
        text: (json['text'] as String?) ?? '',
        createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
        serverId: (json['server_id'] as num?)?.toInt(),
        mime: json['mime'] as String?,
        localImageBase64: json['local_image'] as String?,
        pending: (json['pending'] as bool?) ?? false,
        step: (json['step'] as num?)?.toInt(),
      );

  /// For the on-device cache.
  Map<String, dynamic> toJson() => {
        'client_id': clientId,
        'quest_id': questId,
        'kind': kind,
        'text': text,
        'created_at': createdAt.toIso8601String(),
        if (serverId != null) 'server_id': serverId,
        if (mime != null) 'mime': mime,
        if (localImageBase64 != null) 'local_image': localImageBase64,
        if (pending) 'pending': true,
        if (step != null) 'step': step,
      };
}
