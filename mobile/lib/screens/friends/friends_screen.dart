import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../models/friends.dart';

/// Friends tab: your friends, requests waiting for you (accept / decline),
/// requests you sent (cancel), and "Add new friend" (by account email).
/// The list is cached for offline; changes need a connection.
class FriendsScreen extends StatelessWidget {
  const FriendsScreen({super.key});

  Future<void> _addFriend(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final message = await showDialog<String>(context: context, builder: (_) => const AddFriendDialog());
    if (message != null) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final data = state.friends;
    final text = Theme.of(context).textTheme;
    Widget heading(String label, String key) => Padding(
          padding: const EdgeInsets.only(top: 20, bottom: 4),
          child: Text(label, key: Key(key), style: text.titleMedium),
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Friends')),
      body: RefreshIndicator(
        onRefresh: state.loadFriends,
        child: ListView(
          key: const Key('friends_screen'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            FilledButton.icon(
              key: const Key('add_friend_button'),
              onPressed: () => _addFriend(context),
              icon: const Icon(Icons.person_add_alt_1),
              label: const Text('Add new friend'),
            ),
            if (data.incoming.isNotEmpty) ...[
              heading('Friend requests (${data.incoming.length})', 'incoming_heading'),
              for (final r in data.incoming) _IncomingTile(request: r),
            ],
            heading(
              data.friends.isEmpty ? 'Your friends' : 'Your friends (${data.friends.length})',
              'friends_heading',
            ),
            if (data.friends.isEmpty)
              const Padding(
                key: Key('no_friends'),
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('No friends yet. Tap "Add new friend" and enter the email they signed up with.'),
              ),
            for (final f in data.friends) _FriendTile(friend: f),
            if (data.outgoing.isNotEmpty) ...[
              heading('Waiting for them to accept', 'outgoing_heading'),
              for (final r in data.outgoing) _OutgoingTile(request: r),
            ],
          ],
        ),
      ),
    );
  }
}

/// Runs a friends action, showing a snackbar if it fails.
Future<void> _attempt(BuildContext context, Future<void> Function() action, {String? done}) async {
  final messenger = ScaffoldMessenger.of(context);
  String? message = done;
  try {
    await action();
  } on OfflineException {
    message = 'You need a connection to change friends.';
  } on ApiException catch (e) {
    message = e.message;
  }
  if (message != null) {
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.person});

  final Person person;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return CircleAvatar(
      backgroundColor: colors.secondaryContainer,
      foregroundColor: colors.onSecondaryContainer,
      child: Text(person.initial),
    );
  }
}

class _FriendTile extends StatelessWidget {
  const _FriendTile({required this.friend});

  final Friend friend;

  Future<void> _remove(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove ${friend.displayName}?'),
        content: const Text("You'll stop being friends. You can send a new request later."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(
            key: const Key('confirm_remove_friend'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    final state = AppScope.read(context);
    await _attempt(context, () => state.removeFriend(friend.userId), done: 'Removed ${friend.displayName}.');
  }

  @override
  Widget build(BuildContext context) {
    final stats = <String>[
      '${friend.questsThisWeek} ${friend.questsThisWeek == 1 ? 'quest' : 'quests'} this week',
      '${friend.minutesToday} min today',
      '🔥 ${friend.currentStreak} day streak',
    ];
    return ListTile(
      key: Key('friend_${friend.userId}'),
      contentPadding: EdgeInsets.zero,
      leading: _Avatar(person: friend),
      title: Text(friend.displayName),
      subtitle: Text(stats.join(' · '), key: Key('friend_stats_${friend.userId}')),
      trailing: PopupMenuButton<String>(
        key: Key('friend_menu_${friend.userId}'),
        tooltip: 'More',
        onSelected: (_) => _remove(context),
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'remove', key: Key('remove_friend'), child: Text('Remove friend')),
        ],
      ),
    );
  }
}

class _IncomingTile extends StatelessWidget {
  const _IncomingTile({required this.request});

  final FriendRequest request;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.read(context);
    final person = request.person;
    return Card(
      key: Key('incoming_${request.id}'),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: _Avatar(person: person),
              title: Text(person.displayName),
              subtitle: Text(person.name.trim().isEmpty ? 'wants to be friends' : '${person.email} · wants to be friends'),
            ),
            Wrap(
              spacing: 8,
              children: [
                FilledButton.tonal(
                  key: Key('accept_${request.id}'),
                  style: FilledButton.styleFrom(minimumSize: const Size(88, 40)),
                  onPressed: () => _attempt(context, () => state.respondToFriendRequest(request.id, accept: true),
                      done: 'You and ${person.displayName} are now friends!'),
                  child: const Text('Accept'),
                ),
                TextButton(
                  key: Key('decline_${request.id}'),
                  onPressed: () => _attempt(context, () => state.respondToFriendRequest(request.id, accept: false)),
                  child: const Text('Decline'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _OutgoingTile extends StatelessWidget {
  const _OutgoingTile({required this.request});

  final FriendRequest request;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.read(context);
    return ListTile(
      key: Key('outgoing_${request.id}'),
      contentPadding: EdgeInsets.zero,
      leading: _Avatar(person: request.person),
      title: Text(request.person.displayName),
      subtitle: const Text('Request sent'),
      trailing: TextButton(
        key: Key('cancel_request_${request.id}'),
        onPressed: () => _attempt(context, () => state.cancelFriendRequest(request.id)),
        child: const Text('Cancel'),
      ),
    );
  }
}

/// "Add new friend": enter the email on their account. Pops with a message
/// for the snackbar once the request is sent.
class AddFriendDialog extends StatefulWidget {
  const AddFriendDialog({super.key});

  @override
  State<AddFriendDialog> createState() => _AddFriendDialogState();
}

class _AddFriendDialogState extends State<AddFriendDialog> {
  final _email = TextEditingController();
  bool _sending = false;
  String? _error;

  static final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final email = _email.text.trim();
    if (!_emailPattern.hasMatch(email)) {
      setState(() => _error = 'Enter the email they use for Sidequest.');
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    final state = AppScope.read(context);
    try {
      final result = await state.sendFriendRequest(email);
      if (!mounted) return;
      Navigator.of(context).pop(result.nowFriends
          ? 'You and ${result.person.displayName} are now friends!'
          : 'Friend request sent to ${result.person.displayName}.');
    } on OfflineException {
      if (mounted) setState(() => _error = 'Sending a friend request needs a connection.');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const Key('add_friend_dialog'),
      title: const Text('Add new friend'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("Enter the email on their Sidequest account. They'll need to accept."),
          const SizedBox(height: 12),
          TextField(
            key: const Key('friend_email_field'),
            controller: _email,
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            textInputAction: TextInputAction.send,
            onSubmitted: (_) => _sending ? null : _send(),
            decoration: InputDecoration(labelText: 'Email', errorText: _error, errorMaxLines: 3),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: _sending ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          key: const Key('send_friend_request'),
          style: FilledButton.styleFrom(minimumSize: const Size(88, 40)),
          onPressed: _sending ? null : _send,
          child: _sending
              ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Send request'),
        ),
      ],
    );
  }
}
