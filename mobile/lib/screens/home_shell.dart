import 'package:flutter/material.dart';

import 'account/account_screen.dart';
import 'history/quest_history_screen.dart';
import 'quest/quest_generator_screen.dart';

/// The signed-in area: three tabs switched with the bottom navigation bar.
///
/// An [IndexedStack] keeps every tab alive, so each one keeps its scroll
/// position and state when you switch away and back.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.initialTab = HomeTab.quest});

  final HomeTab initialTab;

  /// Lets a tab switch to another tab, e.g. History's "Get a quest" button.
  static HomeShellState? of(BuildContext context) => context.findAncestorStateOfType<HomeShellState>();

  @override
  State<HomeShell> createState() => HomeShellState();
}

enum HomeTab { quest, history, account }

class HomeShellState extends State<HomeShell> {
  late int _index = widget.initialTab.index;

  void selectTab(HomeTab tab) => setState(() => _index = tab.index);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: const [
          QuestGeneratorScreen(),
          QuestHistoryScreen(),
          AccountScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        key: const Key('bottom_nav'),
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.explore_outlined),
            selectedIcon: Icon(Icons.explore),
            label: 'Quest',
          ),
          NavigationDestination(
            icon: Icon(Icons.history_outlined),
            selectedIcon: Icon(Icons.history),
            label: 'History',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Account',
          ),
        ],
      ),
    );
  }
}
