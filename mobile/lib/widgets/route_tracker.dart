import 'package:flutter/material.dart';

import '../data/app_scope.dart';
import '../models/location.dart';
import 'route_map.dart';

/// "Your route" card: the map of the path walked during a quest.
///
/// [canTrack] (the quest you're doing now): Start / Stop / Continue tracking,
/// with the map following you live. Otherwise (History) it just shows the
/// recorded route, downloading it if it was recorded on another device.
class RouteTracker extends StatefulWidget {
  const RouteTracker({super.key, required this.questId, this.canTrack = false, this.places = const []});

  final int questId;
  final bool canTrack;
  final List<NearbyPlace> places;

  @override
  State<RouteTracker> createState() => _RouteTrackerState();
}

class _RouteTrackerState extends State<RouteTracker> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) AppScope.read(context).loadRoute(widget.questId);
    });
  }

  Future<void> _confirmDelete() async {
    final state = AppScope.read(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this route?'),
        content: const Text('The map of where you walked is removed from this device and your account.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            key: const Key('route_delete_confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok == true) await state.deleteRoute(widget.questId);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final points = state.route(widget.questId);
    final tracking = state.isTracking(widget.questId);
    final matches = state.quests.where((q) => q.id == widget.questId);
    final summary = points.isNotEmpty
        ? RouteSummary.measure(points)
        : (matches.isEmpty ? null : matches.first.route);
    final error = state.trackingError;

    if (!widget.canTrack && points.isEmpty && summary == null) return const SizedBox.shrink();

    return Card(
      key: const Key('route_tracker'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(tracking ? Icons.navigation : Icons.route, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(child: Text('Your route', style: theme.textTheme.titleMedium)),
                if (tracking)
                  Chip(
                    key: const Key('tracking_chip'),
                    avatar: const Icon(Icons.fiber_manual_record, color: Colors.red, size: 14),
                    label: const Text('Recording'),
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
            const SizedBox(height: 4),
            if (summary != null && summary.points > 0)
              Text(summary.label, key: const Key('route_summary'), style: theme.textTheme.titleSmall)
            else if (widget.canTrack)
              Text(
                'Record the path you take while you do this quest - see it on a map afterwards. '
                'Keep the app open while you walk.',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            if (points.isNotEmpty || tracking) ...[
              const SizedBox(height: 12),
              RouteMap(points: points, live: tracking, places: widget.places),
            ] else if (summary != null && summary.points > 0) ...[
              const SizedBox(height: 8),
              Text(
                state.isOnline ? 'Loading the map...' : 'The map needs a connection the first time.',
                style: theme.textTheme.bodySmall,
              ),
            ],
            if (tracking && points.isEmpty) ...[
              const SizedBox(height: 8),
              const Text('Waiting for GPS...', key: Key('route_waiting')),
            ],
            if (error != null && !tracking && widget.canTrack) ...[
              const SizedBox(height: 8),
              Text(error, key: const Key('route_error'), style: TextStyle(color: theme.colorScheme.error)),
            ],
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (widget.canTrack && tracking)
                  FilledButton.tonalIcon(
                    key: const Key('route_stop'),
                    onPressed: () => state.stopTracking(),
                    icon: const Icon(Icons.stop),
                    label: const Text('Stop tracking'),
                  )
                else if (widget.canTrack)
                  FilledButton.icon(
                    key: const Key('route_start'),
                    onPressed: () => state.startTracking(widget.questId),
                    icon: const Icon(Icons.play_arrow),
                    label: Text(points.isEmpty ? 'Start tracking my route' : 'Continue tracking'),
                  ),
                if (points.isNotEmpty && !tracking)
                  TextButton.icon(
                    key: const Key('route_delete'),
                    onPressed: _confirmDelete,
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('Delete route'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
