import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';
import 'storage.dart';

class ApiException implements Exception {
  final int status;
  final String code;
  ApiException(this.status, this.code);

  @override
  String toString() => 'ApiException($status, $code)';

  /// A message safe to show a user.
  String get friendly {
    switch (code) {
      case 'invalid_credentials':
        return 'Wrong email or password.';
      case 'totp_required':
        return 'Enter your 6-digit authenticator code.';
      case 'rate_limited':
        return 'Too many attempts. Wait a few minutes and try again.';
      case 'forbidden':
        return 'This account can’t use the app.';
      case 'unauthorized':
        return 'Your session expired. Please sign in again.';
      case 'not_found':
        return 'That order no longer exists.';
      default:
        return 'Something went wrong ($code).';
    }
  }
}

/// Result of a successful login.
class LoginResult {
  final String token;
  final String? businessName;
  final String role;
  LoginResult({required this.token, required this.businessName, required this.role});
}

class ApiClient {
  final String baseUrl;
  final String? token;

  ApiClient({required this.baseUrl, this.token});

  /// Builds a client from what's persisted (base URL + token).
  static Future<ApiClient> current() async {
    final baseUrl = await Storage.readBaseUrl();
    final token = await Storage.readToken();
    return ApiClient(baseUrl: baseUrl, token: token);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Never _raise(http.Response res) {
    String code = 'http_${res.statusCode}';
    try {
      final body = jsonDecode(res.body);
      if (body is Map && body['error'] != null) code = body['error'].toString();
    } catch (_) {}
    throw ApiException(res.statusCode, code);
  }

  static Future<LoginResult> login({
    required String baseUrl,
    required String email,
    required String password,
    String? code,
  }) async {
    final res = await http.post(
      Uri.parse('$baseUrl/api/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': email,
        'password': password,
        if (code != null && code.isNotEmpty) 'code': code,
      }),
    );
    if (res.statusCode != 200) {
      String errCode = 'http_${res.statusCode}';
      try {
        final body = jsonDecode(res.body);
        if (body is Map && body['error'] != null) errCode = body['error'].toString();
      } catch (_) {}
      throw ApiException(res.statusCode, errCode);
    }
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final user = (body['user'] ?? {}) as Map<String, dynamic>;
    return LoginResult(
      token: body['token'] as String,
      businessName: user['business_name'] as String?,
      role: (user['role'] ?? '').toString(),
    );
  }

  /// Request a password-reset email. The server always responds generically
  /// (never revealing whether the address has an account), so this never throws
  /// on "unknown email".
  static Future<void> forgotPassword({required String baseUrl, required String email}) async {
    await http.post(
      Uri.parse('$baseUrl/api/forgot-password'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email}),
    );
  }

  Future<List<AppOrder>> listOrders({bool onlyActionRequired = false}) async {
    final path = onlyActionRequired ? '/api/action-required' : '/api/orders';
    final res = await http.get(_uri(path), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final orders = (body['orders'] ?? []) as List;
    return orders.map((e) => AppOrder.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<AppOrder> getOrder(int id) async {
    final res = await http.get(_uri('/api/orders/$id'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    return AppOrder.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<AppOrder> doAction(int id, String action, {int? deliveryFee}) async {
    final res = await http.post(
      _uri('/api/orders/$id/action'),
      headers: _headers,
      body: jsonEncode({
        'action': action,
        if (deliveryFee != null) 'delivery_fee': deliveryFee,
      }),
    );
    if (res.statusCode != 200) _raise(res);
    return AppOrder.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  /// Whether this business is currently accepting orders (open/paused switch).
  Future<bool> getAcceptingOrders() async {
    final res = await http.get(_uri('/api/business'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    return body['accepting_orders'] == true;
  }

  /// Flip the open/paused switch; returns the new state.
  Future<bool> setAcceptingOrders(bool accepting) async {
    final res = await http.post(
      _uri('/api/business/accepting-orders'),
      headers: _headers,
      body: jsonEncode({'accepting_orders': accepting}),
    );
    if (res.statusCode != 200) _raise(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    return body['accepting_orders'] == true;
  }

  Future<void> registerDevice(String fcmToken) async {
    final res = await http.post(
      _uri('/api/devices'),
      headers: _headers,
      body: jsonEncode({'token': fcmToken, 'platform': 'android'}),
    );
    if (res.statusCode != 200) _raise(res);
  }

  Future<void> unregisterDevice(String fcmToken) async {
    await http.delete(
      _uri('/api/devices'),
      headers: _headers,
      body: jsonEncode({'token': fcmToken}),
    );
  }
}
