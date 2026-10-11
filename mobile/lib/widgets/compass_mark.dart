import 'package:flutter/material.dart';

import '../theme.dart';

/// Compass badge shown at the top of the log in / sign up screens.
///
/// Always exactly [size] x [size] and centred, even inside a stretched Column,
/// so it never grows over the title below it.
class CompassMark extends StatelessWidget {
  const CompassMark({super.key, this.size = 72});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        key: const Key('auth_compass'),
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: SidequestColors.parchment,
          border: Border.all(color: SidequestColors.gold, width: size * 0.05),
        ),
        child: Icon(
          Icons.explore_outlined,
          size: size * 0.62,
          color: SidequestColors.copper,
          semanticLabel: 'Sidequest compass',
        ),
      ),
    );
  }
}
