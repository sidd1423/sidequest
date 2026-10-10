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

FilledButton finishButton(WidgetTester tester) =>
    tester.widget<FilledButton>(find.byKey(const Key('finish_setup_button')));

FilledButton submitButton(WidgetTester tester) =>
    tester.widget<FilledButton>(find.byKey(const Key('submit_feedback_button')));

String timeSpentText(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(const Key('time_spent_field'))).controller!.text;

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

    testWidgets('Sign up -> choose interests -> opens the app', (tester) async {
      await tester.pumpWidget(const SidequestApp());
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));

      // Step 2: preferences - still an auth screen, so no bottom bar
      expect(find.byKey(const Key('preferences_setup_screen')), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
      // Difficulty, energy and distance are NOT set here (they're per quest)
      expect(find.text('Difficulty'), findsNothing);
      expect(find.textContaining('Energy'), findsNothing);
      expect(find.textContaining('How far'), findsNothing);

      // Can't finish without an interest
      expect(finishButton(tester).onPressed, isNull);
      await tapAndSettle(tester, find.byKey(const Key('interest_nature')));
      expect(finishButton(tester).onPressed, isNotNull);

      await tapAndSettle(tester, find.byKey(const Key('finish_setup_button')));
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
    });

    testWidgets('Back from the preferences step returns to Sign up', (tester) async {
      await tester.pumpWidget(const SidequestApp());
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Create your account'), findsOneWidget);
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

  });

  group('Quest page', () {
    testWidgets('per-quest settings are on the Quest page', (tester) async {
      await logIn(tester);
      for (final key in ['minutes_15', 'difficulty_easy', 'energy_slider', 'distance_slider']) {
        expect(find.byKey(Key(key)), findsOneWidget, reason: key);
      }
    });

    testWidgets('quest card only appears after tapping Generate', (tester) async {
      await logIn(tester);
      expect(find.byKey(const Key('quest_card')), findsNothing);
      expect(find.byKey(const Key('feedback_form')), findsNothing);

      await tapAndSettle(tester, find.byKey(const Key('minutes_10')));
      await tapAndSettle(tester, find.byKey(const Key('difficulty_challenging')));
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));

      expect(find.byKey(const Key('quest_card')), findsOneWidget);
      expect(find.byKey(const Key('feedback_form')), findsOneWidget);
      final card = find.byKey(const Key('quest_card'));
      expect(find.descendant(of: card, matching: find.text('10 min')), findsOneWidget);
      expect(find.descendant(of: card, matching: find.text('Challenging')), findsOneWidget);
    });

    testWidgets('rating a completed quest needs stars, then shows a summary', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));

      expect(submitButton(tester).onPressed, isNull); // completed + no rating
      expect(timeSpentText(tester), '15');

      await tapAndSettle(tester, find.byKey(const Key('star_4')));
      expect(submitButton(tester).onPressed, isNotNull);
      await tester.ensureVisible(find.byKey(const Key('feedback_comment')));
      await tester.enterText(find.byKey(const Key('feedback_comment')), 'great light');
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));

      expect(find.byKey(const Key('feedback_form')), findsNothing);
      final summary = find.byKey(const Key('feedback_summary'));
      expect(summary, findsOneWidget);
      expect(find.descendant(of: summary, matching: find.textContaining('★★★★')), findsOneWidget);
      expect(find.descendant(of: summary, matching: find.textContaining('great light')), findsOneWidget);
    });

    testWidgets("an unfinished quest can be sent with or without a rating", (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      await tapAndSettle(tester, find.byKey(const Key('outcome_not_finished')));

      expect(timeSpentText(tester), '0');
      expect(submitButton(tester).onPressed, isNotNull); // rating optional
      await tapAndSettle(tester, find.byKey(const Key('star_2')));
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));

      final summary = find.byKey(const Key('feedback_summary'));
      expect(find.descendant(of: summary, matching: find.textContaining("Didn't finish")), findsOneWidget);
      expect(find.descendant(of: summary, matching: find.textContaining('★★')), findsOneWidget);
    });

    testWidgets('Generate another shows a fresh card and rating form', (tester) async {
      await logIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      await tapAndSettle(tester, find.byKey(const Key('outcome_not_finished')));
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));
      expect(find.byKey(const Key('feedback_summary')), findsOneWidget);

      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('Sample Sidequest #2'), findsOneWidget);
      expect(find.byKey(const Key('feedback_form')), findsOneWidget);
      expect(find.byKey(const Key('feedback_summary')), findsNothing);
      expect(submitButton(tester).onPressed, isNull); // reset to "Completed it", no rating
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
