import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api.dart';
import 'config.dart';

/// Runs when a push arrives while the app is terminated or backgrounded.
/// Must be a top-level function annotated for the background isolate.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // FCM already draws the system-tray notification for us in the background,
  // so there's nothing to do here except exist (the handler is required).
}

/// Wires up Firebase Messaging + a local-notification channel so alerts show as
/// heads-up notifications with sound even when the app is in the foreground.
class PushService {
  static final _local = FlutterLocalNotificationsPlugin();
  static void Function(int orderId)? _onOpenOrder;

  static Future<void> init({required void Function(int orderId) onOpenOrder}) async {
    _onOpenOrder = onOpenOrder;

    // Android 13+ needs runtime permission to post notifications.
    await FirebaseMessaging.instance.requestPermission();

    // Create the channel the backend targets ("orders") so heads-up + sound work.
    const channel = AndroidNotificationChannel(
      Config.orderChannelId,
      Config.orderChannelName,
      description: Config.orderChannelDescription,
      importance: Importance.high,
    );
    await _local
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);

    const initSettings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    await _local.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (response) {
        final payload = response.payload;
        if (payload != null) _openFromPayload(payload);
      },
    );

    FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);

    // Foreground: FCM does NOT auto-display, so we draw a local notification.
    FirebaseMessaging.onMessage.listen(_showForeground);

    // Taps that opened the app from the tray.
    FirebaseMessaging.onMessageOpenedApp.listen(_handleOpened);
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) _handleOpened(initial);
  }

  /// Fetch the device token and register it with the backend. Call after login.
  static Future<void> registerWithBackend() async {
    try {
      final fcmToken = await FirebaseMessaging.instance.getToken();
      if (fcmToken == null) return;
      final client = await ApiClient.current();
      if (client.token == null) return;
      await client.registerDevice(fcmToken);
    } catch (e) {
      debugPrint('Push token registration failed: $e');
    }
  }

  /// Remove this device's token on logout so it stops receiving pushes.
  static Future<void> unregister() async {
    try {
      final fcmToken = await FirebaseMessaging.instance.getToken();
      final client = await ApiClient.current();
      if (fcmToken != null && client.token != null) {
        await client.unregisterDevice(fcmToken);
      }
      await FirebaseMessaging.instance.deleteToken();
    } catch (e) {
      debugPrint('Push unregister failed: $e');
    }
  }

  static void _showForeground(RemoteMessage message) {
    final notification = message.notification;
    final title = notification?.title ?? 'Recbot';
    final body = notification?.body ?? '';
    _local.show(
      message.hashCode,
      title,
      body,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          Config.orderChannelId,
          Config.orderChannelName,
          channelDescription: Config.orderChannelDescription,
          importance: Importance.high,
          priority: Priority.high,
        ),
      ),
      payload: message.data['order_id']?.toString(),
    );
  }

  static void _handleOpened(RemoteMessage message) {
    _openFromPayload(message.data['order_id']?.toString());
  }

  static void _openFromPayload(String? orderIdStr) {
    final id = int.tryParse(orderIdStr ?? '');
    if (id != null) _onOpenOrder?.call(id);
  }
}
