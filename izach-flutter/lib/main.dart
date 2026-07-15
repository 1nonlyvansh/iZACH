import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'home_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  const opts = WindowOptions(
    size: Size(1280, 780),
    minimumSize: Size(1100, 680),
    center: true,
    backgroundColor: Colors.transparent,
    skipTaskbar: false,
    titleBarStyle: TitleBarStyle.hidden,
    title: 'iZACH Neural Interface',
  );

  await windowManager.waitUntilReadyToShow(opts);
  await windowManager.show();
  await windowManager.focus();

  runApp(const IZACHApp());
}

class IZACHApp extends StatelessWidget {
  const IZACHApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'iZACH',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF050D1A),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF00E5FF),
          surface: Color(0xFF071020),
        ),
      ),
      home: const HomeScreen(),
    );
  }
}
