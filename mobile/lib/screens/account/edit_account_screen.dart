import 'package:flutter/material.dart';

import '../../widgets/coming_soon.dart';

/// Edit account: profile details plus the quest preferences that personalise
/// generation (mirrors the backend's preference model). Layout only.
class EditAccountScreen extends StatelessWidget {
  const EditAccountScreen({super.key});

  static const _interests = [
    'Outdoors', 'Nature', 'Art', 'Music', 'Food', 'History', 'Fitness', 'Photography',
    'Gaming', 'Learning', 'Social', 'Volunteering', 'Shopping', 'Nightlife', 'Wellness',
  ];

  void _save(BuildContext context) {
    // TODO: PUT /users/{id}/preferences and update the profile.
    showComingSoon(context, 'Saving changes');
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    Widget heading(String text) => Padding(
          padding: const EdgeInsets.only(top: 24, bottom: 8),
          child: Text(text, style: theme.textTheme.titleMedium),
        );

    return Scaffold(
      appBar: AppBar(
        title: const Text('Edit account'),
        actions: [
          TextButton(
            key: const Key('save_account_button'),
            onPressed: () => _save(context),
            child: const Text('Save'),
          ),
        ],
      ),
      body: ListView(
        key: const Key('edit_account_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          const ComingSoonBanner(),

          // --- Profile ----------------------------------------------------
          heading('Profile'),
          const TextField(decoration: InputDecoration(labelText: 'Name')),
          const SizedBox(height: 12),
          const TextField(
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(labelText: 'Email'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: () => showComingSoon(context, 'Changing your password'),
            child: const Text('Change password'),
          ),

          // --- Quest preferences -------------------------------------------
          heading('Interests'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final interest in _interests)
                FilterChip(
                  label: Text(interest),
                  selected: false,
                  onSelected: (_) => showComingSoon(context, 'Editing interests'),
                ),
            ],
          ),
          heading('Difficulty & energy'),
          const _PlaceholderRow(icon: Icons.terrain, text: 'Difficulty: easy · moderate · challenging · extreme'),
          const _PlaceholderRow(icon: Icons.bolt, text: 'Energy level right now: 1-5'),
          heading('Accessibility'),
          const _PlaceholderRow(icon: Icons.accessible, text: 'Wheelchair, step-free, rest stops, sensory-friendly...'),
          heading('Where you are'),
          const _PlaceholderRow(icon: Icons.location_city, text: 'Surroundings, how far you will go (0-5 km)'),
          const _PlaceholderRow(icon: Icons.groups_outlined, text: 'Crowd tolerance, who is coming'),
          heading('Weather'),
          const _PlaceholderRow(icon: Icons.thermostat, text: 'Conditions to avoid, comfortable temperature range'),
          const SizedBox(height: 32),
          FilledButton(
            key: const Key('save_account_bottom_button'),
            onPressed: () => _save(context),
            child: const Text('Save changes'),
          ),
        ],
      ),
    );
  }
}

class _PlaceholderRow extends StatelessWidget {
  const _PlaceholderRow({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon),
      title: Text(text),
    );
  }
}
