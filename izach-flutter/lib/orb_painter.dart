import 'dart:math' as math;
import 'package:flutter/material.dart';

const cyan = Color(0xFF00E5FF);
const cyanDim = Color(0xFF005060);
const bgDeep = Color(0xFF050D1A);

class JarvisOrbPainter extends CustomPainter {
  final double time;       // seconds, drives all rotations
  final bool speaking;
  final double speakPulse; // 0→1 animated speaking intensity

  JarvisOrbPainter({
    required this.time,
    required this.speaking,
    required this.speakPulse,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final c = Offset(cx, cy);
    final R = size.width * 0.44; // max radius

    _drawHexGrid(canvas, size, c);
    _drawOuterRing(canvas, c, R);
    _drawRadarSweep(canvas, c, R * 0.86);
    _drawArcRing1(canvas, c, R * 0.76);
    _drawSatellites(canvas, c, R * 0.64);
    _drawArcRing2(canvas, c, R * 0.54);
    _drawPulseRings(canvas, c, R * 0.46);
    _drawInnerRing(canvas, c, R * 0.43);
    _drawCentralOrb(canvas, c, R * 0.36);
    _drawDataLabels(canvas, c, R);
  }

  // ── Subtle hexagonal grid background ─────────────────────────
  void _drawHexGrid(Canvas canvas, Size size, Offset c) {
    final p = Paint()
      ..color = cyan.withOpacity(0.04)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.5;

    const s = 28.0; // hex size
    const h = s * 0.866;
    for (double y = -s; y < size.height + s; y += h) {
      for (double x = -s; x < size.width + s; x += s * 1.5) {
        final offset = ((y / h).floor() % 2 == 0) ? 0.0 : s * 0.75;
        _drawHex(canvas, Offset(x + offset, y), s * 0.48, p);
      }
    }
  }

  void _drawHex(Canvas canvas, Offset center, double r, Paint p) {
    final path = Path();
    for (int i = 0; i < 6; i++) {
      final angle = math.pi / 3 * i - math.pi / 6;
      final pt = Offset(center.dx + r * math.cos(angle), center.dy + r * math.sin(angle));
      i == 0 ? path.moveTo(pt.dx, pt.dy) : path.lineTo(pt.dx, pt.dy);
    }
    path.close();
    canvas.drawPath(path, p);
  }

  // ── Outer decoration ring: tick marks + slow counter-rotation ─
  void _drawOuterRing(Canvas canvas, Offset c, double R) {
    final angle = -time * 0.12;

    // Outer circle
    canvas.drawCircle(c, R, Paint()
      ..color = cyan.withOpacity(0.18)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0);

    // Tick marks
    final tickPaint = Paint()
      ..color = cyan.withOpacity(0.35)
      ..strokeWidth = 1.2
      ..strokeCap = StrokeCap.round;

    for (int i = 0; i < 72; i++) {
      final a = angle + (i / 72) * math.pi * 2;
      final isMajor = i % 6 == 0;
      final inner = R - (isMajor ? 10 : 5);
      final outer = R + (isMajor ? 3 : 0);
      canvas.drawLine(
        Offset(c.dx + inner * math.cos(a), c.dy + inner * math.sin(a)),
        Offset(c.dx + outer * math.cos(a), c.dy + outer * math.sin(a)),
        tickPaint..color = cyan.withOpacity(isMajor ? 0.5 : 0.2),
      );
    }

    // Three arc segments with gaps
    _drawSegmentedArc(canvas, c, R - 6, 0.72, 3, angle + 0.15, cyan.withOpacity(0.5), 1.8);
  }

  // ── Radar sweep with gradient trail ───────────────────────────
  void _drawRadarSweep(Canvas canvas, Offset c, double r) {
    final sweepAngle = time * (speaking ? 2.8 : 1.6);

    // Gradient trail (fan shape behind the beam)
    const trailSpan = math.pi / 2.2;
    final sweepGrad = SweepGradient(
      startAngle: sweepAngle - trailSpan,
      endAngle: sweepAngle,
      colors: [Colors.transparent, cyan.withOpacity(0.0), cyan.withOpacity(speaking ? 0.22 : 0.1)],
      stops: const [0.0, 0.4, 1.0],
    );
    canvas.drawCircle(c, r,
      Paint()
        ..shader = sweepGrad.createShader(Rect.fromCircle(center: c, radius: r))
        ..style = PaintingStyle.fill);

    // Leading beam line
    canvas.drawLine(
      c,
      Offset(c.dx + r * math.cos(sweepAngle), c.dy + r * math.sin(sweepAngle)),
      Paint()
        ..color = cyan.withOpacity(speaking ? 0.9 : 0.6)
        ..strokeWidth = 1.5
        ..strokeCap = StrokeCap.round
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2),
    );

    // Outer ring for this sweep
    canvas.drawCircle(c, r, Paint()
      ..color = cyan.withOpacity(0.12)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.8);
  }

  // ── Arc ring 1: three segmented arcs, medium rotation ────────
  void _drawArcRing1(Canvas canvas, Offset c, double r) {
    _drawSegmentedArc(canvas, c, r, 0.60, 3, time * 0.35, cyan.withOpacity(0.45), 1.6);

    // Dashed inner arc
    _drawDashedArc(canvas, c, r - 8, time * -0.2, cyan.withOpacity(0.2), 0.8);

    // Small node dots at arc ends
    for (int i = 0; i < 3; i++) {
      final a = time * 0.35 + (i / 3) * math.pi * 2;
      final pt = Offset(c.dx + r * math.cos(a), c.dy + r * math.sin(a));
      canvas.drawCircle(pt, 3, Paint()
        ..color = cyan
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3));
    }
  }

  // ── Orbiting satellite dots ───────────────────────────────────
  void _drawSatellites(Canvas canvas, Offset c, double r) {
    const count = 5;
    for (int i = 0; i < count; i++) {
      final a = time * 0.55 + (i / count) * math.pi * 2;
      final pulse = (math.sin(time * 3 + i * 1.2) + 1) / 2;
      final pt = Offset(c.dx + r * math.cos(a), c.dy + r * math.sin(a));
      final size = 2.0 + pulse * 2;
      canvas.drawCircle(pt, size, Paint()
        ..color = cyan.withOpacity(0.5 + pulse * 0.4)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, size));
      // Trailing line to center
      canvas.drawLine(c, pt, Paint()
        ..color = cyan.withOpacity(0.04 + pulse * 0.04)
        ..strokeWidth = 0.5);
    }
  }

  // ── Arc ring 2: six short arcs, counter-rotate ────────────────
  void _drawArcRing2(Canvas canvas, Offset c, double r) {
    _drawSegmentedArc(canvas, c, r, 0.30, 6, -time * 0.50, cyan.withOpacity(0.55), 2.0);
  }

  // ── Expanding pulse rings from center ─────────────────────────
  void _drawPulseRings(Canvas canvas, Offset c, double maxR) {
    const pulseCount = 3;
    for (int i = 0; i < pulseCount; i++) {
      final phase = ((time * 0.6 + i / pulseCount) % 1.0);
      final r = maxR * phase;
      final opacity = (1.0 - phase) * (speaking ? 0.55 : 0.22);
      canvas.drawCircle(c, r, Paint()
        ..color = cyan.withOpacity(opacity)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2);
    }
  }

  // ── Inner counter-rotating segmented ring ─────────────────────
  void _drawInnerRing(Canvas canvas, Offset c, double r) {
    _drawSegmentedArc(canvas, c, r, 0.80, 4, -time * 0.9, cyan.withOpacity(speaking ? 0.8 : 0.5), 2.2);
  }

  // ── Central Jarvis sphere ─────────────────────────────────────
  void _drawCentralOrb(Canvas canvas, Offset c, double r) {
    final pulse = speaking
        ? r * (1.0 + 0.10 * math.sin(time * 7))
        : r * (1.0 + 0.02 * math.sin(time * 2));

    // Outer glow halo
    canvas.drawCircle(c, pulse * 1.55, Paint()
      ..shader = RadialGradient(colors: [
        cyan.withOpacity(speaking ? 0.20 : 0.07),
        Colors.transparent,
      ]).createShader(Rect.fromCircle(center: c, radius: pulse * 1.55)));

    // Main sphere
    canvas.drawCircle(c, pulse, Paint()
      ..shader = RadialGradient(
        center: const Alignment(-0.35, -0.35),
        colors: [
          speaking ? const Color(0xFFB0F4FF) : const Color(0xFF40A0C8),
          const Color(0xFF007090),
          const Color(0xFF001828),
        ],
        stops: const [0.0, 0.45, 1.0],
      ).createShader(Rect.fromCircle(center: c, radius: pulse)));

    // Rim glow
    canvas.drawCircle(c, pulse, Paint()
      ..shader = RadialGradient(
        colors: [Colors.transparent, cyan.withOpacity(speaking ? 0.55 : 0.25)],
        stops: const [0.6, 1.0],
      ).createShader(Rect.fromCircle(center: c, radius: pulse))
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4));

    // Specular highlight
    final specCenter = Offset(c.dx - pulse * 0.32, c.dy - pulse * 0.32);
    canvas.drawCircle(specCenter, pulse * 0.28, Paint()
      ..shader = RadialGradient(
        colors: [Colors.white.withOpacity(0.55), Colors.transparent],
      ).createShader(Rect.fromCircle(center: specCenter, radius: pulse * 0.28)));

    // Speaking: hot core flare
    if (speaking) {
      final flare = (math.sin(time * 8) + 1) / 2;
      canvas.drawCircle(c, pulse * 0.45, Paint()
        ..color = Colors.white.withOpacity(0.12 * flare)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, pulse * 0.2));
    }
  }

  // ── HUD data labels around perimeter ─────────────────────────
  void _drawDataLabels(Canvas canvas, Offset c, double R) {
    final labels = [
      (0.0,        'SYS', '${(32 + 8 * math.sin(time * 0.7)).toStringAsFixed(0)}%'),
      (math.pi/2,  'NET', '${(12.4 + 2 * math.sin(time * 1.1)).toStringAsFixed(1)}ms'),
      (math.pi,    'MEM', '${(48 + 5 * math.sin(time * 0.5)).toStringAsFixed(0)}%'),
      (3*math.pi/2,'GPU', '${(21 + 6 * math.sin(time * 0.9)).toStringAsFixed(0)}%'),
    ];

    for (final (angle, key, val) in labels) {
      final labelR = R * 1.12;
      final pt = Offset(c.dx + labelR * math.cos(angle), c.dy + labelR * math.sin(angle));

      _drawText(canvas, key, pt, 9, cyan.withOpacity(0.45),
          align: TextAlign.center, offsetY: -10);
      _drawText(canvas, val, pt, 11, cyan,
          align: TextAlign.center, offsetY: 4);

      // Connector line from ring to label
      final lineStart = Offset(c.dx + R * 1.01 * math.cos(angle), c.dy + R * 1.01 * math.sin(angle));
      final lineEnd   = Offset(c.dx + R * 1.07 * math.cos(angle), c.dy + R * 1.07 * math.sin(angle));
      canvas.drawLine(lineStart, lineEnd, Paint()
        ..color = cyan.withOpacity(0.3)
        ..strokeWidth = 0.8);
    }
  }

  // ── Helpers ───────────────────────────────────────────────────

  void _drawSegmentedArc(Canvas canvas, Offset c, double r,
      double fill, int segments, double startAngle, Color color, double strokeWidth) {
    final segSpan = (math.pi * 2 * fill) / segments;
    final gapSpan = (math.pi * 2 * (1 - fill)) / segments;
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    for (int i = 0; i < segments; i++) {
      final start = startAngle + i * (segSpan + gapSpan);
      canvas.drawArc(
        Rect.fromCircle(center: c, radius: r),
        start, segSpan, false, p,
      );
    }
  }

  void _drawDashedArc(Canvas canvas, Offset c, double r,
      double startAngle, Color color, double strokeWidth) {
    const dashCount = 48;
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;
    for (int i = 0; i < dashCount; i += 2) {
      final a = startAngle + (i / dashCount) * math.pi * 2;
      canvas.drawArc(
        Rect.fromCircle(center: c, radius: r),
        a, math.pi * 2 / dashCount * 0.55, false, p,
      );
    }
  }

  void _drawText(Canvas canvas, String text, Offset pt, double size, Color color,
      {TextAlign align = TextAlign.left, double offsetY = 0}) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          color: color,
          fontSize: size,
          fontFamily: 'Consolas',
          letterSpacing: 1.5,
          fontWeight: FontWeight.w400,
        ),
      ),
      textAlign: align,
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset(pt.dx - tp.width / 2, pt.dy + offsetY - tp.height / 2));
  }

  @override
  bool shouldRepaint(JarvisOrbPainter old) =>
      old.time != time || old.speaking != speaking || old.speakPulse != speakPulse;
}
