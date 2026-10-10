import 'package:flutter/material.dart';

import '../app_routes.dart';
import '../data/app_scope.dart';
import '../data/app_state.dart';

/// Thin status strip at the top of the signed-in area:
/// offline (with queued changes), session expired, or a failed sync.
class SyncBanner extends StatelessWidget {
  const SyncBanner({super.key});

  static bool isVisible(AppState state) =>
      state.sessionExpired || !state.isOnline || state.lastSyncError != null;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final colors = Theme.of(context).colorScheme;
    final pending = state.pendingChanges;
    final pendingText = pending == 0 ? '' : ' $pending change${pending == 1 ? '' : 's'} will sync when you reconnect.';

    if (state.sessionExpired) {
      return _Strip(
        key: const Key('session_expired_banner'),
        color: colors.errorContainer,
        foreground: colors.onErrorContainer,
        icon: Icons.lock_clock,
        text: 'Your session expired. Log in again to sync.$pendingText',
        action: TextButton(
          key: const Key('session_expired_log_in'),
          onPressed: () => Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.login, (route) => false),
          child: const Text('Log in'),
        ),
      );
    }
    if (!state.isOnline) {
      return _Strip(
        key: const Key('offline_banner'),
        color: colors.secondaryContainer,
        foreground: colors.onSecondaryContainer,
        icon: Icons.cloud_off,
        text: "You're offline - showing saved data.$pendingText",
        action: TextButton(
          onPressed: state.isSyncing ? null : () => state.sync(),
          child: const Text('Retry'),
        ),
      );
    }
    if (state.lastSyncError != null) {
      return _Strip(
        key: const Key('sync_error_banner'),
        color: colors.errorContainer,
        foreground: colors.onErrorContainer,
        icon: Icons.sync_problem,
        text: state.lastSyncError!,
      );
    }
    return const SizedBox.shrink();
  }
}

class _Strip extends StatelessWidget {
  const _Strip({
    super.key,
    required this.color,
    required this.foreground,
    required this.icon,
    required this.text,
    this.action,
  });

  final Color color;
  final Color foreground;
  final IconData icon;
  final String text;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(
            children: [
              Icon(icon, color: foreground, size: 20),
              const SizedBox(width: 12),
              Expanded(child: Text(text, style: TextStyle(color: foreground))),
              if (action != null) action!,
            ],
          ),
        ),
      ),
    );
  }
}
