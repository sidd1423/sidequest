import 'package:flutter/material.dart';

/// Honey-trail palette: parchment ground, gold light, copper shade, ink.
class SidequestColors {
  static const cream = Color(0xFFF9E6A8);
  static const gold = Color(0xFFF2A900);
  static const copper = Color(0xFFCC6F00);
  static const ink = Color(0xFF4D2A00);
  static const parchment = Color(0xFFFFF4C8);
  static const frost = Color(0xFF3D6B8A);
}

/// Warm outdoor look — not the Material seed template.
ThemeData buildSidequestTheme() {
  const cream = SidequestColors.cream;
  const gold = SidequestColors.gold;
  const copper = SidequestColors.copper;
  const ink = SidequestColors.ink;
  const parchment = SidequestColors.parchment;

  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: copper,
    onPrimary: cream,
    primaryContainer: gold,
    onPrimaryContainer: ink,
    secondary: gold,
    onSecondary: ink,
    secondaryContainer: Color(0xFFF6D56A),
    onSecondaryContainer: ink,
    tertiary: copper,
    onTertiary: cream,
    tertiaryContainer: Color(0xFFE8B44A),
    onTertiaryContainer: ink,
    error: Color(0xFF8B1A1A),
    onError: cream,
    errorContainer: Color(0xFFF3C4A8),
    onErrorContainer: ink,
    surface: parchment,
    onSurface: ink,
    onSurfaceVariant: Color(0xFF6B3E08),
    outline: copper,
    outlineVariant: Color(0xFFD9A84A),
    shadow: ink,
    scrim: ink,
    inverseSurface: ink,
    onInverseSurface: cream,
    inversePrimary: gold,
    surfaceTint: gold,
  );

  final radius = BorderRadius.circular(18);
  final shape = RoundedRectangleBorder(borderRadius: radius);

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: cream,
    canvasColor: cream,
    splashColor: gold.withValues(alpha: 0.2),
    highlightColor: gold.withValues(alpha: 0.12),
    dividerColor: copper.withValues(alpha: 0.28),
    textTheme: _inkTextTheme(),
    appBarTheme: const AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      backgroundColor: cream,
      foregroundColor: ink,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: TextStyle(
        color: ink,
        fontSize: 22,
        fontWeight: FontWeight.w800,
        letterSpacing: 0.6,
        height: 1.15,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 72,
      elevation: 0,
      backgroundColor: ink,
      indicatorColor: gold,
      indicatorShape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(color: selected ? ink : cream, size: 24);
      }),
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return TextStyle(
          color: selected ? gold : cream.withValues(alpha: 0.85),
          fontSize: 12,
          fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
        );
      }),
    ),
    cardTheme: CardThemeData(
      color: parchment,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: radius,
        side: BorderSide(color: copper.withValues(alpha: 0.38), width: 1.4),
      ),
      clipBehavior: Clip.antiAlias,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: parchment,
      selectedColor: gold,
      disabledColor: cream,
      side: const BorderSide(color: copper),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      labelStyle: const TextStyle(color: ink, fontWeight: FontWeight.w600),
      secondaryLabelStyle: const TextStyle(color: ink),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: parchment,
      labelStyle: const TextStyle(color: ink),
      hintStyle: TextStyle(color: ink.withValues(alpha: 0.55)),
      prefixIconColor: copper,
      border: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: copper)),
      enabledBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: copper.withValues(alpha: 0.55)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: const BorderSide(color: ink, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: const BorderSide(color: Color(0xFF8B1A1A)),
      ),
    ),
    sliderTheme: const SliderThemeData(
      activeTrackColor: copper,
      inactiveTrackColor: Color(0xFFE8C56A),
      thumbColor: ink,
      overlayColor: Color(0x33CC6F00),
      valueIndicatorColor: ink,
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: copper,
      linearTrackColor: Color(0xFFE8C56A),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        backgroundColor: ink,
        foregroundColor: cream,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: 0.4, fontSize: 16),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        foregroundColor: ink,
        side: const BorderSide(color: ink, width: 1.6),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: copper, textStyle: const TextStyle(fontWeight: FontWeight.w700)),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: ink,
      foregroundColor: cream,
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: ink,
      contentTextStyle: const TextStyle(color: cream),
      actionTextColor: gold,
      behavior: SnackBarBehavior.floating,
      shape: shape,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: parchment,
      surfaceTintColor: Colors.transparent,
      shape: shape,
      titleTextStyle: const TextStyle(color: ink, fontSize: 20, fontWeight: FontWeight.w800),
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: ink, borderRadius: BorderRadius.circular(8)),
      textStyle: const TextStyle(color: cream),
    ),
    expansionTileTheme: const ExpansionTileThemeData(
      iconColor: copper,
      collapsedIconColor: ink,
      textColor: ink,
    ),
    listTileTheme: const ListTileThemeData(iconColor: copper, textColor: ink),
    iconTheme: const IconThemeData(color: copper),
    badgeTheme: const BadgeThemeData(backgroundColor: gold, textColor: ink),
  );
}

TextTheme _inkTextTheme() {
  const ink = SidequestColors.ink;
  return const TextTheme(
    displayLarge: TextStyle(color: ink, fontWeight: FontWeight.w900, letterSpacing: -0.5),
    displayMedium: TextStyle(color: ink, fontWeight: FontWeight.w900),
    displaySmall: TextStyle(color: ink, fontWeight: FontWeight.w800),
    headlineLarge: TextStyle(color: ink, fontWeight: FontWeight.w800, letterSpacing: 0.2),
    headlineMedium: TextStyle(color: ink, fontWeight: FontWeight.w800),
    headlineSmall: TextStyle(color: ink, fontWeight: FontWeight.w700, letterSpacing: 0.2),
    titleLarge: TextStyle(color: ink, fontWeight: FontWeight.w800),
    titleMedium: TextStyle(color: ink, fontWeight: FontWeight.w700, letterSpacing: 0.15),
    titleSmall: TextStyle(color: ink, fontWeight: FontWeight.w700),
    bodyLarge: TextStyle(color: ink, height: 1.35),
    bodyMedium: TextStyle(color: ink, height: 1.35),
    bodySmall: TextStyle(color: ink, height: 1.3),
    labelLarge: TextStyle(color: ink, fontWeight: FontWeight.w700),
    labelMedium: TextStyle(color: ink, fontWeight: FontWeight.w600),
    labelSmall: TextStyle(color: ink, fontWeight: FontWeight.w600),
  );
}
