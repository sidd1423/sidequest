// Widget tests for the Sidequest app: auth, offline cache + sync, and the
// screens, against an in-memory fake backend (test/fake_backend.dart).
// Run with: flutter test
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sidequest/data/api_client.dart';
import 'package:sidequest/data/app_state.dart';
import 'package:sidequest/data/key_value_store.dart';
import 'package:sidequest/main.dart';
import 'package:sidequest/models/generated_quest.dart';
import 'package:sidequest/screens/home_shell.dart';
import 'package:sidequest/widgets/quest_journal.dart';

import 'fake_backend.dart';

late FakeBackend backend;
late MemoryStore cache;
late MemoryStore secure;

AppState newState() => AppState(
      api: ApiClient(baseUrl: 'http://test', httpClient: backend.client),
      cache: cache,
      secure: secure,
    );

/// The default test screen is 800x600, and ListView only builds items near the
/// screen - so widgets further down a page "don't exist" for finders. A tall
/// screen builds every item on our pages.
void useTallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 5000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Start the app like main() does: restore from the device, then show it.
Future<AppState> startApp(WidgetTester tester) async {
  useTallScreen(tester);
  final state = newState();
  await state.restore();
  await tester.pumpWidget(SidequestApp(state: state));
  await tester.pumpAndSettle();
  return state;
}

/// A returning user already logged in on this device.
Future<AppState> startLoggedIn(WidgetTester tester, {bool withPrefs = true, int quests = 0}) async {
  useTallScreen(tester);
  final user = backend.addUser(prefs: withPrefs ? Map.of(savedPrefs) : null);
  for (var i = 0; i < quests; i++) {
    backend.addQuest(user['id'] as String, title: i == 0 ? 'Bench Bird Count' : 'Quest $i');
  }
  await secure.write('session', jsonEncode(backend.sessionFor(user['id'] as String)));
  final state = newState();
  await state.restore();
  await state.sync(); // like main(): pull the profile + quests into the device cache
  await tester.pumpWidget(SidequestApp(state: state));
  await tester.pumpAndSettle();
  return state;
}

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

/// A real 1x1 PNG, so image decoding in the photo test doesn't error.
final tinyPng = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=');

String counter(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('completed_count'))).data!;

Future<void> tapAndSettle(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> enter(WidgetTester tester, String key, String text) async {
  final finder = find.byKey(Key(key));
  await tester.ensureVisible(finder);
  await tester.enterText(finder, text);
}

Future<void> fillSignUp(WidgetTester tester, {String email = 'new@example.com', String confirm = 'longpassword'}) async {
  await enter(tester, 'sign_up_name', 'Gowtham');
  await enter(tester, 'sign_up_email', email);
  await enter(tester, 'sign_up_password', 'longpassword');
  await enter(tester, 'sign_up_confirm_password', confirm);
}

Future<void> logInWith(WidgetTester tester, String email, String password) async {
  await enter(tester, 'login_email', email);
  await enter(tester, 'login_password', password);
  await tapAndSettle(tester, find.byKey(const Key('login_button')));
}

void main() {
  setUp(() {
    backend = FakeBackend();
    cache = MemoryStore();
    secure = MemoryStore();
  });

  group('Sign up & log in', () {
    testWidgets('opens on Log in without a bottom bar when nobody is logged in', (tester) async {
      await startApp(tester);
      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
    });

    testWidgets('Log in -> Sign up -> back to Log in', (tester) async {
      await startApp(tester);
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      expect(find.text('Create your account'), findsOneWidget);
      await tapAndSettle(tester, find.byKey(const Key('go_to_log_in')));
      expect(find.text('Welcome back'), findsOneWidget);
    });

    testWidgets('sign-up form is checked before anything is sent', (tester) async {
      await startApp(tester);
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await fillSignUp(tester, confirm: 'different');
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));
      expect(find.text("Passwords don't match"), findsOneWidget);
      expect(backend.requests, isEmpty);
    });

    testWidgets('sign up -> pick interests -> app; account, token and preferences saved', (tester) async {
      final state = await startApp(tester);
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await fillSignUp(tester);
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));

      // Step 2: preferences - no bottom bar, no per-quest settings
      expect(find.byKey(const Key('preferences_setup_screen')), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
      expect(find.text('Difficulty'), findsNothing);
      expect(find.textContaining('Energy'), findsNothing);
      expect(find.textContaining("Who's"), findsNothing); // asked before each quest instead
      expect(rootCanPop(tester), isFalse); // the account exists - no going back to the form
      expect(backend.users.values.single['email'], 'new@example.com');
      expect(secure.values['session'], isNotNull); // token kept on the device

      expect(finishButton(tester).onPressed, isNull);
      await tapAndSettle(tester, find.byKey(const Key('interest_nature')));
      await tapAndSettle(tester, find.byKey(const Key('finish_setup_button')));

      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
      final userId = state.account!.id;
      expect(backend.preferences[userId]!['interests'], ['nature']);
      expect(state.pendingChanges, 0);
    });

    testWidgets('signing up with a taken email shows the server message', (tester) async {
      backend.addUser(email: 'new@example.com');
      await startApp(tester);
      await tapAndSettle(tester, find.byKey(const Key('go_to_sign_up')));
      await fillSignUp(tester);
      await tapAndSettle(tester, find.byKey(const Key('sign_up_button')));
      expect(find.text('An account with this email already exists'), findsOneWidget);
      expect(find.byKey(const Key('preferences_setup_screen')), findsNothing);
    });

    testWidgets('wrong password shows an error', (tester) async {
      backend.addUser();
      await startApp(tester);
      await logInWith(tester, 'gowtham@example.com', 'wrong password');
      expect(find.text('Wrong email or password'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
    });

    testWidgets('log in goes home and loads the profile + history from the server', (tester) async {
      final user = backend.addUser(prefs: Map.of(savedPrefs));
      backend.addQuest(user['id'] as String);
      final state = await startApp(tester);
      await logInWith(tester, 'Gowtham@Example.com', 'correct horse');

      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
      expect(state.profile!.interests, {'nature'});
      expect(state.quests.single.title, 'Bench Bird Count');
    });

    testWidgets('log in without saved preferences asks for them first', (tester) async {
      backend.addUser();
      await startApp(tester);
      await logInWith(tester, 'gowtham@example.com', 'correct horse');
      expect(find.byKey(const Key('preferences_setup_screen')), findsOneWidget);
    });

    testWidgets('logging in needs a connection', (tester) async {
      backend.addUser();
      backend.online = false;
      await startApp(tester);
      await logInWith(tester, 'gowtham@example.com', 'correct horse');
      expect(find.byKey(const Key('login_error')), findsOneWidget);
      expect(find.textContaining('needs a connection'), findsOneWidget);
    });
  });

  group('Offline', () {
    testWidgets('a saved session opens straight into the app with cached data, even offline', (tester) async {
      // First run online: logged in, history cached on the device.
      await startLoggedIn(tester, quests: 2);
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);

      // Next launch: no connection.
      await tester.pumpWidget(const SizedBox());
      backend.online = false;
      final state = await startApp(tester);
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(state.quests, hasLength(2));
      await state.sync();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('offline_banner')), findsOneWidget);

      await tapAndSettle(tester, navItem('History'));
      expect(find.text('Bench Bird Count'), findsOneWidget);
    });

    testWidgets('generating a quest offline explains it needs a connection', (tester) async {
      await startLoggedIn(tester);
      backend.online = false;
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.byKey(const Key('generate_error')), findsOneWidget);
      expect(find.byKey(const Key('quest_card')), findsNothing);
    });

    testWidgets('rating offline is queued and sent when back online', (tester) async {
      final state = await startLoggedIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      final questId = state.quests.first.id;

      backend.online = false;
      await tapAndSettle(tester, find.byKey(const Key('star_5')));
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));
      expect(state.pendingChanges, 1);
      expect(find.byKey(const Key('quest_card')), findsNothing); // completed -> off the Quest screen
      expect(counter(tester), '1'); // counted right away, even offline
      expect(find.byKey(const Key('offline_banner')), findsOneWidget);
      expect(find.textContaining('1 change will sync'), findsOneWidget);
      expect(state.quests.first.feedbackPending, isTrue);
      expect(jsonDecode(cache.values['outbox:${state.account!.id}']!), hasLength(1)); // survives restarts

      backend.online = true;
      await tapAndSettle(tester, find.text('Retry'));
      expect(state.pendingChanges, 0);
      expect(find.byKey(const Key('offline_banner')), findsNothing);
      final serverQuest = backend.quests[state.account!.id]!.firstWhere((q) => q['id'] == questId);
      expect(serverQuest['feedback']['rating'], 5);
      expect(serverQuest['status'], 'completed');
    });

    testWidgets('editing preferences offline saves locally and syncs later', (tester) async {
      final state = await startLoggedIn(tester);
      backend.online = false;
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('edit_account_tile')));
      await tapAndSettle(tester, find.byKey(const Key('interest_art')));
      await tapAndSettle(tester, find.byKey(const Key('save_account_button')));

      expect(state.profile!.interests, containsAll(['nature', 'art']));
      expect(state.pendingChanges, 1);
      expect(backend.preferences[state.account!.id]!['interests'], ['nature']);

      backend.online = true;
      await state.sync();
      await tester.pumpAndSettle();
      expect(backend.preferences[state.account!.id]!['interests'], containsAll(['nature', 'art']));
      // per-quest defaults saved elsewhere aren't wiped
      expect(backend.preferences[state.account!.id]!['difficulty'], 'easy');
      expect((backend.preferences[state.account!.id]!['environment'] as Map<String, dynamic>)['group_size'], 'solo');
    });

    testWidgets('an expired session keeps local data and asks to log in again', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      backend.sessions.clear(); // revoked on the server
      await state.sync();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('session_expired_banner')), findsOneWidget);
      expect(state.quests, hasLength(1));

      await tapAndSettle(tester, find.byKey(const Key('session_expired_log_in')));
      expect(find.text('Welcome back'), findsOneWidget);
      await enter(tester, 'login_password', 'correct horse'); // email is pre-filled
      await tapAndSettle(tester, find.byKey(const Key('login_button')));
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(find.byKey(const Key('session_expired_banner')), findsNothing);
    });
  });

  group('Bottom bar (signed in)', () {
    testWidgets('switches between Quest, History and Account', (tester) async {
      await startLoggedIn(tester, quests: 1);
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
      await startLoggedIn(tester);
      tester.state<HomeShellState>(find.byType(HomeShell)).selectTab(HomeTab.account);
      await tester.pumpAndSettle();
      expect(selectedTab(tester), 2);
    });

    testWidgets('empty history links to the Quest tab', (tester) async {
      await startLoggedIn(tester);
      await tapAndSettle(tester, navItem('History'));
      await tapAndSettle(tester, find.byKey(const Key('empty_history_get_quest')));
      expect(selectedTab(tester), 0);
    });
  });

  group('Quest page', () {
    testWidgets('per-quest settings are on the Quest page', (tester) async {
      await startLoggedIn(tester);
      for (final key in ['minutes_15', 'group_solo', 'difficulty_easy', 'energy_slider', 'distance_slider']) {
        expect(find.byKey(Key(key)), findsOneWidget, reason: key);
      }
    });

    testWidgets('quest card only appears after Generate, with the chosen settings sent', (tester) async {
      await startLoggedIn(tester);
      expect(find.byKey(const Key('quest_card')), findsNothing);
      expect(find.byKey(const Key('feedback_form')), findsNothing);

      await tapAndSettle(tester, find.byKey(const Key('minutes_10')));
      await tapAndSettle(tester, find.byKey(const Key('group_pair')));
      await tapAndSettle(tester, find.byKey(const Key('difficulty_challenging')));
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));

      expect(backend.lastQuestSettings, {
        'duration_minutes': 10,
        'difficulty': 'challenging',
        'energy_level': 3,
        'max_travel_km': 1.0,
        'group_size': 'pair',
      });
      final card = find.byKey(const Key('quest_card'));
      expect(card, findsOneWidget);
      expect(find.byKey(const Key('feedback_form')), findsOneWidget);
      expect(find.descendant(of: card, matching: find.text('10 min')), findsOneWidget);
      expect(find.descendant(of: card, matching: find.text('Challenging')), findsOneWidget);
      expect(find.descendant(of: card, matching: find.text('≤ 1.0 km')), findsOneWidget);
    });

    testWidgets('completing a quest needs stars, removes it from the Quest screen and counts it', (tester) async {
      final state = await startLoggedIn(tester);
      expect(counter(tester), '0');
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));

      expect(submitButton(tester).onPressed, isNull); // completed + no rating
      expect(timeSpentText(tester), '15');

      await tapAndSettle(tester, find.byKey(const Key('star_4')));
      expect(submitButton(tester).onPressed, isNotNull);
      await enter(tester, 'feedback_comment', 'great light');
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));

      expect(find.byKey(const Key('quest_card')), findsNothing);
      expect(find.byKey(const Key('feedback_form')), findsNothing);
      expect(find.textContaining('Quest complete!'), findsOneWidget);
      expect(counter(tester), '1');
      expect(find.text('Generate sidequest'), findsOneWidget); // back to the start
      expect(state.pendingChanges, 0);
      expect(backend.quests[state.account!.id]!.first['status'], 'completed');
      expect(backend.quests[state.account!.id]!.first['feedback']['comment'], 'great light');
    });

    testWidgets('an unfinished quest can be sent with or without a rating', (tester) async {
      await startLoggedIn(tester);
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
      await startLoggedIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('Quest #1'), findsOneWidget);
      await tapAndSettle(tester, find.byKey(const Key('outcome_not_finished')));
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));

      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('Quest #2'), findsOneWidget);
      expect(find.byKey(const Key('feedback_form')), findsOneWidget);
      expect(find.byKey(const Key('feedback_summary')), findsNothing);
      expect(submitButton(tester).onPressed, isNull); // reset to "Completed it", no rating
    });
  });

  group('Pages opened from tabs', () {
    testWidgets('History -> quest detail -> rate it -> back keeps the History tab', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      final id = state.quests.single.id;
      await tapAndSettle(tester, navItem('History'));
      await tapAndSettle(tester, find.byKey(Key('history_quest_$id')));

      expect(find.byKey(const Key('quest_detail_screen')), findsOneWidget);
      expect(find.text('Bench Bird Count'), findsWidgets);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);

      await tapAndSettle(tester, find.byKey(const Key('star_5')));
      await tapAndSettle(tester, find.byKey(const Key('submit_feedback_button')));
      expect(find.byKey(const Key('quest_detail_feedback')), findsOneWidget);
      expect(backend.quests[state.account!.id]!.single['status'], 'completed');

      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('bottom_nav')), findsOneWidget);
      expect(selectedTab(tester), 1);
      expect(find.text('10 min · Completed · ★★★★★'), findsOneWidget);
    });

    testWidgets('Account shows the user; Edit account saves name + preferences', (tester) async {
      final state = await startLoggedIn(tester);
      await tapAndSettle(tester, navItem('Account'));
      expect(find.text('Gowtham'), findsOneWidget);
      expect(find.text('gowtham@example.com'), findsOneWidget);

      await tapAndSettle(tester, find.byKey(const Key('edit_account_tile')));
      expect(find.byKey(const Key('edit_account_screen')), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
      await enter(tester, 'edit_name', 'G');
      await tapAndSettle(tester, find.byKey(const Key('save_account_button')));

      expect(find.byKey(const Key('account_screen')), findsOneWidget);
      expect(selectedTab(tester), 2);
      expect(find.text('G'), findsOneWidget);
      expect(backend.users[state.account!.id]!['name'], 'G');
    });

    testWidgets('Log out revokes the session, clears the device and returns to Log in', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      final userId = state.account!.id;
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('log_out_button')));

      expect(find.text('Welcome back'), findsOneWidget);
      expect(find.byKey(const Key('bottom_nav')), findsNothing);
      expect(rootCanPop(tester), isFalse);
      expect(backend.sessions, isEmpty);
      expect(secure.values, isEmpty);
      expect(cache.values.keys.where((k) => k.endsWith(userId)), isEmpty);
    });

    testWidgets('Log out with unsynced changes asks first', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      backend.online = false;
      await state.sendFeedback(state.quests.single.id, const QuestFeedback(completed: false));
      await tester.pumpAndSettle();

      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('log_out_button')));
      expect(find.text('Log out?'), findsOneWidget);
      await tapAndSettle(tester, find.text('Cancel'));
      expect(find.byKey(const Key('account_screen')), findsOneWidget);
      expect(state.isLoggedIn, isTrue);

      await tapAndSettle(tester, find.byKey(const Key('log_out_button')));
      await tapAndSettle(tester, find.byKey(const Key('confirm_log_out')));
      expect(find.text('Welcome back'), findsOneWidget);
      expect(state.isLoggedIn, isFalse);
    });
  });

  group('Counter, quest log and account deletion', () {
    testWidgets('the counter starts from the server total', (tester) async {
      final user = backend.addUser(prefs: Map.of(savedPrefs));
      final id = user['id'] as String;
      backend.addQuest(id, title: 'Done One', feedback: {'completed': true, 'rating': 5});
      backend.addQuest(id, title: 'Done Two', feedback: {'completed': true, 'rating': 4});
      backend.addQuest(id, title: 'Skipped', feedback: {'completed': false});
      await secure.write('session', jsonEncode(backend.sessionFor(id)));
      useTallScreen(tester);
      final state = newState();
      await state.restore();
      await state.sync();
      await tester.pumpWidget(SidequestApp(state: state));
      await tester.pumpAndSettle();
      expect(counter(tester), '2');
    });

    testWidgets('the current quest stays on the Quest screen after a restart until completed', (tester) async {
      await startLoggedIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('Quest #1'), findsOneWidget);

      await tester.pumpWidget(const SizedBox());
      await startApp(tester);
      expect(find.byKey(const Key('quest_card')), findsOneWidget);
      expect(find.text('Quest #1'), findsOneWidget);
    });

    testWidgets('notes and photos are saved to the quest log and uploaded', (tester) async {
      final state = await startLoggedIn(tester);
      QuestJournal.pickPhoto = ({required bool camera}) async =>
          PickedPhoto(Uint8List.fromList(tinyPng), 'image/png');
      addTearDown(() => QuestJournal.pickPhoto = ({required bool camera}) async => null);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      final questId = state.activeQuest!.id;

      await enter(tester, 'journal_note_field', 'Saw a heron by the pond');
      await tapAndSettle(tester, find.byKey(const Key('add_note_button')));
      await tapAndSettle(tester, find.byKey(const Key('add_photo_button')));

      expect(find.text('Saw a heron by the pond'), findsOneWidget);
      final journal = state.journal(questId);
      expect(journal.map((e) => e.kind), ['note', 'photo']);
      expect(find.byKey(Key('journal_photo_${journal.last.clientId}')), findsOneWidget);
      final saved = backend.logs[state.account!.id]!;
      expect(saved.map((l) => l['kind']), ['note', 'photo']);
      expect(base64Decode(saved.last['image'] as String), tinyPng);
      expect(state.pendingChanges, 0);

      // delete the note
      await tapAndSettle(tester, find.byKey(Key('delete_entry_${journal.first.clientId}')));
      expect(find.text('Saw a heron by the pond'), findsNothing);
      expect(backend.logs[state.account!.id]!.map((l) => l['kind']), ['photo']);
    });

    testWidgets('quest log notes made offline sync later and show in History', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      final id = state.quests.single.id;
      backend.online = false;
      await tapAndSettle(tester, navItem('History'));
      await tapAndSettle(tester, find.byKey(Key('history_quest_$id')));
      await enter(tester, 'journal_note_field', 'Rainy but fun');
      await tapAndSettle(tester, find.byKey(const Key('add_note_button')));
      expect(find.textContaining('waiting to sync'), findsOneWidget);
      expect(state.pendingChanges, 1);

      backend.online = true;
      await state.sync();
      await tester.pumpAndSettle();
      expect(state.pendingChanges, 0);
      expect(backend.logs[state.account!.id]!.single['text'], 'Rainy but fun');
      expect(find.textContaining('waiting to sync'), findsNothing);
    });

    testWidgets('quest output no longer shows the reasoning line', (tester) async {
      await startLoggedIn(tester);
      await tapAndSettle(tester, find.byKey(const Key('generate_button')));
      expect(find.text('You like nature.'), findsNothing); // fake backend's why_it_fits
    });

    testWidgets('delete account needs the password, then wipes everything', (tester) async {
      final state = await startLoggedIn(tester, quests: 1);
      final id = state.account!.id;
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('delete_account_button')));
      expect(find.text('Delete your account?'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('delete_password')), 'not my password');
      await tapAndSettle(tester, find.byKey(const Key('confirm_delete_account')));
      expect(find.text('Wrong password'), findsOneWidget);
      expect(backend.users.containsKey(id), isTrue);

      await tester.enterText(find.byKey(const Key('delete_password')), 'correct horse');
      await tapAndSettle(tester, find.byKey(const Key('confirm_delete_account')));
      expect(find.text('Welcome back'), findsOneWidget);
      expect(rootCanPop(tester), isFalse);
      expect(backend.users.containsKey(id), isFalse);
      expect(backend.quests.containsKey(id), isFalse);
      expect(secure.values, isEmpty);
      expect(cache.values.keys.where((k) => k.endsWith(id)), isEmpty);
    });

    testWidgets('delete account needs a connection', (tester) async {
      final state = await startLoggedIn(tester);
      backend.online = false;
      await tapAndSettle(tester, navItem('Account'));
      await tapAndSettle(tester, find.byKey(const Key('delete_account_button')));
      await tester.enterText(find.byKey(const Key('delete_password')), 'correct horse');
      await tapAndSettle(tester, find.byKey(const Key('confirm_delete_account')));
      expect(find.textContaining('needs a connection'), findsOneWidget);
      expect(state.isLoggedIn, isTrue);
    });
  });
}
