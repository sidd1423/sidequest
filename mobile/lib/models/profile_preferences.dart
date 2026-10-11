/// The preferences a user sets once (at sign-up) and can change in Edit
/// account. Minutes, difficulty, energy, distance and who's with you are NOT here - those are
/// picked on the Quest page right before each quest. Weather and what's around
/// you aren't either - they're looked up live from your location for every quest.
class ProfilePreferences {
  ProfilePreferences({
    Set<String>? interests,
    this.customInterests = '',
    Set<String>? accessibility,
    this.accessibilityNotes = '',
    this.crowd = 'moderate',
    Map<String, dynamic>? perQuestDefaults,
  })  : perQuestDefaults = perQuestDefaults ?? const {},
        interests = interests ?? <String>{},
        accessibility = accessibility ?? <String>{};

  final Set<String> interests;
  String customInterests; // comma-separated free text
  final Set<String> accessibility;
  String accessibilityNotes;
  String crowd;

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
        'crowd_tolerance': crowd,
        if (d['group_size'] != null) 'group_size': d['group_size'],
        if (d['max_travel_km'] != null) 'max_travel_km': d['max_travel_km'],
      },
    };
  }

  /// From GET /users/{id}/preferences (or the on-device cache).
  factory ProfilePreferences.fromJson(Map<String, dynamic> json) {
    Set<String> strings(Object? list) => {for (final v in (list as List<dynamic>? ?? const [])) v as String};
    final accessibility = (json['accessibility'] as Map<String, dynamic>?) ?? const {};
    final environment = (json['environment'] as Map<String, dynamic>?) ?? const {};
    return ProfilePreferences(
      interests: strings(json['interests']),
      customInterests: strings(json['custom_interests']).join(', '),
      accessibility: strings(accessibility['needs']),
      accessibilityNotes: (accessibility['notes'] as String?) ?? '',
      crowd: (environment['crowd_tolerance'] as String?) ?? 'moderate',
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
