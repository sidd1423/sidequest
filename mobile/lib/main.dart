import 'package:flutter/material.dart';

import 'app_routes.dart';
import 'models/sample_quest.dart';
import 'screens/account/edit_account_screen.dart';
import 'screens/auth/login_screen.dart';
import 'screens/auth/sign_up_screen.dart';
import 'screens/history/quest_detail_screen.dart';
import 'screens/home_shell.dart';
import 'theme.dart';

void main() {
  runApp(const SidequestApp());
}

/// Root of the app.
///
/// Navigation map (no functionality wired up yet):
///
///   Log in  <->  Sign up                      (auth screens, no bottom bar)
///      |            |
///      +-----+------+
///            v
///   HomeShell  - bottom bar:  Quest | History | Account
///                               |        |         |
///                               |   Quest detail   Edit account
///                               |                  Log out -> Log in
class SidequestApp extends StatelessWidget {
  const SidequestApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sidequest',
      debugShowCheckedModeBanner: false,
      theme: buildSidequestTheme(),
      initialRoute: AppRoutes.login,
      routes: {
        AppRoutes.login: (_) => const LoginScreen(),
        AppRoutes.signUp: (_) => const SignUpScreen(),
        AppRoutes.home: (_) => const HomeShell(),
        AppRoutes.editAccount: (_) => const EditAccountScreen(),
      },
      onGenerateRoute: (settings) {
        // Routes that take arguments.
        if (settings.name == AppRoutes.questDetail) {
          final quest = settings.arguments as SampleQuest;
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => QuestDetailScreen(quest: quest),
          );
        }
        return null;
      },
    );
  }
}
