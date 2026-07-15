import 'dart:async';
import 'dart:math' as math;
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:window_manager/window_manager.dart';
import 'orb_painter.dart';

const _cyan      = Color(0xFF00E5FF);
const _cyanDim   = Color(0xFF1A4A5A);
const _bgDeep    = Color(0xFF050D1A);
const _bgPanel   = Color(0xFF071020);
const _textPri   = Color(0xFFC8E8F0);
const _textSec   = Color(0xFF3A6070);
const _green     = Color(0xFF1DB954);
const _red       = Color(0xFFFF3D3D);
const _amber     = Color(0xFFFFB300);
const _border    = Color(0xFF0D2A3A);

// ─────────────────────────────────────────────────────────────
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with TickerProviderStateMixin, WindowListener {

  // Orb animation
  late final AnimationController _orbCtrl;
  late final AnimationController _speakCtrl;

  // State
  bool _speaking = false;
  double _cpu = 32, _ram = 48, _gpu = 21;
  String _trackTitle = 'Blinding Lights', _trackArtist = 'The Weeknd';
  int _uptime = 0;
  final List<({String sender, String text})> _messages = [];
  final _inputCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final _inputFocus = FocusNode();
  final _cmdHistory = <String>[];
  int _histIdx = -1;

  // Mock metric timers
  Timer? _metricTimer, _uptimeTimer;
  final _rng = math.Random();

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);

    _orbCtrl = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 60),
    )..repeat();

    _speakCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    _messages.addAll([
      (sender: 'iZACH', text: 'Neural interface online — Flutter / Dart engine active.'),
      (sender: 'iZACH', text: 'GPU-accelerated render. Spring physics. Jarvis aesthetic engaged.'),
      (sender: 'iZACH', text: 'Type a command. Connect backend at ws://localhost:5050/ws.'),
    ]);

    _metricTimer = Timer.periodic(const Duration(milliseconds: 800), (_) {
      setState(() {
        _cpu = (_cpu + _rng.nextDouble() * 8 - 4).clamp(5, 92);
        _ram = (_ram + _rng.nextDouble() * 4 - 2).clamp(20, 88);
        _gpu = (_gpu + _rng.nextDouble() * 6 - 3).clamp(5, 78);
      });
    });

    _uptimeTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() => _uptime++);
    });
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    _orbCtrl.dispose();
    _speakCtrl.dispose();
    _metricTimer?.cancel();
    _uptimeTimer?.cancel();
    _inputCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _submit(String text) {
    final cmd = text.trim();
    if (cmd.isEmpty) return;
    _inputCtrl.clear();
    _cmdHistory.add(cmd);
    _histIdx = -1;

    setState(() {
      _messages.add((sender: 'YOU', text: cmd));
      _speaking = true;
    });
    _speakCtrl.forward(from: 0);

    // Mock response
    Future.delayed(const Duration(milliseconds: 1200), () {
      if (!mounted) return;
      const responses = [
        'Acknowledged. Processing neural pathways...',
        'Command received. Executing cognitive subroutines.',
        'Input parsed. Cross-referencing contextual matrix.',
        'Neural sync complete. Deploying response protocol.',
      ];
      setState(() {
        _messages.add((
          sender: 'iZACH',
          text: responses[_rng.nextInt(responses.length)],
        ));
        _speaking = false;
      });
      _speakCtrl.reverse();
      _scrollToBottom();
    });
    _scrollToBottom();
    _inputFocus.requestFocus();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  String get _uptimeStr {
    final h = _uptime ~/ 3600;
    final m = (_uptime % 3600) ~/ 60;
    final s = _uptime % 60;
    return '${h.toString().padLeft(2,'0')}:${m.toString().padLeft(2,'0')}:${s.toString().padLeft(2,'0')}';
  }

  // ── Build ────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgDeep,
      body: Stack(
        children: [
          // Scanline overlay
          Positioned.fill(child: _buildScanlines()),

          Column(children: [
            _buildTitleBar(),
            Expanded(child: Row(children: [
              _buildLeftPanel(),
              Expanded(child: _buildCenter()),
              _buildRightPanel(),
            ])),
          ]),

          // Corner brackets
          ..._cornerBrackets(),
        ],
      ),
    );
  }

  // ── Title bar ────────────────────────────────────────────────
  Widget _buildTitleBar() {
    return GestureDetector(
      onPanStart: (_) => windowManager.startDragging(),
      child: Container(
        height: 42,
        decoration: BoxDecoration(
          color: _bgPanel,
          border: Border(bottom: BorderSide(color: _border)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            width: 7, height: 7,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _speaking ? _cyan : _cyanDim,
              boxShadow: _speaking
                  ? [BoxShadow(color: _cyan.withOpacity(0.6), blurRadius: 8)]
                  : [],
            ),
          ),
          const SizedBox(width: 10),
          _mono('iZ.ACH', 12, _cyan, letterSpacing: 4, bold: true),
          const SizedBox(width: 12),
          _mono('NEURAL INTERFACE  v1.4', 9, _cyanDim, letterSpacing: 3),
          const Spacer(),
          _clockWidget(),
          const SizedBox(width: 16),
          // Window controls
          _winBtn(_amber, () => windowManager.minimize()),
          const SizedBox(width: 8),
          _winBtn(_green,  () {}),
          const SizedBox(width: 8),
          _winBtn(_red,    () => windowManager.close()),
        ]),
      ),
    );
  }

  // ── Left panel ───────────────────────────────────────────────
  Widget _buildLeftPanel() {
    return _glassPanel(
      width: 210,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader('SYSTEM VITALS'),
        _vitalBar('CPU', _cpu),
        _vitalBar('RAM', _ram),
        _vitalBar('GPU', _gpu),
        _divider(),
        _sectionHeader('NETWORK'),
        ...[
          ('WS BRIDGE', 'ONLINE',  _green),
          ('WHATSAPP',  'ACTIVE',  _green),
          ('N8N',       'RUNNING', _amber),
          ('NGROK',     'TUNNEL',  _cyan),
        ].map((e) => _netRow(e.$1, e.$2, e.$3)),
        _divider(),
        _sectionHeader('PROCESSES'),
        ...[
          'MAIN.PY', 'WS_BRIDGE', 'AI_HANDLER', 'CONTEXT_ENG',
        ].map((p) => _processRow(p)),
        const Spacer(),
        Center(child: _mono('BUILD 1.4.0', 8, _cyanDim, letterSpacing: 2)),
        const SizedBox(height: 8),
      ]),
    );
  }

  // ── Center: Orb + Chat ───────────────────────────────────────
  Widget _buildCenter() {
    return Column(children: [
      // Jarvis orb
      Expanded(
        flex: 5,
        child: Container(
          color: _bgDeep,
          child: AnimatedBuilder(
            animation: _orbCtrl,
            builder: (_, __) => CustomPaint(
              painter: JarvisOrbPainter(
                time: _orbCtrl.value * 60 * math.pi * 2 / 60,
                speaking: _speaking,
                speakPulse: _speakCtrl.value,
              ),
              child: Stack(children: [
                Positioned(left: 12, top: 12,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    _mono('iZ.ACH', 8, _cyan.withOpacity(0.4), letterSpacing: 3),
                    _mono(_speaking ? 'SPEAKING' : 'STANDBY', 8,
                        _speaking ? _cyan.withOpacity(0.8) : _cyanDim, letterSpacing: 3),
                  ]),
                ),
                Positioned(right: 12, top: 12,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    _mono('NEURAL', 8, _cyan.withOpacity(0.3), letterSpacing: 3),
                    _mono('CORE',   8, _cyan.withOpacity(0.3), letterSpacing: 3),
                  ]),
                ),
              ]),
            ),
          ),
        ),
      ),
      // Chat panel
      Expanded(
        flex: 4,
        child: Container(
          decoration: BoxDecoration(
            color: _bgDeep,
            border: Border(top: BorderSide(color: _border)),
          ),
          child: Column(children: [
            _sectionHeader('NEURAL FEED'),
            Expanded(
              child: ListView.builder(
                controller: _scrollCtrl,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                itemCount: _messages.length,
                itemBuilder: (_, i) => _chatBubble(_messages[i]),
              ),
            ),
            _buildInputBar(),
          ]),
        ),
      ),
    ]);
  }

  // ── Right panel ──────────────────────────────────────────────
  Widget _buildRightPanel() {
    return _glassPanel(
      width: 210,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _sectionHeader('SPOTIFY'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(children: [
            Container(
              width: 40, height: 40,
              decoration: BoxDecoration(
                color: _border,
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: _cyanDim),
              ),
              child: const Icon(Icons.music_note, color: _green, size: 18),
            ),
            const SizedBox(width: 10),
            Expanded(child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _mono(_trackTitle,  10, _textPri),
                _mono(_trackArtist,  9, _textSec),
              ],
            )),
          ]),
        ),
        const SizedBox(height: 8),
        _spotifyControls(),
        _divider(),
        _sectionHeader('QUICK ACTIONS'),
        ...[
          ('⬡', 'SCAN NETWORK'),
          ('◈', 'SYNC CONTEXT'),
          ('⬢', 'FLUSH CACHE'),
          ('◉', 'VOICE MODE'),
        ].map((e) => _quickAction(e.$1, e.$2)),
        _divider(),
        _sectionHeader('UPTIME'),
        Center(child: _mono(_uptimeStr, 22, _cyan, letterSpacing: 2)),
        Center(child: _mono('SESSION ACTIVE', 8, _cyanDim, letterSpacing: 3)),
        const Spacer(),
      ]),
    );
  }

  // ── Input bar ────────────────────────────────────────────────
  Widget _buildInputBar() {
    return Container(
      height: 54,
      decoration: BoxDecoration(
        color: _bgDeep,
        border: Border(top: BorderSide(color: _border)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Row(children: [
        Expanded(
          child: KeyboardListener(
            focusNode: FocusNode(),
            onKeyEvent: (e) {
              if (e is! KeyDownEvent) return;
              if (e.logicalKey == LogicalKeyboardKey.arrowUp && _cmdHistory.isNotEmpty) {
                _histIdx = (_histIdx + 1).clamp(0, _cmdHistory.length - 1);
                _inputCtrl.text = _cmdHistory[_cmdHistory.length - 1 - _histIdx];
              } else if (e.logicalKey == LogicalKeyboardKey.arrowDown) {
                _histIdx = (_histIdx - 1).clamp(-1, _cmdHistory.length - 1);
                _inputCtrl.text = _histIdx < 0 ? '' : _cmdHistory[_cmdHistory.length - 1 - _histIdx];
              }
            },
            child: TextField(
              controller: _inputCtrl,
              focusNode: _inputFocus,
              autofocus: true,
              style: TextStyle(
                color: _textPri,
                fontFamily: 'Consolas',
                fontSize: 11,
                letterSpacing: 0.5,
              ),
              cursorColor: _cyan,
              cursorWidth: 2,
              decoration: InputDecoration(
                hintText: '[ TYPE COMMAND HERE ]...',
                hintStyle: TextStyle(color: _cyanDim, fontFamily: 'Consolas', fontSize: 11),
                filled: true,
                fillColor: _bgPanel,
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 0),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(3),
                  borderSide: BorderSide(color: _border),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(3),
                  borderSide: BorderSide(color: _border),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(3),
                  borderSide: BorderSide(color: _cyan.withOpacity(0.5), width: 1.5),
                ),
              ),
              onSubmitted: _submit,
            ),
          ),
        ),
        const SizedBox(width: 8),
        _hudBtn('TRANSMIT', _cyan, () => _submit(_inputCtrl.text)),
        const SizedBox(width: 8),
        _hudBtn('■  STOP', _red, () {
          setState(() => _speaking = false);
          _speakCtrl.reverse();
        }),
      ]),
    );
  }

  // ── Reusable widgets ─────────────────────────────────────────

  Widget _glassPanel({required double width, required Widget child}) {
    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
        child: Container(
          width: width,
          decoration: BoxDecoration(
            color: _bgPanel.withOpacity(0.92),
            border: Border(
              left: BorderSide(color: _border),
              right: BorderSide(color: _border),
            ),
          ),
          child: child,
        ),
      ),
    );
  }

  Widget _sectionHeader(String label) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      child: Row(children: [
        _mono('* ', 10, _cyan),
        _mono(label, 9, _cyan, letterSpacing: 4),
        const SizedBox(width: 8),
        Expanded(child: Container(height: 1, color: _border)),
      ]),
    );
  }

  Widget _vitalBar(String label, double value) {
    final color = value > 85 ? _red : value > 65 ? _amber : _cyan;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: Column(children: [
        Row(children: [
          _mono(label, 9, _textSec),
          const Spacer(),
          _mono('${value.toStringAsFixed(0)}%', 9, color),
        ]),
        const SizedBox(height: 3),
        ClipRRect(
          borderRadius: BorderRadius.circular(2),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: value / 100),
            duration: const Duration(milliseconds: 600),
            curve: Curves.easeOutCubic,
            builder: (_, v, __) => LinearProgressIndicator(
              value: v,
              backgroundColor: _border,
              valueColor: AlwaysStoppedAnimation(color),
              minHeight: 3,
            ),
          ),
        ),
      ]),
    );
  }

  Widget _netRow(String label, String status, Color color) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 5),
      child: Row(children: [
        _mono(label, 8, _textSec),
        const Spacer(),
        _pulseDot(color),
        const SizedBox(width: 4),
        _mono(status, 8, color),
      ]),
    );
  }

  Widget _processRow(String name) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
      child: Row(children: [
        _mono('▸ ', 8, _cyan.withOpacity(0.4)),
        _mono(name, 8, _textSec),
        const Spacer(),
        Container(width: 4, height: 4,
          decoration: const BoxDecoration(shape: BoxShape.circle, color: _green)),
      ]),
    );
  }

  Widget _spotifyControls() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        IconButton(icon: const Icon(Icons.skip_previous), color: _textSec, iconSize: 20, onPressed: () {}),
        IconButton(icon: const Icon(Icons.pause_circle_filled), color: _green, iconSize: 28, onPressed: () {}),
        IconButton(icon: const Icon(Icons.skip_next), color: _textSec, iconSize: 20, onPressed: () {}),
      ]),
    );
  }

  Widget _quickAction(String icon, String label) {
    return InkWell(
      onTap: () {},
      hoverColor: _cyan.withOpacity(0.06),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 4),
        child: Row(children: [
          _mono('$icon  ', 10, _cyan.withOpacity(0.4)),
          _mono(label, 9, _textSec, letterSpacing: 1),
          const Spacer(),
          Container(width: 5, height: 5,
            decoration: BoxDecoration(
              border: Border.all(color: _cyanDim),
              borderRadius: BorderRadius.circular(1),
            )),
        ]),
      ),
    );
  }

  Widget _chatBubble(({String sender, String text}) msg) {
    final isUser = msg.sender == 'YOU';
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeOutQuart,
      builder: (_, v, child) => Opacity(
        opacity: v,
        child: Transform.translate(offset: Offset((1 - v) * 14, 0), child: child),
      ),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _mono(msg.sender, 9, isUser ? _cyan.withOpacity(0.5) : _textSec, letterSpacing: 3),
          const SizedBox(height: 3),
          Align(
            alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              constraints: const BoxConstraints(maxWidth: 480),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(
                color: isUser ? _cyan.withOpacity(0.07) : _bgPanel,
                border: Border.all(color: isUser ? _cyan.withOpacity(0.25) : _border),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(2),
                  topRight: const Radius.circular(8),
                  bottomLeft: Radius.circular(isUser ? 8 : 2),
                  bottomRight: const Radius.circular(8),
                ),
              ),
              child: _mono(msg.text, 10, _textPri, letterSpacing: 0.3),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _hudBtn(String label, Color color, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(3),
      hoverColor: color.withOpacity(0.15),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: color.withOpacity(0.08),
          border: Border.all(color: color.withOpacity(0.35)),
          borderRadius: BorderRadius.circular(3),
        ),
        child: _mono(label, 10, color, letterSpacing: 2),
      ),
    );
  }

  Widget _winBtn(Color color, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        child: Container(
          width: 10, height: 10,
          decoration: BoxDecoration(shape: BoxShape.circle, color: color.withOpacity(0.7)),
        ),
      ),
    );
  }

  Widget _pulseDot(Color color) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0.4, end: 1.0),
      duration: const Duration(milliseconds: 900),
      curve: Curves.easeInOut,
      onEnd: () => setState(() {}),
      builder: (_, v, __) => Container(
        width: 5, height: 5,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: color.withOpacity(v),
          boxShadow: [BoxShadow(color: color.withOpacity(v * 0.5), blurRadius: 4)],
        ),
      ),
    );
  }

  Widget _clockWidget() {
    return StreamBuilder(
      stream: Stream.periodic(const Duration(seconds: 1)),
      builder: (_, __) {
        final now = DateTime.now();
        final t = '${now.hour.toString().padLeft(2,'0')}:'
                  '${now.minute.toString().padLeft(2,'0')}:'
                  '${now.second.toString().padLeft(2,'0')}';
        return _mono(t, 9, _textSec, letterSpacing: 2);
      },
    );
  }

  Widget _divider() => Container(height: 1, color: _border, margin: const EdgeInsets.symmetric(vertical: 4));

  // Scanline overlay
  Widget _buildScanlines() {
    return CustomPaint(painter: _ScanlinePainter());
  }

  // Corner brackets
  List<Widget> _cornerBrackets() {
    return [
      Positioned(top: 0, left: 0, child: _bracket(false, false)),
      Positioned(top: 0, right: 0, child: _bracket(true,  false)),
      Positioned(bottom: 0, left: 0, child: _bracket(false, true)),
      Positioned(bottom: 0, right: 0, child: _bracket(true,  true)),
    ];
  }

  Widget _bracket(bool flipX, bool flipY) {
    return Transform.scale(
      scaleX: flipX ? -1 : 1,
      scaleY: flipY ? -1 : 1,
      child: SizedBox(
        width: 20, height: 20,
        child: CustomPaint(painter: _BracketPainter()),
      ),
    );
  }

  // Mono text helper
  Widget _mono(String text, double size, Color color,
      {double letterSpacing = 0.5, bool bold = false}) {
    return Text(text, style: TextStyle(
      color: color, fontSize: size, fontFamily: 'Consolas',
      letterSpacing: letterSpacing, fontWeight: bold ? FontWeight.bold : FontWeight.normal,
    ));
  }
}

// ── Scanline CustomPainter ────────────────────────────────────
class _ScanlinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = Colors.black.withOpacity(0.03);
    for (double y = 0; y < size.height; y += 4) {
      canvas.drawRect(Rect.fromLTWH(0, y + 2, size.width, 2), p);
    }
  }
  @override bool shouldRepaint(_) => false;
}

// ── Corner bracket CustomPainter ─────────────────────────────
class _BracketPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = const Color(0xFF00E5FF).withOpacity(0.5)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..strokeCap = StrokeCap.square;
    canvas.drawLine(Offset(0, 8), Offset(0, 0), p);
    canvas.drawLine(Offset(0, 0), Offset(8, 0), p);
  }
  @override bool shouldRepaint(_) => false;
}
