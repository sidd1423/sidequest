import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// The backend said no (4xx/5xx). [message] is FastAPI's `detail`.
class ApiException implements Exception {
  const ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => message;
}

/// The backend couldn't be reached (no connection, server down, timeout).
class OfflineException implements Exception {
  const OfflineException([this.message = "You're offline - can't reach the Sidequest server."]);

  final String message;

  @override
  String toString() => message;
}

/// Where the FastAPI backend runs. Override with
/// `flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000`.
/// Defaults: the Android emulator reaches your computer at 10.0.2.2,
/// everything else (web, Windows, iOS simulator) at localhost.
String defaultApiBaseUrl() {
  const fromEnv = String.fromEnvironment('API_BASE_URL');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) return 'http://10.0.2.2:8000';
  return 'http://localhost:8000';
}

/// Thin JSON client for the Sidequest API. Adds the session token, turns
/// errors into [ApiException] / [OfflineException].
class ApiClient {
  ApiClient({String? baseUrl, http.Client? httpClient})
      : baseUrl = (baseUrl ?? defaultApiBaseUrl()).replaceAll(RegExp(r'/+$'), ''),
        _http = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _http;

  /// Set after logging in; sent as `Authorization: Bearer <token>`.
  String? token;

  static const defaultTimeout = Duration(seconds: 20);

  /// Gemma can take a while (the backend allows up to 300 s incl. retries).
  static const generateTimeout = Duration(seconds: 360);

  Future<dynamic> get(String path) => _send('GET', path);
  Future<dynamic> post(String path, [Object? body, Duration timeout = defaultTimeout]) =>
      _send('POST', path, body: body, timeout: timeout);
  Future<dynamic> put(String path, Object? body) => _send('PUT', path, body: body);
  Future<dynamic> patch(String path, Object? body) => _send('PATCH', path, body: body);

  Future<dynamic> _send(String method, String path, {Object? body, Duration timeout = defaultTimeout}) async {
    final request = http.Request(method, Uri.parse('$baseUrl$path'));
    request.headers['Accept'] = 'application/json';
    if (token != null) request.headers['Authorization'] = 'Bearer $token';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }

    final http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(request).timeout(timeout));
    } on TimeoutException {
      throw const OfflineException('The server took too long to answer. Check your connection and try again.');
    } on http.ClientException {
      throw const OfflineException(); // includes SocketException on mobile/desktop
    }

    final text = utf8.decode(response.bodyBytes);
    final dynamic json = text.isEmpty ? null : _tryDecode(text);
    if (response.statusCode >= 200 && response.statusCode < 300) return json;
    throw ApiException(response.statusCode, _detail(json, response));
  }

  static dynamic _tryDecode(String text) {
    try {
      return jsonDecode(text);
    } on FormatException {
      return text;
    }
  }

  /// FastAPI errors: {"detail": "message"} or {"detail": [{"loc": [...], "msg": "..."}]}.
  static String _detail(dynamic json, http.Response response) {
    final detail = json is Map<String, dynamic> ? json['detail'] : json;
    if (detail is String && detail.isNotEmpty) return detail;
    if (detail is List && detail.isNotEmpty) {
      return detail
          .map((e) => e is Map ? (e['msg'] ?? e).toString().replaceFirst('Value error, ', '') : e.toString())
          .join('\n');
    }
    return 'Something went wrong (${response.statusCode} ${response.reasonPhrase ?? ''})'.trim();
  }
}
