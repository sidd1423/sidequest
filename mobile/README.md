# Sidequest mobile app (Flutter)

App outline: all screens and navigation, **no backend calls yet**. Forms work
locally (selections, validation, the quest card and rating form), quests are
placeholders, buttons that would hit the server show "coming soon", and the
History tab shows sample quests.

**Which preferences live where**

- *Set once* (Sign up step 2, editable in Edit account): interests, accessibility,
  surroundings, crowds, who's with you, weather to avoid + temperature range.
- *Picked before each quest* (Quest tab): minutes (5-30), difficulty, energy,
  distance (0-5 km).
- The quest card appears only after tapping **Generate**, with the
  "How did it go?" rating form underneath (completed / didn't finish, stars -
  required only if completed - time spent, comment).

## Screens & navigation

```
Log in  <──>  Sign up ──▶ Set up your quests   auth screens - no bottom bar
   │                          │
   └──── Log in ──────── Start questing ─┐    (back stack cleared)
                                     ▼
            ┌──────────── bottom bar ────────────┐
            │   Quest   │   History   │  Account  │
            └───────────┴──────┬──────┴─────┬─────┘
                               ▼            ├─▶ Edit account (Save -> back)
                         Quest detail       └─▶ Log out -> Log in (stack cleared)
```

| Screen | File | Reached from |
|---|---|---|
| Log in | `lib/screens/auth/login_screen.dart` | app start, Sign up, Log out |
| Sign up | `lib/screens/auth/sign_up_screen.dart` | Log in |
| Set up your quests (sign-up step 2) | `lib/screens/auth/preferences_setup_screen.dart` | Sign up > Create account |
| Quest generator (tab) | `lib/screens/quest/quest_generator_screen.dart` (+ `quest_card.dart`, `quest_feedback_form.dart`) | bottom bar (default tab) |
| Quest history (tab) | `lib/screens/history/quest_history_screen.dart` | bottom bar |
| Quest detail | `lib/screens/history/quest_detail_screen.dart` | tap a quest in History |
| Account (tab) | `lib/screens/account/account_screen.dart` | bottom bar |
| Edit account | `lib/screens/account/edit_account_screen.dart` | Account > Edit account |

- The bottom bar lives in `lib/screens/home_shell.dart` (Material 3
  `NavigationBar` + `IndexedStack`, so each tab keeps its state).
- Route names are in `lib/app_routes.dart`; routes are registered in `lib/main.dart`.
- No third-party packages - just Flutter's built-in `Navigator`.

## Run it (Windows)

1. Install Flutter: https://docs.flutter.dev/get-started/install/windows
   (check with `flutter doctor`).
2. Generate the platform folders (only the first time - existing files are
   not overwritten):

   ```powershell
   cd ~\sidequest\mobile
   flutter create --project-name sidequest --platforms=android,ios,web,windows .
   ```

3. Run and test:

   ```powershell
   flutter pub get
   flutter run          # pick Chrome, Windows or an emulator
   flutter test         # navigation tests in test/widget_test.dart
   ```
