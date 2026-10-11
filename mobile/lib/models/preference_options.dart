import 'package:flutter/material.dart';

/// Option lists for the quest preferences. Values mirror the backend's
/// enums in backend/schemas.py so they can be sent as-is later.
class PreferenceOption {
  const PreferenceOption(this.value, this.label, this.icon);

  final String value; // what the backend expects
  final String label; // what the user sees
  final IconData icon;
}

// --- Set once at sign-up (editable in Edit account) ---------------------------

const interestOptions = [
  PreferenceOption('outdoors', 'Outdoors', Icons.terrain),
  PreferenceOption('nature', 'Nature', Icons.park_outlined),
  PreferenceOption('art', 'Art', Icons.palette_outlined),
  PreferenceOption('music', 'Music', Icons.music_note_outlined),
  PreferenceOption('food', 'Food', Icons.restaurant_outlined),
  PreferenceOption('history', 'History', Icons.account_balance_outlined),
  PreferenceOption('fitness', 'Fitness', Icons.fitness_center),
  PreferenceOption('photography', 'Photography', Icons.photo_camera_outlined),
  PreferenceOption('gaming', 'Gaming', Icons.sports_esports_outlined),
  PreferenceOption('learning', 'Learning', Icons.menu_book_outlined),
  PreferenceOption('social', 'Social', Icons.groups_outlined),
  PreferenceOption('volunteering', 'Volunteering', Icons.volunteer_activism_outlined),
  PreferenceOption('shopping', 'Shopping', Icons.shopping_bag_outlined),
  PreferenceOption('nightlife', 'Nightlife', Icons.nightlife),
  PreferenceOption('wellness', 'Wellness', Icons.spa_outlined),
];

const accessibilityOptions = [
  PreferenceOption('wheelchair_accessible', 'Wheelchair accessible', Icons.accessible),
  PreferenceOption('step_free', 'Step-free', Icons.stairs_outlined),
  PreferenceOption('limited_mobility', 'Limited mobility', Icons.accessibility_new),
  PreferenceOption('frequent_rest_stops', 'Frequent rest stops', Icons.weekend_outlined),
  PreferenceOption('visual_impairment', 'Visual impairment', Icons.visibility_outlined),
  PreferenceOption('hearing_impairment', 'Hearing impairment', Icons.hearing_disabled),
  PreferenceOption('sensory_friendly', 'Sensory-friendly', Icons.volume_off_outlined),
  PreferenceOption('service_animal', 'Service animal', Icons.pets),
  PreferenceOption('accessible_restrooms', 'Accessible restrooms', Icons.wc),
];

const crowdOptions = [
  PreferenceOption('quiet', 'Quiet', Icons.volume_mute_outlined),
  PreferenceOption('moderate', 'Some people', Icons.person_outline),
  PreferenceOption('busy', 'Busy is fine', Icons.groups_outlined),
];

// --- Chosen right before each quest ---------------------------------------------

const minuteOptions = [5, 10, 15, 20, 30];

const groupOptions = [
  PreferenceOption('solo', 'Just me', Icons.person_outline),
  PreferenceOption('pair', 'Me + 1', Icons.people_outline),
  PreferenceOption('small_group', 'Small group (3-6)', Icons.groups_outlined),
  PreferenceOption('large_group', 'Big group (7+)', Icons.groups),
];

const difficultyOptions = [
  PreferenceOption('easy', 'Easy', Icons.sentiment_satisfied_outlined),
  PreferenceOption('moderate', 'Moderate', Icons.trending_flat),
  PreferenceOption('challenging', 'Challenging', Icons.trending_up),
  PreferenceOption('extreme', 'Extreme', Icons.thunderstorm_outlined),
];

const energyLabels = {1: 'Very low', 2: 'Low', 3: 'Medium', 4: 'High', 5: 'Very high'};

const maxDistanceKm = 5.0;
