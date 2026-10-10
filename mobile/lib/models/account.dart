/// The logged-in user, as returned by the backend's /auth endpoints.
class Account {
  const Account({required this.id, required this.email, this.name = ''});

  final String id; // e.g. u_3f2a... - used in /users/{id}/... URLs
  final String email;
  final String name;

  String get displayName => name.trim().isEmpty ? email : name;

  factory Account.fromJson(Map<String, dynamic> json) => Account(
        id: json['id'] as String,
        email: json['email'] as String,
        name: (json['name'] as String?) ?? '',
      );

  Map<String, dynamic> toJson() => {'id': id, 'email': email, 'name': name};
}

/// A login session. The token is kept in secure storage on the device so the
/// app opens straight into your account, even with no connection.
class Session {
  const Session({required this.token, required this.account});

  final String token;
  final Account account;

  factory Session.fromJson(Map<String, dynamic> json) => Session(
        token: json['token'] as String,
        account: Account.fromJson(json['user'] as Map<String, dynamic>),
      );

  Map<String, dynamic> toJson() => {'token': token, 'user': account.toJson()};

  Session copyWith({Account? account}) => Session(token: token, account: account ?? this.account);
}
