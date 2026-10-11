import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;
import 'package:sentry_flutter/sentry_flutter.dart';

/// Crash + error reporting with Sentry (https://sentry.io).
///
/// Off unless the app is built/run with a DSN:
///   flutter run --dart-define=SENTRY_DSN=https://...@o123.ingest.sentry.io/456
///   (optional) --dart-define=SENTRY_ENVIRONMENT=production
///
/// When on, Sentry gets: crashes and uncaught Flutter/Dart errors (with the
/// screen they happened on), native crashes (Android/iOS/Windows), HTTP
/// breadcrumbs + spans for every backend call, server errors (5xx) from the
/// backend, and quest generations that failed or timed out on the device.
/// Only the account id is attached - never email, name, location or photos.
class Monitoring {
  Monitoring._();

  static const dsn = String.fromEnvironment('SENTRY_DSN');
  static const environment = String.fromEnvironment('SENTRY_ENVIRONMENT', defaultValue: 'development');

  static bool get enabled => dsn.isNotEmpty;

  /// Start Sentry (if configured), then run the app inside it so every error is caught.
  static Future<void> run(FutureOr<void> Function() app) async {
    if (!enabled) {
      await app();
      return;
    }
    await SentryFlutter.init(
      (options) {
        options.dsn = dsn;
        options.environment = environment;
        options.tracesSampleRate = 0.2; // 1 in 5 sessions' screens/HTTP calls as performance traces
        options.sendDefaultPii = false; // no IPs / user names
        options.attachScreenshot = false; // the screen can show notes, photos and where you are
        options.maxBreadcrumbs = 100;
      },
      appRunner: app,
    );
  }

  /// The HTTP client for the backend: records each call (and 5xx errors) when Sentry is on.
  static http.Client httpClient() => enabled ? SentryHttpClient() : http.Client();

  /// Tracks screen changes (breadcrumbs + screen load spans).
  static List<NavigatorObserver> get navigatorObservers => enabled ? [SentryNavigatorObserver()] : const [];

  /// Attach the account id to reports (null = logged out).
  static void setUser(String? userId) {
    if (!enabled) return;
    Sentry.configureScope((scope) => scope.setUser(userId == null ? null : SentryUser(id: userId)));
  }

  /// Report a handled problem worth seeing in Sentry (e.g. a quest that couldn't be generated).
  static void report(Object error, {StackTrace? stackTrace, String? message, Map<String, Object?> data = const {}}) {
    if (!enabled) return;
    unawaited(Sentry.captureException(
      error,
      stackTrace: stackTrace,
      withScope: (scope) {
        if (message != null) scope.setTag('what', message);
        if (data.isNotEmpty) scope.setContexts('details', data);
      },
    ));
  }

  /// A trail entry shown with the next error report.
  static void breadcrumb(String message, {Map<String, Object?>? data}) {
    if (!enabled) return;
    unawaited(Sentry.addBreadcrumb(Breadcrumb(message: message, category: 'sidequest', data: data)));
  }
}
