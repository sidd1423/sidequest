import 'package:flutter/material.dart';

import '../../app_routes.dart';
import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../widgets/coming_soon.dart';

/// Account tab: profile summary, link to Edit account, Log out and Delete account.
class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  Future<void> _logOut(BuildContext context) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    final pending = state.pendingChanges;
    if (pending > 0) {
      // Logging out removes this account's data from the device.
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Log out?'),
          content: Text(
            '$pending change${pending == 1 ? " hasn't" : "s haven't"} synced yet and will be lost. '
            'Reconnect first to keep ${pending == 1 ? 'it' : 'them'}.',
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            TextButton(
              key: const Key('confirm_log_out'),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Log out anyway'),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    await state.logOut();
    navigator.pushNamedAndRemoveUntil(AppRoutes.login, (route) => false);
  }

  Future<void> _deleteAccount(BuildContext context) async {
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final deleted = await showDialog<bool>(context: context, builder: (_) => const _DeleteAccountDialog());
    if (deleted != true) return;
    navigator.pushNamedAndRemoveUntil(AppRoutes.login, (route) => false);
    messenger.showSnackBar(const SnackBar(content: Text('Your account and all its data were deleted.')));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final account = state.account;
    final pending = state.pendingChanges;
    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: ListView(
        key: const Key('account_screen'),
        padding: const EdgeInsets.all(16),
        children: [
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
                    Text(
                      account?.name.isNotEmpty == true ? account!.name : 'Your account',
                      key: const Key('account_name'),
                      style: theme.textTheme.titleLarge,
                    ),
                    Text(account?.email ?? '', key: const Key('account_email'), style: theme.textTheme.bodyMedium),
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
                  key: const Key('sync_tile'),
                  leading: Icon(state.isOnline ? Icons.cloud_done_outlined : Icons.cloud_off),
                  title: const Text('Sync'),
                  subtitle: Text(
                    state.isSyncing
                        ? 'Syncing...'
                        : pending > 0
                            ? '$pending change${pending == 1 ? '' : 's'} waiting to sync'
                            : state.isOnline
                                ? 'Everything is saved'
                                : 'Offline - using data saved on this device',
                  ),
                  trailing: const Icon(Icons.sync),
                  onTap: state.isSyncing ? null : () => state.sync(),
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
          const SizedBox(height: 32),
          TextButton.icon(
            key: const Key('delete_account_button'),
            style: TextButton.styleFrom(foregroundColor: theme.colorScheme.error),
            onPressed: () => _deleteAccount(context),
            icon: const Icon(Icons.delete_forever_outlined),
            label: const Text('Delete account'),
          ),
        ],
      ),
    );
  }
}

/// Asks for the password, then deletes the account on the server and this device.
class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  Future<void> _delete() async {
    if (_password.text.isEmpty) {
      setState(() => _error = 'Enter your password');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).deleteAccount(_password.text);
      if (mounted) Navigator.of(context).pop(true);
    } on OfflineException {
      if (mounted) setState(() => _error = 'Deleting your account needs a connection.');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.statusCode == 403 ? 'Wrong password' : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return AlertDialog(
      title: const Text('Delete your account?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'This permanently deletes your account, preferences, quests, ratings, notes and photos. '
            "It can't be undone.",
          ),
          const SizedBox(height: 16),
          TextField(
            key: const Key('delete_password'),
            controller: _password,
            obscureText: true,
            autofocus: true,
            decoration: InputDecoration(labelText: 'Password', errorText: _error),
            onSubmitted: (_) => _busy ? null : _delete(),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('confirm_delete_account'),
          style: FilledButton.styleFrom(backgroundColor: colors.error, foregroundColor: colors.onError),
          onPressed: _busy ? null : _delete,
          child: const Text('Delete forever'),
        ),
      ],
    );
  }
}
