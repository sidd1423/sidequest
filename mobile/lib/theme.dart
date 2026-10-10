import 'package:flutter/material.dart';

/// Outdoorsy green theme for Sidequest.
ThemeData buildSidequestTheme() {
  final colorScheme = ColorScheme.fromSeed(seedColor: const Color(0xFF2E7D4F));
  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
    ),
  );
}
