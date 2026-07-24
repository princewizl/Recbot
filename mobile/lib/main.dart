import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'push.dart';
import 'screens/login_screen.dart';
import 'screens/order_detail_screen.dart';
import 'screens/orders_screen.dart';
import 'storage.dart';
import 'theme.dart';

/// Lets notification taps navigate even when no widget context is handy.
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Firebase must init before any messaging call. If google-services.json is
  // missing this throws — see mobile/README.md for setup.
  await Firebase.initializeApp();
  await PushService.init(onOpenOrder: _openOrder);

  final token = await Storage.readToken();
  runApp(RecbotApp(loggedIn: token != null));
}

void _openOrder(int orderId) {
  navigatorKey.currentState?.push(
    MaterialPageRoute(builder: (_) => OrderDetailScreen(orderId: orderId)),
  );
}

class RecbotApp extends StatelessWidget {
  final bool loggedIn;
  const RecbotApp({super.key, required this.loggedIn});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Recbot',
      navigatorKey: navigatorKey,
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: loggedIn ? const OrdersScreen() : const LoginScreen(),
    );
  }
}
