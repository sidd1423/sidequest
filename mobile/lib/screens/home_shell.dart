import 'package:flutter/material.dart';

import '../data/app_scope.dart';
import '../widgets/sync_banner.dart';

import 'account/account_screen.dart';
import 'friends/friends_screen.dart';
import 'history/quest_history_screen.dart';
import 'quest/quest_generator_screen.dart';
import 'rewards/rewards_screen.dart';

/// The signed-in area: five tabs switched with the bottom navigation bar.
///
/// An [IndexedStack] keeps every tab alive, so each one keeps its scroll
/// position and state when you switch away and back.
///
/// Coming back to the app (resume) triggers a sync, so changes made offline
/// go out as soon as possible.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.initialTab = HomeTab.quest});

  final HomeTab initialTab;

  /// Lets a tab switch to another tab, e.g. History's "Get a quest" button.
  static HomeShellState? of(BuildContext context) => context.findAncestorStateOfType<HomeShellState>();

  @override
  State<HomeShell> createState() => HomeShellState();
}

enum HomeTab { quest, history, rewards, friends, account }

class HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  late int _index = widget.initialTab.index;

  void selectTab(HomeTab tab) => _select(tab.index);

  void _select(int index) {
    setState(() => _index = index);
    // Fresh points every time the Rewards tab opens.
    if (index == HomeTab.rewards.index) AppScope.read(context).loadRewards();
    if (index == HomeTab.friends.index) AppScope.read(context).loadFriends();
    if (index == HomeTab.quest.index) AppScope.read(context).loadParties();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) AppScope.read(context).sync();
  }

  @override
  Widget build(BuildContext context) {
    final requests = AppScope.of(context).incomingFriendRequests;
    final invites = AppScope.of(context).partyInvites;
    return Scaffold(
      body: Column(
        children: [
          const SyncBanner(),
          Expanded(
            // When the banner shows, it already sits under the status bar.
            child: MediaQuery.removePadding(
              context: context,
              removeTop: SyncBanner.isVisible(AppScope.of(context)),
              child: IndexedStack(
                index: _index,
                children: const [
                  QuestGeneratorScreen(),
                  QuestHistoryScreen(),
                  RewardsScreen(),
                  FriendsScreen(),
                  AccountScreen(),
                ],
              ),
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        key: const Key('bottom_nav'),
        selectedIndex: _index,
        onDestinationSelected: _select,
        destinations: [
          NavigationDestination(
            // Badge = group quest invites waiting for you.
            icon: Badge(
              key: const Key('quest_badge'),
              isLabelVisible: invites > 0,
              label: Text('$invites'),
              child: const Icon(Icons.explore_outlined),
            ),
            selectedIcon: Badge(
              isLabelVisible: invites > 0,
              label: Text('$invites'),
              child: const Icon(Icons.explore),
            ),
            label: 'Quest',
          ),
          const NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history),
            label: 'History',
          ),
          const NavigationDestination(
            icon: Icon(Icons.workspace_premium_outlined),
            selectedIcon: Icon(Icons.workspace_premium),
            label: 'Rewards',
          ),
          NavigationDestination(
            // Badge = friend requests waiting for you.
            icon: Badge(
              key: const Key('friends_badge'),
              isLabelVisible: requests > 0,
              label: Text('$requests'),
              child: const Icon(Icons.group_outlined),
            ),
            selectedIcon: const Icon(Icons.group),
            label: 'Friends',
          ),
          const NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Account',
          ),
        ],
      ),
    );
  }
}
