import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'config.dart';
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
    final token = await Storage.readToken();
    return ApiClient(baseUrl: Config.defaultBaseUrl, token: token);
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

  /// scope 'active' = orders still in flight (until delivered); '' = all recent.
  Future<List<AppOrder>> listOrders({String scope = ''}) async {
    final path = scope == 'active' ? '/api/orders?scope=active' : '/api/orders';
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

  // --- Dashboard ---

  Future<Map<String, dynamic>> getStats() async {
    final res = await http.get(_uri('/api/stats'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  // --- Catalogue ---

  Future<({List<CatalogueCategory> categories, List<CatalogueItem> items})> getCatalogue() async {
    final res = await http.get(_uri('/api/catalogue'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    return (
      categories: ((body['categories'] ?? []) as List).map((e) => CatalogueCategory.fromJson(e)).toList(),
      items: ((body['items'] ?? []) as List).map((e) => CatalogueItem.fromJson(e)).toList(),
    );
  }

  Future<CatalogueCategory> createCategory(String name) async {
    final res = await http.post(_uri('/api/categories'), headers: _headers, body: jsonEncode({'name': name}));
    if (res.statusCode != 200) _raise(res);
    return CatalogueCategory.fromJson(jsonDecode(res.body));
  }

  /// Create (id == null) or update an item. imagePath sends a new photo; leave
  /// null to keep the current one.
  Future<CatalogueItem> saveItem({
    int? id,
    required String name,
    required int price,
    String description = '',
    int? categoryId,
    required bool isActive,
    required bool isOutOfStock,
    String? imagePath,
  }) async {
    final req = http.MultipartRequest('POST', _uri(id == null ? '/api/items' : '/api/items/$id'));
    if (token != null) req.headers['Authorization'] = 'Bearer $token';
    req.fields['name'] = name;
    req.fields['price'] = price.toString();
    req.fields['description'] = description;
    if (categoryId != null) req.fields['category_id'] = categoryId.toString();
    req.fields['is_active'] = isActive ? '1' : '0';
    req.fields['is_out_of_stock'] = isOutOfStock ? '1' : '0';
    if (imagePath != null) {
      final ext = imagePath.split('.').last.toLowerCase();
      final sub = ext == 'png' ? 'png' : (ext == 'webp' ? 'webp' : 'jpeg');
      req.files.add(await http.MultipartFile.fromPath('image', imagePath, contentType: MediaType('image', sub)));
    }
    final res = await http.Response.fromStream(await req.send());
    if (res.statusCode != 200) _raise(res);
    return CatalogueItem.fromJson(jsonDecode(res.body));
  }

  Future<void> setItemStock(int id, bool outOfStock) async {
    final res = await http.post(_uri('/api/items/$id/stock'), headers: _headers, body: jsonEncode({'is_out_of_stock': outOfStock}));
    if (res.statusCode != 200) _raise(res);
  }

  Future<void> deleteItem(int id) async {
    final res = await http.delete(_uri('/api/items/$id'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
  }

  // --- Business config ---

  Future<Map<String, dynamic>> getBusinessConfig() async {
    final res = await http.get(_uri('/api/business/config'), headers: _headers);
    if (res.statusCode != 200) _raise(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> saveBusinessConfig(Map<String, dynamic> data) async {
    final res = await http.post(_uri('/api/business/config'), headers: _headers, body: jsonEncode(data));
    if (res.statusCode != 200) _raise(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
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
