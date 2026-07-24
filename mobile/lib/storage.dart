import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';

/// Small persistence layer: the auth token lives in encrypted secure storage,
/// while the (non-secret) base URL and cached profile live in shared prefs.
class Storage {
  static const _storage = FlutterSecureStorage();
  static const _kToken = 'auth_token';
  static const _kBaseUrl = 'base_url';
  static const _kEmail = 'email';
  static const _kBusinessName = 'business_name';

  static Future<String?> readToken() => _storage.read(key: _kToken);

  static Future<void> writeToken(String token) =>
      _storage.write(key: _kToken, value: token);

  static Future<void> clearToken() => _storage.delete(key: _kToken);

  static Future<String> readBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kBaseUrl) ?? Config.defaultBaseUrl;
  }

  static Future<void> writeBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, url);
  }

  static Future<void> writeProfile({String? email, String? businessName}) async {
    final prefs = await SharedPreferences.getInstance();
    if (email != null) await prefs.setString(_kEmail, email);
    if (businessName != null) await prefs.setString(_kBusinessName, businessName);
  }

  static Future<String?> readBusinessName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kBusinessName);
  }
}
