import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../widgets/coming_soon.dart';

/// Account tab: profile summary, link to Edit account, and Log out.
class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  void _logOut(BuildContext context) {
    // TODO: clear the session/token.
    Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.login, (route) => false);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: ListView(
        key: const Key('account_screen'),
        padding: const EdgeInsets.all(16),
        children: [
          const ComingSoonBanner(),
          const SizedBox(height: 16),
          Row(
            children: [
              CircleAvatar(
                radius: 32,
                backgroundColor: theme.colorScheme.primaryContainer,
                child: Icon(Icons.person, size: 32, color: theme.colorScheme.onPrimaryContainer),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Your name', style: theme.textTheme.titleLarge),
                    Text('you@example.com', style: theme.textTheme.bodyMedium),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Card(
            child: Column(
              children: [
                ListTile(
                  key: const Key('edit_account_tile'),
                  leading: const Icon(Icons.manage_accounts_outlined),
                  title: const Text('Edit account'),
                  subtitle: const Text('Name, email, password and quest preferences'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).pushNamed(AppRoutes.editAccount),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.notifications_outlined),
                  title: const Text('Notifications'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => showComingSoon(context, 'Notification settings'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            key: const Key('log_out_button'),
            onPressed: () => _logOut(context),
            icon: const Icon(Icons.logout),
            label: const Text('Log out'),
          ),
        ],
      ),
    );
  }
}
