/// App-wide constants and the default backend location.
///
/// The base URL is only a *default* — the login screen lets the tester type a
/// different one (e.g. an ngrok tunnel or a laptop's LAN IP) and it is saved,
/// so you can point the same APK at any environment without rebuilding.
class Config {
  /// Change this to your deployed backend, or leave it and override on the
  /// login screen. No trailing slash.
  static const String defaultBaseUrl = 'https://collxct.com.ng:8443';

  /// Android notification channel used for order alerts. Must match the
  /// `channel_id` the backend sets on the FCM message ("orders").
  static const String orderChannelId = 'orders';
  static const String orderChannelName = 'Order alerts';
  static const String orderChannelDescription =
      'New orders and orders that need your action.';
}
