import 'package:flutter/material.dart';

import '../../data/api_client.dart';
import '../../data/app_scope.dart';
import '../../models/generated_quest.dart';
import '../../models/party.dart';
import '../home_shell.dart';

/// "Quest with friends" on the Quest tab:
/// - Invite friends (picked from your friends list) with this quest's settings.
/// - Invites you got: Join / Decline.
/// - Group quests you host: who's in, Start (Gemma makes ONE quest for
///   everyone who joined) or Cancel.
/// Once it starts, the quest shows up as your quest on this screen.
class PartySection extends StatefulWidget {
  const PartySection({super.key, required this.settings});

  /// This quest's settings as picked on the Quest tab (used for new invites).
  final QuestSettings Function() settings;

  @override
  State<PartySection> createState() => _PartySectionState();
}

class _PartySectionState extends State<PartySection> {
  final _busy = <int>{}; // parties with a request in flight
  bool _inviting = false;

  Future<void> _run(Future<void> Function() action, {int? partyId, String? done}) async {
    final messenger = ScaffoldMessenger.of(context);
    void setBusy(bool on) {
      if (partyId == null) {
        _inviting = on;
      } else if (on) {
        _busy.add(partyId);
      } else {
        _busy.remove(partyId);
      }
    }

    setState(() => setBusy(true));
    String? message = done;
    try {
      await action();
    } on OfflineException {
      message = 'Group quests need a connection.';
    } on ApiException catch (e) {
      message = e.message;
    } finally {
      if (mounted) setState(() => setBusy(false));
    }
    if (message != null) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _invite() async {
    final state = AppScope.read(context);
    final shell = HomeShell.of(context); // the dialog sits above HomeShell, so look it up here
    final picked = await showDialog<List<String>>(
      context: context,
      builder: (_) => InviteFriendsDialog(onGoToFriends: () => shell?.selectTab(HomeTab.friends)),
    );
    if (picked == null || picked.isEmpty || !mounted) return;
    await _run(
      () => state.createParty(picked, widget.settings()),
      done: 'Invites sent! Start the quest once someone joins.',
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    // Started ones you're in are already your quest; still-open ones and late invites show here.
    final visible = state.parties.where((p) => p.isOpen || p.isInvite).toList();
    return Column(
      key: const Key('party_section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(child: Text('Quest with friends', style: text.titleMedium)),
            IconButton(
              key: const Key('refresh_parties'),
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh),
              onPressed: state.loadParties,
            ),
          ],
        ),
        for (final p in visible)
          _PartyCard(
            party: p,
            busy: _busy.contains(p.id),
            onJoin: () => _run(() => state.joinParty(p.id), partyId: p.id,
                done: p.isOpen ? "You're in! ${p.hostName} will start it soon." : null),
            onDecline: () => _run(() => state.declineParty(p.id), partyId: p.id),
            onStart: () => _run(() => state.startParty(p.id), partyId: p.id, done: 'Group quest started!'),
            onCancel: () => _run(() => state.cancelParty(p.id), partyId: p.id),
          ),
        const SizedBox(height: 4),
        OutlinedButton.icon(
          key: const Key('invite_friends_button'),
          onPressed: _inviting ? null : _invite,
          icon: _inviting
              ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.group_add_outlined),
          label: const Text('Invite friends to a group quest'),
        ),
      ],
    );
  }
}

class _PartyCard extends StatelessWidget {
  const _PartyCard({
    required this.party,
    required this.busy,
    required this.onJoin,
    required this.onDecline,
    required this.onStart,
    required this.onCancel,
  });

  final Party party;
  final bool busy;
  final VoidCallback onJoin;
  final VoidCallback onDecline;
  final VoidCallback onStart;
  final VoidCallback onCancel;

  static final _small = ButtonStyle(minimumSize: WidgetStateProperty.all(const Size(88, 40)));

  @override
  Widget build(BuildContext context) {
    final p = party;
    final colors = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final String title;
    final String subtitle;
    if (p.isHost) {
      title = 'Your group quest';
      subtitle = p.canStart
          ? '${p.joined} people in. Start when everyone is ready.'
          : 'Waiting for friends to join...';
    } else if (p.isInvite) {
      title = '${p.hostName} invited you to a group quest';
      subtitle = p.isOpen
          ? 'Join, and you\'ll all get the same quest when ${p.hostName} starts it.'
          : 'Already started: ${p.questTitle ?? 'a quest'}. Join to get it too.';
    } else {
      title = "You're in ${p.hostName}'s group quest";
      subtitle = 'Waiting for ${p.hostName} to start it...';
    }
    return Card(
      key: Key('party_${p.id}'),
      color: p.isInvite ? colors.secondaryContainer : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.groups_outlined),
                const SizedBox(width: 8),
                Expanded(child: Text(title, style: text.titleSmall)),
              ],
            ),
            const SizedBox(height: 4),
            Text(subtitle, key: Key('party_status_${p.id}')),
            const SizedBox(height: 8),
            PartyMembers(members: p.members),
            const SizedBox(height: 8),
            if (busy)
              Row(
                children: [
                  const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                  const SizedBox(width: 8),
                  Text(p.isHost ? 'Asking Gemma for a quest for ${p.joined}... (10-60 s)' : 'One moment...'),
                ],
              )
            else
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (p.isHost) ...[
                    FilledButton.icon(
                      key: Key('start_party_${p.id}'),
                      style: _small,
                      onPressed: p.canStart ? onStart : null,
                      icon: const Icon(Icons.play_arrow),
                      label: Text('Start for ${p.joined}'),
                    ),
                    TextButton(key: Key('cancel_party_${p.id}'), onPressed: onCancel, child: const Text('Cancel')),
                  ],
                  if (p.isInvite) ...[
                    FilledButton(key: Key('join_party_${p.id}'), style: _small, onPressed: onJoin, child: const Text('Join')),
                    TextButton(key: Key('decline_party_${p.id}'), onPressed: onDecline, child: const Text('Decline')),
                  ],
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// Who's in a group quest: joined ✓, invited ⏳, declined ✕.
class PartyMembers extends StatelessWidget {
  const PartyMembers({super.key, required this.members});

  final List<PartyMember> members;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final m in members)
          Chip(
            key: Key('member_${m.userId}_${m.status}'),
            visualDensity: VisualDensity.compact,
            avatar: Icon(
              m.status == 'joined'
                  ? Icons.check_circle
                  : m.status == 'declined'
                      ? Icons.cancel_outlined
                      : Icons.hourglass_empty,
              size: 18,
              color: m.status == 'joined' ? colors.primary : colors.outline,
            ),
            label: Text(m.isHost ? '${m.name} (host)' : m.name),
          ),
      ],
    );
  }
}

/// Pick friends for a group quest. Pops with their user ids.
class InviteFriendsDialog extends StatefulWidget {
  const InviteFriendsDialog({super.key, this.onGoToFriends});

  /// Shown when you have no friends yet.
  final VoidCallback? onGoToFriends;

  @override
  State<InviteFriendsDialog> createState() => _InviteFriendsDialogState();
}

class _InviteFriendsDialogState extends State<InviteFriendsDialog> {
  final _picked = <String>{};

  @override
  Widget build(BuildContext context) {
    final friends = AppScope.of(context).friends.friends;
    return AlertDialog(
      key: const Key('invite_friends_dialog'),
      title: const Text('Invite friends'),
      content: SizedBox(
        width: 360,
        child: friends.isEmpty
            ? Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Add friends first - then you can do quests together.'),
                  const SizedBox(height: 8),
                  TextButton(
                    key: const Key('go_to_friends'),
                    onPressed: () {
                      Navigator.of(context).pop();
                      widget.onGoToFriends?.call();
                    },
                    child: const Text('Go to Friends'),
                  ),
                ],
              )
            : SingleChildScrollView(
                child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text("Everyone who joins gets the same quest, made for the whole group."),
                  for (final f in friends)
                    CheckboxListTile(
                      key: Key('invite_${f.userId}'),
                      contentPadding: EdgeInsets.zero,
                      value: _picked.contains(f.userId),
                      title: Text(f.displayName),
                      onChanged: (on) => setState(() {
                        if (on == true) {
                          _picked.add(f.userId);
                        } else {
                          _picked.remove(f.userId);
                        }
                      }),
                    ),
                ],
              ),
              ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        if (friends.isNotEmpty)
          FilledButton(
            key: const Key('send_party_invites'),
            style: FilledButton.styleFrom(minimumSize: const Size(88, 40)),
            onPressed: _picked.isEmpty ? null : () => Navigator.of(context).pop(_picked.toList()),
            child: Text(_picked.length <= 1 ? 'Send invite' : 'Send ${_picked.length} invites'),
          ),
      ],
    );
  }
}
