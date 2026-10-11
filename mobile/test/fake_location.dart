// A stand-in for the device GPS (lib/data/location_service.dart).
import 'dart:async';

import 'package:sidequest/data/location_service.dart';
import 'package:sidequest/models/location.dart';

class FakeLocation implements LocationService {
  /// Where the "device" is. null = permission not given ([problem]).
  GeoPoint? position;
  LocationProblem problem = LocationProblem.denied;

  /// Permission prompts shown (current(ask: true) / track()).
  int asked = 0;
  int settingsOpened = 0;

  StreamController<GeoPoint>? _walk;

  /// Is a route being recorded right now?
  bool get tracking => _walk != null && _walk!.hasListener;

  @override
  Future<GeoPoint> current({bool ask = true}) async {
    if (ask) asked++;
    final p = position;
    if (p == null) throw LocationException(problem);
    return p;
  }

  @override
  Stream<GeoPoint> track() {
    asked++;
    if (position == null) return Stream.error(LocationException(problem));
    final controller = StreamController<GeoPoint>();
    controller.onCancel = () {
      if (identical(_walk, controller)) _walk = null;
    };
    _walk = controller;
    return controller.stream;
  }

  /// Move the walker (while tracking).
  void walkTo(GeoPoint p) {
    position = p;
    _walk?.add(p);
  }

  @override
  Future<void> openSettings(LocationProblem problem) async => settingsOpened++;
}
