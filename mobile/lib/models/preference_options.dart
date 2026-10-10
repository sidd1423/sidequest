/// Option lists for the quest preferences. Values mirror the backend's
/// enums in backend/schemas.py so they can be sent as-is later.
class PreferenceOption {
  const PreferenceOption(this.value, this.label);

  final String value; // what the backend expects
  final String label; // what the user sees
}

// --- Set once at sign-up (editable in Edit account) ---------------------------

const interestOptions = [
  PreferenceOption('outdoors', 'Outdoors'),
  PreferenceOption('nature', 'Nature'),
  PreferenceOption('art', 'Art'),
  PreferenceOption('music', 'Music'),
  PreferenceOption('food', 'Food'),
  PreferenceOption('history', 'History'),
  PreferenceOption('fitness', 'Fitness'),
  PreferenceOption('photography', 'Photography'),
  PreferenceOption('gaming', 'Gaming'),
  PreferenceOption('learning', 'Learning'),
  PreferenceOption('social', 'Social'),
  PreferenceOption('volunteering', 'Volunteering'),
  PreferenceOption('shopping', 'Shopping'),
  PreferenceOption('nightlife', 'Nightlife'),
  PreferenceOption('wellness', 'Wellness'),
];

const accessibilityOptions = [
  PreferenceOption('wheelchair_accessible', 'Wheelchair accessible'),
  PreferenceOption('step_free', 'Step-free'),
  PreferenceOption('limited_mobility', 'Limited mobility'),
  PreferenceOption('frequent_rest_stops', 'Frequent rest stops'),
  PreferenceOption('visual_impairment', 'Visual impairment'),
  PreferenceOption('hearing_impairment', 'Hearing impairment'),
  PreferenceOption('sensory_friendly', 'Sensory-friendly'),
  PreferenceOption('service_animal', 'Service animal'),
  PreferenceOption('accessible_restrooms', 'Accessible restrooms'),
];

const surroundingsOptions = [
  PreferenceOption('urban', 'Urban'),
  PreferenceOption('suburban', 'Suburban'),
  PreferenceOption('rural', 'Rural'),
  PreferenceOption('wilderness', 'Wilderness'),
  PreferenceOption('waterfront', 'Waterfront'),
];

const crowdOptions = [
  PreferenceOption('quiet', 'Quiet'),
  PreferenceOption('moderate', 'Some people'),
  PreferenceOption('busy', 'Busy is fine'),
];

const weatherAvoidOptions = [
  PreferenceOption('rain', 'Rain'),
  PreferenceOption('snow', 'Snow'),
  PreferenceOption('wind', 'Wind'),
  PreferenceOption('extreme_heat', 'Extreme heat'),
  PreferenceOption('extreme_cold', 'Extreme cold'),
  PreferenceOption('high_uv', 'High UV'),
  PreferenceOption('poor_air_quality', 'Poor air quality'),
];

// --- Chosen right before each quest ---------------------------------------------

const minuteOptions = [5, 10, 15, 20, 30];

const groupOptions = [
  PreferenceOption('solo', 'Just me'),
  PreferenceOption('pair', 'Me + 1'),
  PreferenceOption('small_group', 'Small group (3-6)'),
  PreferenceOption('large_group', 'Big group (7+)'),
];

const difficultyOptions = [
  PreferenceOption('easy', 'Easy'),
  PreferenceOption('moderate', 'Moderate'),
  PreferenceOption('challenging', 'Challenging'),
  PreferenceOption('extreme', 'Extreme'),
];

const energyLabels = {1: 'Very low', 2: 'Low', 3: 'Medium', 4: 'High', 5: 'Very high'};

const maxDistanceKm = 5.0;
