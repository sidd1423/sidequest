import 'package:flutter/material.dart';

/// Small banner marking a screen or section as a placeholder.
class ComingSoonBanner extends StatelessWidget {
  const ComingSoonBanner({super.key, this.message = 'Layout only - not connected yet'});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      color: colors.tertiaryContainer,
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Icon(Icons.construction, color: colors.onTertiaryContainer),
            const SizedBox(width: 12),
            Expanded(
              child: Text(message, style: TextStyle(color: colors.onTertiaryContainer)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Shows a "coming soon" snackbar - used by buttons that have no behaviour yet.
void showComingSoon(BuildContext context, String feature) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text('$feature is coming soon')));
}
