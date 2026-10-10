import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import 'auth_scaffold.dart';

/// Sign up, step 1 of 2: creates the account (needs a connection).
/// Step 2 is [PreferencesSetupScreen].
class SignUpScreen extends StatefulWidget {
  const SignUpScreen({super.key});

  static const minPasswordLength = 8; // same as the backend

  @override
  State<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends State<SignUpScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_name, _email, _password, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _signUp() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).signUp(
        name: _name.text.trim(),
        email: _email.text.trim(),
        password: _password.text,
      );
      if (!mounted) return;
      // The account exists now, so Back shouldn't return to this form.
      Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.preferencesSetup, (route) => false);
    } on OfflineException catch (e) {
      setState(() => _error = '${e.message} Creating an account needs a connection.');
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _goToLogIn(BuildContext context) {
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop(); // came here from Log in
    } else {
      navigator.pushReplacementNamed(AppRoutes.login);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Create your account',
      subtitle: 'Quick 5-30 minute quests to get you outside.',
      showBack: Navigator.of(context).canPop(),
      children: [
        Form(
          key: _formKey,
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  key: const Key('sign_up_name'),
                  controller: _name,
                  textCapitalization: TextCapitalization.words,
                  autofillHints: const [AutofillHints.name],
                  textInputAction: TextInputAction.next,
                  maxLength: 80,
                  decoration: const InputDecoration(
                    labelText: 'Name',
                    prefixIcon: Icon(Icons.person_outline),
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('sign_up_email'),
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.email_outlined)),
                  validator: validateEmail,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('sign_up_password'),
                  controller: _password,
                  obscureText: true,
                  autofillHints: const [AutofillHints.newPassword],
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    helperText: 'At least ${SignUpScreen.minPasswordLength} characters',
                    prefixIcon: Icon(Icons.lock_outline),
                  ),
                  validator: (v) => (v == null || v.length < SignUpScreen.minPasswordLength)
                      ? 'Use at least ${SignUpScreen.minPasswordLength} characters'
                      : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('sign_up_confirm_password'),
                  controller: _confirm,
                  obscureText: true,
                  onFieldSubmitted: (_) => _busy ? null : _signUp(),
                  decoration: const InputDecoration(labelText: 'Confirm password', prefixIcon: Icon(Icons.lock_outline)),
                  validator: (v) => v != _password.text ? "Passwords don't match" : null,
                ),
              ],
            ),
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 16),
          AuthError(_error!, key: const Key('sign_up_error')),
        ],
        const SizedBox(height: 24),
        FilledButton(
          key: const Key('sign_up_button'),
          onPressed: _busy ? null : _signUp,
          child: _busy ? const ButtonSpinner() : const Text('Create account'),
        ),
        const SizedBox(height: 16),
        // Wrap (not Row) so this line wraps instead of overflowing on narrow
        // screens or with large text.
        Wrap(
          alignment: WrapAlignment.center,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            const Text('Already have an account?'),
            TextButton(
              key: const Key('go_to_log_in'),
              onPressed: () => _goToLogIn(context),
              child: const Text('Log in'),
            ),
          ],
        ),
      ],
    );
  }
}
