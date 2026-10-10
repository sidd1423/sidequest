import 'package:flutter/material.dart';

import 'app_routes.dart';
import 'data/api_client.dart';
import 'data/app_scope.dart';
import 'data/app_state.dart';
import 'data/key_value_store.dart';
import 'screens/account/edit_account_screen.dart';
import 'screens/auth/login_screen.dart';
import 'screens/auth/preferences_setup_screen.dart';
import 'screens/auth/sign_up_screen.dart';
import 'screens/history/quest_detail_screen.dart';
import 'screens/home_shell.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState(
    api: ApiClient(),
    cache: await SharedPrefsStore.open(),
    secure: SecureStore(),
  );
  await state.restore(); // local only - opens straight into the app when logged in, even offline
  runApp(SidequestApp(state: state));
  state.sync(); // in the background: send queued changes, pull the latest
}

/// Root of the app.
///
///   Log in  <->  Sign up -> Set up your quests   (auth screens, no bottom bar)
///      |                        |
///      +-----------+------------+
///            v
///   HomeShell  - bottom bar:  Quest | History | Account
///                               |        |         |
///                               |   Quest detail   Edit account
///                               |                  Log out -> Log in
///
/// Starts on Home if a session is saved on the device, otherwise on Log in.
class SidequestApp extends StatelessWidget {
  const SidequestApp({super.key, required this.state});

  final AppState state;

  static final Map<String, WidgetBuilder> routes = {
    AppRoutes.login: (_) => const LoginScreen(),
    AppRoutes.signUp: (_) => const SignUpScreen(),
    AppRoutes.preferencesSetup: (_) => const PreferencesSetupScreen(),
    AppRoutes.home: (_) => const HomeShell(),
    AppRoutes.editAccount: (_) => const EditAccountScreen(),
  };

  /// On web the first route comes from the browser address bar (refresh,
  /// bookmarks), so only allow screens that make sense right now.
  String _safeInitialRoute(String name) {
    const authScreens = {AppRoutes.login, AppRoutes.signUp};
    if (!state.isLoggedIn) return authScreens.contains(name) ? name : AppRoutes.login;
    if (!routes.containsKey(name) || authScreens.contains(name)) return AppRoutes.afterLogin(state);
    return name;
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: state,
      child: MaterialApp(
        title: 'Sidequest',
        debugShowCheckedModeBanner: false,
        theme: buildSidequestTheme(),
        initialRoute: state.isLoggedIn
            ? AppRoutes.afterLogin(state)
            : AppRoutes.login,
        routes: routes,
        // Open on exactly one screen (the default would also push "/signup"
        // underneath "/signup/preferences").
        onGenerateInitialRoutes: (name) {
          final target = _safeInitialRoute(name);
          return [MaterialPageRoute<void>(settings: RouteSettings(name: target), builder: routes[target]!)];
        },
        onGenerateRoute: (settings) {
          // Routes that take arguments.
          final questId = settings.arguments;
          if (settings.name == AppRoutes.questDetail && questId is int) {
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => QuestDetailScreen(questId: questId),
            );
          }
          return null;
        },
      ),
    );
  }
}

