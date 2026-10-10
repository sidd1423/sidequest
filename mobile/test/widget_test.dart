// Navigation tests for the Sidequest app outline. Run with: flutter test
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sidequest/main.dart';
import 'package:sidequest/screens/home_shell.dart';

Finder navItem(String label) =>
    find.descendant(of: find.byKey(const Key('bottom_nav')), matching: find.text(label));

int selectedTab(WidgetTester tester) =>
    tester.widget<NavigationBar>(find.byKey(const Key('bottom_nav'))).selectedIndex;

bool rootCanPop(WidgetTester tester) => tester.state<NavigatorState>(find.byType(Navigator).first).canPop();

Future<void> tapAndSettle(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> logIn(WidgetTester tester) async {
  await tester.pumpWidget(const SidequestApp());
  await tapAndSettle(tester, find.byKey(const Key('login_button')));
}

void main() {
  group('Auth screens (no bottom bar)', () {
    testWidgets('app opens on Log in without a bottom bar', (tester) async {
      await tester.pumpWidget(const SidequestApp());
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
    });

    testWidgets('Log in -> Sign up -> back to Log in', (tester) async {
      await tester.pumpWidget(const SidequestApp());
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      expect(find.text('Create your account'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);

      await tapAndSettle(tester, find.byKey(const Key('go_to_log_in')));
      expect(find.text('Welcome back'), findsOneWidget);
    });

    testWidgets('Log in opens the app and clears the auth screens from history', (tester) async {
      await logIn(tester);
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(find.byKey(const Key('quest_generator_screen')), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
    });

    testWidgets('Sign up opens the app', (tester) async {
      await tester.pumpWidget(const SidequestApp());
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
    });
  });

  group('Bottom bar (signed in)', () {
    testWidgets('switches between Quest, History and Account', (tester) async {
      await logIn(tester);
      expect(selectedTab(tester), 0);

      await tapAndSettle(tester, navItem('History'));
      expect(selectedTab(tester), 1);
      expect(find.byKey(const Key('quest_history_screen')), findsOneWidget);

      await tapAndSettle(tester, navItem('Account'));
      expect(selectedTab(tester), 2);
      expect(find.byKey(const Key('account_screen')), findsOneWidget);

      await tapAndSettle(tester, navItem('Quest'));
      expect(selectedTab(tester), 0);
      expect(find.byKey(const Key('generate_button')), findsOneWidget);
    });

    testWidgets('tabs can switch to another tab programmatically', (tester) async {
      await logIn(tester);
      tester.state<HomeShellState>(find.byType(HomeShell)).selectTab(HomeTab.account);
      await tester.pumpAndSettle();
      expect(selectedTab(tester), 2);
    });

    testWidgets('Generate button is a placeholder (shows "coming soon")', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('Quest generation is coming soon'), findsOneWidget);
    });
  });

  group('Pages opened from tabs', () {
    testWidgets('History -> quest detail -> back keeps the History tab', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, navItem('History'));
      await tapAndSettle(tester, find.byKey(const Key('history_quest_2')));

      expect(find.byKey(const Key('quest_detail_screen')), findsOneWidget);
      expect(find.text('Bench Bird Count'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);

      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(selectedTab(tester), 1);
    });

    testWidgets('Account -> Edit account -> Save returns to Account', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('edit_account_tile')));
      expect(find.byKey(const Key('edit_account_screen')), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);

      await tapAndSettle(tester, find.byKey(const Key('save_account_button')));
      expect(find.byKey(const Key('account_screen')), findsOneWidget);
      expect(selectedTab(tester), 2);
    });

    testWidgets('Log out returns to Log in and clears history', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('log_out_button')));
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
      expect(rootCanPop(tester), isFalse);
    });
  });
}
