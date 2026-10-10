import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../models/profile_preferences.dart';
import '../../widgets/coming_soon.dart';
import '../../widgets/profile_preferences_form.dart';
import '../auth/auth_scaffold.dart' show AuthError, validateEmail;

/// Edit account: name/email plus the same "set once" quest preferences chosen
/// at sign-up. Difficulty, energy and distance aren't here - they're picked on
/// the Quest page before each quest.
///
/// Preferences save offline (queued until online); name/email changes need a
/// connection.
class EditAccountScreen extends StatefulWidget {
  const EditAccountScreen({super.key});

  @override
  State<EditAccountScreen> createState() => _EditAccountScreenState();
}

class _EditAccountScreenState extends State<EditAccountScreen> {
  final _formKey = GlobalKey<FormState>();
  late final ProfilePreferences _preferences;
  late final TextEditingController _name;
  late final TextEditingController _email;
  bool _saving = false;
  String? _error;
  bool _loaded = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loaded) return;
    _loaded = true;
    final state = AppScope.read(context);
    // Edit a copy, so Back without saving changes nothing.
    _preferences = state.profile?.copy() ?? ProfilePreferences();
    _name = TextEditingController(text: state.account?.name ?? '');
    _email = TextEditingController(text: state.account?.email ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _saving = true;
      _error = null;
    });
    await state.saveProfile(_preferences); // always works - queued if offline
    try {
      await state.updateAccount(name: _name.text, email: _email.text);
    } on OfflineException {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = 'Preferences saved. Changing your name or email needs a connection - try again when online.';
      });
      return;
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = e.message;
      });
      return;
    }
    messenger.showSnackBar(SnackBar(
      content: Text(state.isOnline ? 'Saved' : "Saved on this device - it'll sync when you're online"),
    ));
    navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final canSave = _preferences.hasInterest && !_saving;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Edit account'),
        actions: [
          TextButton(
            key: const Key('save_account_button'),
            onPressed: canSave ? _save : null,
            child: const Text('Save'),
          ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          key: const Key('edit_account_screen'),
          padding: const EdgeInsets.all(16),
          children: [
            if (_error != null) AuthError(_error!, key: const Key('edit_account_error')),
            Padding(
              padding: const EdgeInsets.only(top: 8, bottom: 8),
              child: Text('Profile', style: theme.textTheme.titleMedium),
            ),
            TextFormField(
              key: const Key('edit_name'),
              controller: _name,
              maxLength: 80,
              decoration: const InputDecoration(labelText: 'Name', counterText: ''),
            ),
            const SizedBox(height: 12),
            TextFormField(
              key: const Key('edit_email'),
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Email'),
              validator: validateEmail,
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
              onPressed: canSave ? _save : null,
              child: const Text('Save changes'),
            ),
          ],
        ),
      ),
    );
  }
}
