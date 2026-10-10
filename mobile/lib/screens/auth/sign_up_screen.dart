import 'package:flutter/material.dart';

import '../../app_routes.dart';
import 'auth_scaffold.dart';

/// Sign up. Placeholder: "creating an account" just opens the main app.
class SignUpScreen extends StatelessWidget {
  const SignUpScreen({super.key});

  void _signUp(BuildContext context) {
    // TODO: create the account, then send the user to set their quest preferences.
    Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
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
        const TextField(
          key: Key('sign_up_name'),
          textCapitalization: TextCapitalization.words,
          autofillHints: [AutofillHints.name],
          decoration: InputDecoration(labelText: 'Name', prefixIcon: Icon(Icons.person_outline)),
        ),
        const SizedBox(height: 16),
        const TextField(
          key: Key('sign_up_email'),
          keyboardType: TextInputType.emailAddress,
          autofillHints: [AutofillHints.email],
          decoration: InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.email_outlined)),
        ),
        const SizedBox(height: 16),
        const TextField(
          key: Key('sign_up_password'),
          obscureText: true,
          autofillHints: [AutofillHints.newPassword],
          decoration: InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline)),
        ),
        const SizedBox(height: 16),
        const TextField(
          key: Key('sign_up_confirm_password'),
          obscureText: true,
          decoration: InputDecoration(labelText: 'Confirm password', prefixIcon: Icon(Icons.lock_outline)),
        ),
        const SizedBox(height: 24),
        FilledButton(
          key: const Key('sign_up_button'),
          onPressed: () => _signUp(context),
          child: const Text('Create account'),
        ),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
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
