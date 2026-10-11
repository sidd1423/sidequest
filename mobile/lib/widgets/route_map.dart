import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../models/location.dart';

/// A map (OpenStreetMap tiles) with the path walked during a quest: a line
/// from the green start dot to the red end dot. [live]: keeps the newest
/// point in view while tracking.
class RouteMap extends StatefulWidget {
  const RouteMap({
    super.key,
    required this.points,
    this.live = false,
    this.height = 240,
    this.places = const [],
    this.center,
  });

  final List<GeoPoint> points;
  final bool live;
  final double height;

  /// Real spots near where the quest was made (pins), if known.
  final List<NearbyPlace> places;

  /// Where to look before the first GPS point (e.g. where the quest was made).
  final LatLng? center;

  /// Widget tests turn this off: no network tiles there.
  static bool tilesEnabled = true;

  /// OpenStreetMap's tile policy asks apps to identify themselves.
  static const userAgentPackageName = 'com.sidequest.app';

  @override
  State<RouteMap> createState() => _RouteMapState();
}

class _RouteMapState extends State<RouteMap> {
  final _controller = MapController();
  bool _ready = false;

  List<LatLng> get _line => [for (final p in widget.points) LatLng(p.lat, p.lon)];

  @override
  void didUpdateWidget(RouteMap old) {
    super.didUpdateWidget(old);
    // Follow the walker while tracking.
    if (widget.live && _ready && widget.points.length != old.points.length && widget.points.isNotEmpty) {
      final first = old.points.isEmpty; // first fix: zoom in on it
      final last = widget.points.last;
      _controller.move(LatLng(last.lat, last.lon), first ? 17 : _controller.camera.zoom);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  MapOptions _options() {
    final line = _line;
    final distinct = line.toSet();
    const interaction = InteractionOptions(flags: InteractiveFlag.all & ~InteractiveFlag.rotate);
    if (distinct.length >= 2 && !widget.live) {
      return MapOptions(
        initialCameraFit: CameraFit.bounds(
          bounds: LatLngBounds.fromPoints(line),
          padding: const EdgeInsets.all(32),
          maxZoom: 18,
        ),
        interactionOptions: interaction,
        onMapReady: () => _ready = true,
      );
    }
    return MapOptions(
      initialCenter: line.isNotEmpty ? line.last : (widget.center ?? const LatLng(0, 0)),
      initialZoom: line.isNotEmpty ? 17 : (widget.center != null ? 15 : 2),
      interactionOptions: interaction,
      onMapReady: () => _ready = true,
    );
  }

  Widget _dot(Color color) => DecoratedBox(
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 3),
          boxShadow: const [BoxShadow(blurRadius: 4, color: Colors.black38)],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final line = _line;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: SizedBox(
        key: const Key('route_map'),
        height: widget.height,
        child: FlutterMap(
          mapController: _controller,
          options: _options(),
          children: [
            if (RouteMap.tilesEnabled)
              TileLayer(
                urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: RouteMap.userAgentPackageName,
                maxZoom: 19,
              )
            else
              SizedBox.expand(child: ColoredBox(color: colors.surfaceContainerHighest)),
            if (line.length >= 2)
              PolylineLayer(polylines: [
                Polyline(points: line, strokeWidth: 5, color: colors.primary, borderStrokeWidth: 2,
                    borderColor: Colors.white),
              ]),
            MarkerLayer(markers: [
              for (final p in widget.places)
                if (p.lat != null && p.lon != null)
                Marker(
                  point: LatLng(p.lat!, p.lon!),
                  width: 28,
                  height: 28,
                  child: Tooltip(message: p.name, child: Icon(Icons.place, color: colors.tertiary, size: 28)),
                ),
              if (line.isNotEmpty)
                Marker(point: line.first, width: 18, height: 18, child: _dot(Colors.green)),
              if (line.length >= 2)
                Marker(
                  point: line.last,
                  width: 18,
                  height: 18,
                  child: _dot(widget.live ? Colors.blue : Colors.red),
                ),
            ]),
            if (RouteMap.tilesEnabled)
              const SimpleAttributionWidget(source: Text('OpenStreetMap contributors')),
          ],
        ),
      ),
    );
  }
}
