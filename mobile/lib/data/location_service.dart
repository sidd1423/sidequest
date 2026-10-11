import 'dart:async';

import 'package:geolocator/geolocator.dart';

import '../models/location.dart';

/// Why we couldn't get a position.
enum LocationProblem {
  /// Location services (GPS) are switched off on the device.
  serviceOff,

  /// The user said no (we can ask again).
  denied,

  /// The user said "never" - only the system settings can change it.
  deniedForever,

  /// No fix in time / not supported here.
  unavailable,
}

class LocationException implements Exception {
  const LocationException(this.problem);

  final LocationProblem problem;

  String get message => switch (problem) {
        LocationProblem.serviceOff => 'Location is switched off on this device.',
        LocationProblem.denied => 'Sidequest doesn\'t have permission to use your location.',
        LocationProblem.deniedForever =>
          'Location permission is blocked for Sidequest - turn it on in your device settings.',
        LocationProblem.unavailable => "Couldn't get your location right now.",
      };

  @override
  String toString() => message;
}

/// Where the device is. Swappable in tests (see test/fake_location.dart).
abstract class LocationService {
  /// Current position. [ask]: show the permission prompt if needed (otherwise
  /// only works when permission was already given). Throws [LocationException].
  Future<GeoPoint> current({bool ask = true});

  /// Positions while walking (foreground only), every few metres.
  /// Throws [LocationException] (on listen) if permission is missing.
  Stream<GeoPoint> track();

  /// Open the system screen where the user can fix [problem].
  Future<void> openSettings(LocationProblem problem);
}

/// The real thing, via the geolocator plugin (Android, iOS, Windows, macOS, web).
class DeviceLocationService implements LocationService {
  Future<void> _ensurePermission({required bool ask}) async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const LocationException(LocationProblem.serviceOff);
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied && ask) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) {
      throw const LocationException(LocationProblem.deniedForever);
    }
    if (permission == LocationPermission.denied) {
      throw const LocationException(LocationProblem.denied);
    }
  }

  static GeoPoint _point(Position p) =>
      GeoPoint(lat: p.latitude, lon: p.longitude, accuracyM: p.accuracy, time: p.timestamp.toLocal());

  @override
  Future<GeoPoint> current({bool ask = true}) async {
    await _ensurePermission(ask: ask);
    try {
      final p = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 15)),
      );
      return _point(p);
    } on TimeoutException {
      // Indoors / slow GPS: a recent last-known fix is good enough to find the weather.
      final last = await _lastKnown();
      if (last != null) return last;
      throw const LocationException(LocationProblem.unavailable);
    } on LocationServiceDisabledException {
      throw const LocationException(LocationProblem.serviceOff);
    } on PermissionDeniedException {
      throw const LocationException(LocationProblem.denied);
    }
  }

  Future<GeoPoint?> _lastKnown() async {
    try {
      final p = await Geolocator.getLastKnownPosition(); // not supported on web
      return p == null ? null : _point(p);
    } on Object {
      return null;
    }
  }

  @override
  Stream<GeoPoint> track() async* {
    await _ensurePermission(ask: true);
    yield* Geolocator.getPositionStream(
      locationSettings: const LocationSettings(accuracy: LocationAccuracy.best, distanceFilter: 5),
    ).map(_point);
  }

  @override
  Future<void> openSettings(LocationProblem problem) async {
    if (problem == LocationProblem.serviceOff) {
      await Geolocator.openLocationSettings();
    } else {
      await Geolocator.openAppSettings();
    }
  }
}
