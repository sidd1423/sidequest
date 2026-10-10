import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import 'auth_scaffold.dart';

/// Log in with email + password. Needs a connection; after that the session
/// is saved on the device and the app works offline.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Session expired? Pre-fill the email.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final account = AppScope.read(context).account;
      if (account != null && _email.text.isEmpty) _email.text = account.email;
    });
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _logIn() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final state = AppScope.read(context);
    try {
      await state.logIn(email: _email.text.trim(), password: _password.text);
      if (!mounted) return;
      // Clear the stack so Back can't return to the auth screens.
      Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.afterLogin(state), (route) => false);
    } on OfflineException catch (e) {
      setState(() => _error = '${e.message} Logging in needs a connection.');
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AuthScaffold(
      title: 'Welcome back',
      subtitle: 'Log in to get your next sidequest.',
      children: [
        Form(
          key: _formKey,
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  key: const Key('login_email'),
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.email_outlined)),
                  validator: validateEmail,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('login_password'),
                  controller: _password,
                  obscureText: true,
                  autofillHints: const [AutofillHints.password],
                  onFieldSubmitted: (_) => _busy ? null : _logIn(),
                  decoration: const InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline)),
                  validator: (v) => (v == null || v.isEmpty) ? 'Enter your password' : null,
                ),
              ],
            ),
          ),
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
        if (_error != null) AuthError(_error!, key: const Key('login_error')),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('login_button'),
          onPressed: _busy ? null : _logIn,
          child: _busy ? const ButtonSpinner() : const Text('Log in'),
        ),
        const SizedBox(height: 16),
        // Wrap (not Row) so this line wraps instead of overflowing on narrow
        // screens or with large text.
        Wrap(
          alignment: WrapAlignment.center,
          crossAxisAlignment: WrapCrossAlignment.center,
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
