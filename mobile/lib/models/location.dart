import 'dart:math' as math;

/// A position from the device (backend GeoPoint / RoutePoint).
class GeoPoint {
  const GeoPoint({required this.lat, required this.lon, this.accuracyM, this.time});

  final double lat;
  final double lon;
  final double? accuracyM;
  final DateTime? time; // when it was recorded (route points)

  /// Body for QuestSettings.location.
  Map<String, dynamic> toLocationJson() => {
        'lat': lat,
        'lon': lon,
        if (accuracyM != null) 'accuracy_m': accuracyM,
      };

  /// A route point: {lat, lon, t, accuracy_m}.
  Map<String, dynamic> toJson() => {
        'lat': lat,
        'lon': lon,
        't': (time ?? DateTime.now()).toUtc().toIso8601String(),
        if (accuracyM != null) 'accuracy_m': accuracyM,
      };

  factory GeoPoint.fromJson(Map<String, dynamic> json) => GeoPoint(
        lat: (json['lat'] as num).toDouble(),
        lon: (json['lon'] as num).toDouble(),
        accuracyM: (json['accuracy_m'] as num?)?.toDouble(),
        time: DateTime.tryParse(json['t'] as String? ?? '')?.toLocal(),
      );

  /// Great-circle distance in metres.
  double distanceTo(GeoPoint other) {
    const r = 6371000.0;
    double rad(double d) => d * math.pi / 180;
    final dLat = rad(other.lat - lat);
    final dLon = rad(other.lon - lon);
    final a = math.pow(math.sin(dLat / 2), 2) +
        math.cos(rad(lat)) * math.cos(rad(other.lat)) * math.pow(math.sin(dLon / 2), 2);
    return 2 * r * math.asin(math.min(1.0, math.sqrt(a)));
  }
}

/// Weather where the user was when a quest was made (backend WeatherNow).
class WeatherNow {
  const WeatherNow({
    required this.tempC,
    this.feelsLikeC,
    this.condition = '',
    this.rainChancePct,
    this.windKmh,
    this.isDay,
    this.airQualityIndex,
    this.sunset,
  });

  final double tempC;
  final double? feelsLikeC;
  final String condition;
  final int? rainChancePct;
  final double? windKmh;
  final bool? isDay;
  final int? airQualityIndex;
  final String? sunset;

  factory WeatherNow.fromJson(Map<String, dynamic> json) => WeatherNow(
        tempC: (json['temp_c'] as num).toDouble(),
        feelsLikeC: (json['feels_like_c'] as num?)?.toDouble(),
        condition: (json['condition'] as String?) ?? '',
        rainChancePct: (json['rain_chance_pct'] as num?)?.toInt(),
        windKmh: (json['wind_kmh'] as num?)?.toDouble(),
        isDay: json['is_day'] as bool?,
        airQualityIndex: (json['air_quality_index'] as num?)?.toInt(),
        sunset: json['sunset'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'temp_c': tempC,
        'feels_like_c': feelsLikeC,
        'condition': condition,
        'rain_chance_pct': rainChancePct,
        'wind_kmh': windKmh,
        'is_day': isDay,
        'air_quality_index': airQualityIndex,
        'sunset': sunset,
      };

  /// "12°C, light rain"
  String get short => '${tempC.round()}°C${condition.isEmpty ? '' : ', $condition'}';
}

/// A real outdoor spot near the user (backend NearbyPlace).
class NearbyPlace {
  const NearbyPlace({
    required this.name,
    required this.kind,
    required this.distanceM,
    this.direction = '',
    this.lat,
    this.lon,
    this.rating,
    this.openState = '',
  });

  final String name;
  final String kind;
  final int distanceM;
  final String direction;
  final double? lat;
  final double? lon;
  final double? rating; // Google rating (SerpApi), null for OpenStreetMap places
  final String openState; // "Open 24 hours", "Closes 9 PM"...

  /// "Riverdale Park · park · 350 m NE"
  String get label => '$name · $kind · ${distanceM >= 1000 ? '${(distanceM / 1000).toStringAsFixed(1)} km' : '$distanceM m'}'
      '${direction.isEmpty ? '' : ' $direction'}';

  factory NearbyPlace.fromJson(Map<String, dynamic> json) => NearbyPlace(
        name: json['name'] as String,
        kind: (json['kind'] as String?) ?? '',
        distanceM: (json['distance_m'] as num?)?.toInt() ?? 0,
        direction: (json['direction'] as String?) ?? '',
        lat: (json['lat'] as num?)?.toDouble(),
        lon: (json['lon'] as num?)?.toDouble(),
        rating: (json['rating'] as num?)?.toDouble(),
        openState: (json['open_state'] as String?) ?? '',
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        'kind': kind,
        'distance_m': distanceM,
        'direction': direction,
        'lat': lat,
        'lon': lon,
        'rating': rating,
        'open_state': openState,
      };
}

/// Where/when a quest was generated (backend QuestContext): place, weather,
/// nearby spots. Also what GET /users/{id}/conditions returns.
class QuestConditions {
  const QuestConditions({this.place = '', this.lat, this.lon, this.weather, this.nearby = const []});

  final String place;
  final double? lat;
  final double? lon;
  final WeatherNow? weather;
  final List<NearbyPlace> nearby;

  bool get isEmpty => place.isEmpty && weather == null && nearby.isEmpty;

  factory QuestConditions.fromJson(Map<String, dynamic> json) => QuestConditions(
        place: (json['place'] as String?) ?? '',
        lat: (json['lat'] as num?)?.toDouble(),
        lon: (json['lon'] as num?)?.toDouble(),
        weather: json['weather'] == null ? null : WeatherNow.fromJson(json['weather'] as Map<String, dynamic>),
        nearby: [
          for (final p in (json['nearby'] as List<dynamic>? ?? const [])) NearbyPlace.fromJson(p as Map<String, dynamic>),
        ],
      );

  Map<String, dynamic> toJson() => {
        'place': place,
        'lat': lat,
        'lon': lon,
        'weather': weather?.toJson(),
        'nearby': [for (final p in nearby) p.toJson()],
      };

  /// "📍 Riverdale, Toronto · 12°C, light rain"
  String get summary => [
        if (place.isNotEmpty) '📍 $place',
        if (weather != null) weather!.short,
      ].join(' · ');
}

/// Distance/duration of a recorded route (backend RouteSummary, or worked out on the device).
class RouteSummary {
  const RouteSummary({required this.distanceM, required this.durationSeconds, required this.points});

  final int distanceM;
  final int durationSeconds;
  final int points;

  factory RouteSummary.fromJson(Map<String, dynamic> json) => RouteSummary(
        distanceM: (json['distance_m'] as num).toInt(),
        durationSeconds: (json['duration_seconds'] as num).toInt(),
        points: (json['points'] as num).toInt(),
      );

  Map<String, dynamic> toJson() => {'distance_m': distanceM, 'duration_seconds': durationSeconds, 'points': points};

  /// Same rules as the backend (backend/routes.py): skip fixes worse than
  /// 75 m and jumps faster than 15 m/s (GPS glitches).
  factory RouteSummary.measure(List<GeoPoint> points) {
    if (points.length < 2) return RouteSummary(distanceM: 0, durationSeconds: 0, points: points.length);
    var total = 0.0;
    GeoPoint? last;
    for (final p in points) {
      if (p.accuracyM != null && p.accuracyM! > 75) continue;
      if (last != null) {
        final d = last.distanceTo(p);
        final secs = (p.time != null && last.time != null) ? p.time!.difference(last.time!).inMilliseconds / 1000 : 0;
        if (secs > 0 && d / secs > 15) continue;
        total += d;
      }
      last = p;
    }
    final first = points.first.time;
    final end = points.last.time;
    return RouteSummary(
      distanceM: total.round(),
      durationSeconds: first != null && end != null ? end.difference(first).inSeconds : 0,
      points: points.length,
    );
  }

  /// "1.2 km · 18 min"
  String get label {
    final dist = distanceM >= 1000 ? '${(distanceM / 1000).toStringAsFixed(1)} km' : '$distanceM m';
    final mins = (durationSeconds / 60).round();
    return '$dist · $mins min';
  }
}
