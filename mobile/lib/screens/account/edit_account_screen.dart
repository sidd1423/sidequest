import 'package:flutter/material.dart';

import '../../models/profile_preferences.dart';
import '../../widgets/coming_soon.dart';
import '../../widgets/profile_preferences_form.dart';

/// Edit account: profile details plus the same "set once" quest preferences
/// chosen at sign-up. Difficulty, energy and distance aren't here - they're
/// picked on the Quest page before each quest. Layout only (nothing is saved).
class EditAccountScreen extends StatefulWidget {
  const EditAccountScreen({super.key});

  @override
  State<EditAccountScreen> createState() => _EditAccountScreenState();
}

class _EditAccountScreenState extends State<EditAccountScreen> {
  // TODO: load the user's saved preferences instead of these placeholders.
  final _preferences = ProfilePreferences(interests: {'nature', 'photography'});

  void _save() {
    // TODO: PUT /users/{id}/preferences and update the profile.
    showComingSoon(context, 'Saving changes');
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Edit account'),
        actions: [
          TextButton(
            key: const Key('save_account_button'),
            onPressed: _preferences.hasInterest ? _save : null,
            child: const Text('Save'),
          ),
        ],
      ),
      body: ListView(
        key: const Key('edit_account_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          const ComingSoonBanner(),
          Padding(
            padding: const EdgeInsets.only(top: 24, bottom: 8),
            child: Text('Profile', style: theme.textTheme.titleMedium),
          ),
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
          ProfilePreferencesForm(
            preferences: _preferences,
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 32),
          FilledButton(
            key: const Key('save_account_bottom_button'),
            onPressed: _preferences.hasInterest ? _save : null,
            child: const Text('Save changes'),
          ),
        ],
      ),
    );
  }
}
