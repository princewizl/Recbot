import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'push.dart';
import 'screens/affiliate_dashboard_screen.dart';
import 'screens/login_screen.dart';
import 'screens/main_shell.dart';
import 'screens/order_detail_screen.dart';
import 'storage.dart';
import 'theme.dart';

/// Lets notification taps navigate even when no widget context is handy.
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Firebase must init before any messaging call. If google-services.json is
  // missing or misconfigured this throws — don't let that take the whole app
  // down; push notifications just won't work for this session.
  try {
    await Firebase.initializeApp();
    await PushService.init(onOpenOrder: _openOrder);
  } catch (e) {
    debugPrint('Push notification setup failed, continuing without it: $e');
  }

  final token = await Storage.readToken();
  final role = token != null ? await Storage.readRole() : null;
  runApp(RecbotApp(loggedIn: token != null, role: role));
}

void _openOrder(int orderId) {
  navigatorKey.currentState?.push(
    MaterialPageRoute(builder: (_) => OrderDetailScreen(orderId: orderId)),
  );
}

class RecbotApp extends StatelessWidget {
  final bool loggedIn;
  final String? role;
  const RecbotApp({super.key, required this.loggedIn, this.role});

  @override
  Widget build(BuildContext context) {
    Widget home = const LoginScreen();
    if (loggedIn) {
      home = role == 'affiliate' ? const AffiliateDashboardScreen() : const MainShell();
    }
    return MaterialApp(
      title: 'Recbot',
      navigatorKey: navigatorKey,
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: home,
    );
  }
}
