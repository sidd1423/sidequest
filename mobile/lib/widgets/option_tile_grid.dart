import 'package:flutter/material.dart';

import '../theme.dart';

/// Equal-sized selectable tiles in a fixed column grid so rows line up.
class OptionTileGrid extends StatelessWidget {
  const OptionTileGrid({
    super.key,
    required this.tiles,
    this.columns = 3,
    this.aspectRatio = 1.12,
    this.spacing = 10,
  });

  final List<Widget> tiles;
  final int columns;
  final double aspectRatio;
  final double spacing;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = (constraints.maxWidth - spacing * (columns - 1)) / columns;
        final height = width / aspectRatio;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final tile in tiles) SizedBox(width: width, height: height, child: tile),
          ],
        );
      },
    );
  }
}

class SelectableOptionTile extends StatelessWidget {
  const SelectableOptionTile({
    super.key,
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final gold = SidequestColors.gold;
    final copper = SidequestColors.copper;
    final ink = SidequestColors.ink;
    return Material(
      color: selected ? gold : SidequestColors.parchment,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: selected ? ink : copper.withValues(alpha: 0.45), width: selected ? 2 : 1.4),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, color: ink, size: 26),
              const SizedBox(height: 6),
              Text(
                label,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: ink,
                  fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                  fontSize: 12,
                  height: 1.15,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
