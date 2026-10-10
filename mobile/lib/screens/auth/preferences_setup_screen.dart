import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/app_scope.dart';
import '../../models/profile_preferences.dart';
import '../../widgets/profile_preferences_form.dart';

/// Second sign-up step: the preferences that stay the same between quests.
/// (Difficulty, energy and distance are picked on the Quest page each time.)
/// Still part of the auth flow, so no bottom bar. Also shown after logging in
/// if the account has no preferences yet. Saving works offline (queued).
class PreferencesSetupScreen extends StatefulWidget {
  const PreferencesSetupScreen({super.key});

  @override
  State<PreferencesSetupScreen> createState() => _PreferencesSetupScreenState();
}

class _PreferencesSetupScreenState extends State<PreferencesSetupScreen> {
  final _preferences = ProfilePreferences();
  bool _saving = false;

  Future<void> _finish() async {
    setState(() => _saving = true);
    // Saved on the device right away; sent to the server now or once online.
    await AppScope.read(context).saveProfile(_preferences);
    if (!mounted) return;
    Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Set up your quests')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: ListView(
              key: const Key('preferences_setup_screen'),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
              children: [
                Text('What are you into?', style: theme.textTheme.headlineSmall),
                const SizedBox(height: 4),
                Text(
                  "We'll use this for every quest. You'll pick difficulty, energy and how far "
                  'to go each time you ask for one.',
                  style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
                ProfilePreferencesForm(
                  preferences: _preferences,
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 32),
                FilledButton(
                  key: const Key('finish_setup_button'),
                  onPressed: _preferences.hasInterest && !_saving ? _finish : null,
                  child: const Text('Start questing'),
                ),
                if (!_preferences.hasInterest)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      'Pick at least one interest to continue',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
