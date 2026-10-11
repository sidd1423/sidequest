import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// Compass-sun mark used on auth screens and empty states.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 72});

  final double size;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: Size.square(size),
      painter: const _BrandPainter(),
    );
  }
}

class _BrandPainter extends CustomPainter {
  const _BrandPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final r = size.width * 0.42;

    final disk = Paint()..color = SidequestColors.gold;
    canvas.drawCircle(Offset(cx, cy), r, disk);

    final ray = Paint()
      ..color = SidequestColors.copper
      ..strokeWidth = size.width * 0.045
      ..strokeCap = StrokeCap.round;
    for (var i = 0; i < 8; i++) {
      final a = (i / 8) * math.pi * 2;
      final inner = Offset(cx + math.cos(a) * r * 0.78, cy + math.sin(a) * r * 0.78);
      final outer = Offset(cx + math.cos(a) * r * 1.12, cy + math.sin(a) * r * 1.12);
      canvas.drawLine(inner, outer, ray);
    }

    final trail = Paint()
      ..color = SidequestColors.ink
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * 0.07
      ..strokeCap = StrokeCap.round;
    final path = Path()
      ..moveTo(cx - r * 0.45, cy + r * 0.28)
      ..quadraticBezierTo(cx - r * 0.05, cy + r * 0.55, cx + r * 0.12, cy + r * 0.05)
      ..quadraticBezierTo(cx + r * 0.28, cy - r * 0.28, cx + r * 0.42, cy - r * 0.12);
    canvas.drawPath(path, trail);

    canvas.drawCircle(
      Offset(cx - r * 0.18, cy - r * 0.12),
      r * 0.12,
      Paint()..color = SidequestColors.ink,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
