import 'package:flutter/material.dart' show RangeValues;

/// The preferences a user sets once (at sign-up) and can change in Edit
/// account. Difficulty, energy, distance and minutes are NOT here - those are
/// picked on the Quest page right before each quest.
class ProfilePreferences {
  ProfilePreferences({
    Set<String>? interests,
    this.customInterests = '',
    Set<String>? accessibility,
    this.accessibilityNotes = '',
    Set<String>? surroundings,
    this.crowd = 'moderate',
    this.group = 'solo',
    Set<String>? weatherAvoid,
    this.temperatureC = const RangeValues(5, 30),
  })  : interests = interests ?? <String>{},
        accessibility = accessibility ?? <String>{},
        surroundings = surroundings ?? <String>{},
        weatherAvoid = weatherAvoid ?? <String>{};

  final Set<String> interests;
  String customInterests; // comma-separated free text
  final Set<String> accessibility;
  String accessibilityNotes;
  final Set<String> surroundings;
  String crowd;
  String group;
  final Set<String> weatherAvoid;
  RangeValues temperatureC;

  /// At least one interest (picked or typed) is required, like the backend.
  bool get hasInterest => interests.isNotEmpty || customInterests.trim().isNotEmpty;
}
