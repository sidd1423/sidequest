import 'package:flutter/material.dart';

import '../models/preference_options.dart';
import '../models/profile_preferences.dart';

/// The "set once" quest preferences: interests, accessibility and crowds.
/// Used by the sign-up preferences step and by Edit account. Minutes,
/// difficulty, energy, distance and who's with you are chosen per quest;
/// weather and what's around you come from your location for every quest.
///
/// Edits [preferences] in place and calls [onChanged] after every change.
class ProfilePreferencesForm extends StatefulWidget {
  const ProfilePreferencesForm({super.key, required this.preferences, this.onChanged});

  final ProfilePreferences preferences;
  final ValueChanged<ProfilePreferences>? onChanged;

  @override
  State<ProfilePreferencesForm> createState() => _ProfilePreferencesFormState();
}

class _ProfilePreferencesFormState extends State<ProfilePreferencesForm> {
  ProfilePreferences get _p => widget.preferences;

  void _update(VoidCallback change) {
    setState(change);
    widget.onChanged?.call(_p);
  }

  void _toggle(Set<String> set, String value, bool selected) =>
      _update(() => selected ? set.add(value) : set.remove(value));

  Widget _heading(BuildContext context, String title, [String? subtitle]) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.titleMedium),
          if (subtitle != null)
            Text(
              subtitle,
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
        ],
      ),
    );
  }

  Widget _multiChips(String keyPrefix, List<PreferenceOption> options, Set<String> selected) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final o in options)
          FilterChip(
            key: Key('${keyPrefix}_${o.value}'),
            label: Text(o.label),
            selected: selected.contains(o.value),
            onSelected: (on) => _toggle(selected, o.value, on),
          ),
      ],
    );
  }

  Widget _singleChips(String keyPrefix, List<PreferenceOption> options, String current, ValueChanged<String> onPick) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final o in options)
          ChoiceChip(
            key: Key('${keyPrefix}_${o.value}'),
            label: Text(o.label),
            selected: current == o.value,
            onSelected: (_) => _update(() => onPick(o.value)),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('profile_preferences_form'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _heading(context, 'Interests', 'Pick at least one'),
        _multiChips('interest', interestOptions, _p.interests),
        const SizedBox(height: 12),
        TextFormField(
          key: const Key('custom_interests'),
          initialValue: _p.customInterests,
          decoration: const InputDecoration(
            labelText: 'Anything else? (comma-separated)',
            hintText: 'e.g. birdwatching, skateboarding',
          ),
          onChanged: (v) => _update(() => _p.customInterests = v),
        ),

        _heading(context, 'Accessibility needs', 'Optional'),
        _multiChips('access', accessibilityOptions, _p.accessibility),
        const SizedBox(height: 12),
        TextFormField(
          initialValue: _p.accessibilityNotes,
          maxLines: 2,
          decoration: const InputDecoration(labelText: 'Anything else we should know?'),
          onChanged: (v) => _update(() => _p.accessibilityNotes = v),
        ),

        _heading(context, 'Crowds'),
        _singleChips('crowd', crowdOptions, _p.crowd, (v) => _p.crowd = v),

        const SizedBox(height: 24),
        const ListTile(
          key: Key('live_conditions_note'),
          contentPadding: EdgeInsets.zero,
          leading: Icon(Icons.my_location),
          title: Text('Weather and places nearby are automatic'),
          subtitle: Text('Each quest uses your location to check the weather right now and find real '
              'parks, paths and spots near you. You can type a place instead if location is off.'),
        ),
      ],
    );
  }
}
