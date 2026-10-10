import 'package:flutter/material.dart' show RangeValues;

/// The preferences a user sets once (at sign-up) and can change in Edit
/// account. Minutes, difficulty, energy, distance and who's with you are NOT here - those are
/// picked on the Quest page right before each quest.
class ProfilePreferences {
  ProfilePreferences({
    Set<String>? interests,
    this.customInterests = '',
    Set<String>? accessibility,
    this.accessibilityNotes = '',
    Set<String>? surroundings,
    this.crowd = 'moderate',
    Set<String>? weatherAvoid,
    this.temperatureC = const RangeValues(5, 30),
    Map<String, dynamic>? perQuestDefaults,
  })  : perQuestDefaults = perQuestDefaults ?? const {},
        interests = interests ?? <String>{},
        accessibility = accessibility ?? <String>{},
        surroundings = surroundings ?? <String>{},
        weatherAvoid = weatherAvoid ?? <String>{};

  final Set<String> interests;
  String customInterests; // comma-separated free text
  final Set<String> accessibility;
  String accessibilityNotes;
  final Set<String> surroundings;
  String crowd;
  final Set<String> weatherAvoid;
  RangeValues temperatureC;

  /// Backend fields this form doesn't edit (default minutes, difficulty,
  /// energy, distance). Kept so saving doesn't wipe values set elsewhere,
  /// e.g. in the Streamlit app. The Quest page sends its own per quest.
  final Map<String, dynamic> perQuestDefaults;

  /// At least one interest (picked or typed) is required, like the backend.
  bool get hasInterest => interests.isNotEmpty || customInterests.trim().isNotEmpty;

  ProfilePreferences copy() => ProfilePreferences.fromJson(toJson());

  /// Body for PUT /users/{id}/preferences (backend PreferencesIn).
  Map<String, dynamic> toJson() {
    final d = perQuestDefaults;
    return {
      'interests': interests.toList(),
      'custom_interests': [
        for (final s in customInterests.split(','))
          if (s.trim().isNotEmpty) s.trim(),
      ],
      if (d['availability'] != null) 'availability': d['availability'],
      if (d['difficulty'] != null) 'difficulty': d['difficulty'],
      if (d['energy_level'] != null) 'energy_level': d['energy_level'],
      'accessibility': {'needs': accessibility.toList(), 'notes': accessibilityNotes.trim()},
      'environment': {
        'surroundings': surroundings.toList(),
        'crowd_tolerance': crowd,
        if (d['group_size'] != null) 'group_size': d['group_size'],
        if (d['max_travel_km'] != null) 'max_travel_km': d['max_travel_km'],
      },
      'weather': {
        'avoid': weatherAvoid.toList(),
        'min_temp_c': temperatureC.start.round(),
        'max_temp_c': temperatureC.end.round(),
      },
    };
  }

  /// From GET /users/{id}/preferences (or the on-device cache).
  factory ProfilePreferences.fromJson(Map<String, dynamic> json) {
    Set<String> strings(Object? list) => {for (final v in (list as List<dynamic>? ?? const [])) v as String};
    final accessibility = (json['accessibility'] as Map<String, dynamic>?) ?? const {};
    final environment = (json['environment'] as Map<String, dynamic>?) ?? const {};
    final weather = (json['weather'] as Map<String, dynamic>?) ?? const {};
    return ProfilePreferences(
      interests: strings(json['interests']),
      customInterests: strings(json['custom_interests']).join(', '),
      accessibility: strings(accessibility['needs']),
      accessibilityNotes: (accessibility['notes'] as String?) ?? '',
      surroundings: strings(environment['surroundings']),
      crowd: (environment['crowd_tolerance'] as String?) ?? 'moderate',
      weatherAvoid: strings(weather['avoid']),
      // Clamped to the form's slider range (-20..40 C).
      temperatureC: RangeValues(
        ((weather['min_temp_c'] as num?) ?? 5).toDouble().clamp(-20.0, 40.0),
        ((weather['max_temp_c'] as num?) ?? 30).toDouble().clamp(-20.0, 40.0),
      ),
      perQuestDefaults: {
        if (json['availability'] != null) 'availability': json['availability'],
        if (json['difficulty'] != null) 'difficulty': json['difficulty'],
        if (json['energy_level'] != null) 'energy_level': json['energy_level'],
        if (environment['max_travel_km'] != null) 'max_travel_km': environment['max_travel_km'],
        if (environment['group_size'] != null) 'group_size': environment['group_size'],
      },
    );
  }
}
