import 'data/app_state.dart';

/// Named routes for the screens that sit on the root navigator.
///
/// The three main tabs (Quest, History, Account) are not routes - they live
/// inside [HomeShell] and are switched with the bottom navigation bar.
abstract final class AppRoutes {
  // Auth (no bottom bar)
  static const login = '/login';
  static const signUp = '/signup';
  static const preferencesSetup = '/signup/preferences'; // second sign-up step

  // Signed-in area (bottom bar)
  static const home = '/home';

  // Detail screens pushed from a tab
  static const questDetail = '/quest-detail';
  static const editAccount = '/account/edit';

  /// After logging in (or opening the app logged in): set up preferences
  /// first if this account has none yet, otherwise straight to Home.
  static String afterLogin(AppState state) => state.profile == null ? preferencesSetup : home;
}
