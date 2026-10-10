/// Named routes for the screens that sit on the root navigator.
///
/// The three main tabs (Quest, History, Account) are not routes - they live
/// inside [HomeShell] and are switched with the bottom navigation bar.
abstract final class AppRoutes {
  // Auth (no bottom bar)
  static const login = '/login';
  static const signUp = '/signup';

  // Signed-in area (bottom bar)
  static const home = '/home';

  // Detail screens pushed from a tab
  static const questDetail = '/quest-detail';
  static const editAccount = '/account/edit';
}
