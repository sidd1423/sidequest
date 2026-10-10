import 'package:flutter/material.dart';

import '../../app_routes.dart';
import 'auth_scaffold.dart';

/// Log in. Placeholder: any input "logs you in" and opens the main app.
class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  void _logIn(BuildContext context) {
    // TODO: authenticate against the backend.
    // Clear the stack so Back can't return to the auth screens.
    Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Welcome back',
      subtitle: 'Log in to get your next sidequest.',
      children: [
        const TextField(
          key: Key('login_email'),
          keyboardType: TextInputType.emailAddress,
          autofillHints: [AutofillHints.email],
          decoration: InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.email_outlined)),
        ),
        const SizedBox(height: 16),
        const TextField(
          key: Key('login_password'),
          obscureText: true,
          autofillHints: [AutofillHints.password],
          decoration: InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline)),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Password reset is coming soon')),
            ),
            child: const Text('Forgot password?'),
          ),
        ),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('login_button'),
          onPressed: () => _logIn(context),
          child: const Text('Log in'),
        ),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text("Don't have an account?"),
            TextButton(
              key: const Key('go_to_sign_up'),
              onPressed: () => Navigator.of(context).pushNamed(AppRoutes.signUp),
              child: const Text('Sign up'),
            ),
          ],
        ),
      ],
    );
  }
}
