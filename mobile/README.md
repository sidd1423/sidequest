# Sidequest mobile app (Flutter)

Sign up / log in against the FastAPI backend, set your preferences, generate
quests with Gemma, rate them and browse your history - **offline-first**.

**Accounts & offline storage**

| What | Stored on the device in | Works offline? |
|---|---|---|
| Login session (token + name/email) | `shared_preferences` (app-private storage) | Yes - the app opens straight into your account |
| Preferences, quest history | `shared_preferences` cache, per account | Yes - shown from the cache, refreshed when online |
| Ratings & preference edits made offline | an *outbox* in the same cache | Yes - saved instantly, sent when back online |
| Signing up, logging in, changing name/email, **generating a quest** | - | No - these need the server (Gemma runs there) |

Sync runs on app start, when the app returns to the foreground, on
pull-to-refresh in History, from **Account > Sync**, and after anything that
reaches the server. A banner shows when you're offline (with the number of
unsynced changes) or when the session expired (log in again - nothing queued
is lost). Logging out removes that account's data from the device (and warns
first if changes haven't synced). Logic: `lib/data/app_state.dart`.

**Which preferences live where**

- *Set once* (Sign up step 2, editable in Edit account): interests, accessibility,
  surroundings, crowds, weather to avoid + temperature range.
- *Picked before each quest* (Quest tab): minutes (5-30), who's with you,
  difficulty, energy, distance (0-5 km) - sent with the Generate request.
- **Generate** asks the backend, which asks Gemma with your profile, these
  settings, 3 example quests and your feedback (see "Feedback loop" in the
  main README). Ratings you send shape the next quest.
- A counter at the top of the Quest tab shows how many quests you've completed.
- Under the quest card, the **Quest log** takes notes and photos (camera on
  phones, file picker on desktop/web). They save offline and upload later;
  you can add more from the quest's page in History.
- Completing a quest removes it from the Quest tab (it's in History). An
  unfinished one stays until you generate another. The current quest survives
  app restarts.
- **Account > Delete account** (needs your password and a connection) deletes
  everything on the server and the device.
- The quest card appears only after tapping **Generate**, with the
  "How did it go?" rating form underneath (completed / didn't finish, stars -
  required only if completed - time spent, comment).

## Screens & navigation

```
Log in  <──>  Sign up ──▶ Set up your quests   auth screens - no bottom bar
   │     (no preferences yet?) ──▶ │
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
- The app opens on Home when a session is saved on the device, otherwise on Log in.
- Packages: `http`, `shared_preferences`. State is a
  plain `ChangeNotifier` (`lib/data/app_state.dart`) shared via `AppScope`.

## Run it (Windows)

1. Install Flutter: https://docs.flutter.dev/get-started/install/windows
   (check with `flutter doctor`).
2. Generate the platform folders (only the first time - existing files are
   not overwritten):

   ```powershell
   cd ~\sidequest\mobile
   flutter create --project-name sidequest --platforms=android,ios,web,windows .
   ```

3. Start the backend (repo root, venv): `uvicorn backend.main:app --reload --host 0.0.0.0`
   (`--host 0.0.0.0` lets an emulator or phone reach it).
4. Run and test:

   ```powershell
   flutter pub get
   flutter run          # pick Chrome, Windows or an emulator
   flutter test         # widget tests against a fake backend (test/fake_backend.dart)
   ```

   The app calls `http://127.0.0.1:8000` (Android emulator: `http://10.0.2.2:8000`).
   If it says it can't reach the server, the backend isn't running (check
   http://127.0.0.1:8000/health in a browser).
   On a real phone, use your computer's LAN address:
   `flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000`.
   Debug Android builds allow plain `http://` (see
   `android/app/src/debug/AndroidManifest.xml`); use HTTPS for release.
