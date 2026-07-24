import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../push.dart';
import '../storage.dart';
import '../theme.dart';
import 'orders_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _baseUrl = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _code = TextEditingController();
  bool _needs2fa = false;
  bool _busy = false;
  bool _showAdvanced = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    Storage.readBaseUrl().then((v) => setState(() => _baseUrl.text = v));
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    _email.dispose();
    _password.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final baseUrl = _baseUrl.text.trim().replaceAll(RegExp(r'/+$'), '');
    try {
      final result = await ApiClient.login(
        baseUrl: baseUrl,
        email: _email.text.trim(),
        password: _password.text,
        code: _needs2fa ? _code.text.trim() : null,
      );
      await Storage.writeBaseUrl(baseUrl);
      await Storage.writeToken(result.token);
      await Storage.writeProfile(email: _email.text.trim(), businessName: result.businessName);
      await PushService.registerWithBackend();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const OrdersScreen()));
    } on ApiException catch (e) {
      setState(() {
        if (e.code == 'totp_required') {
          _needs2fa = true;
          _error = 'Enter your 6-digit authenticator code.';
        } else {
          _error = e.friendly;
        }
      });
    } catch (_) {
      setState(() => _error = 'Can’t reach the server. Check the address and your connection.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: GlowBackground(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 40, 24, 32),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Center(child: BrandLogo(size: 72)),
                    const SizedBox(height: 22),
                    Center(
                      child: GradientText(
                        'Recbot',
                        style: Theme.of(context).textTheme.headlineMedium!.copyWith(fontSize: 34),
                      ),
                    ),
                    const SizedBox(height: 6),
                    const Center(
                      child: Text(
                        'Order alerts that reach you anywhere',
                        style: TextStyle(color: AppColors.muted, fontSize: 15),
                      ),
                    ),
                    const SizedBox(height: 34),
                    _card(),
                    const SizedBox(height: 18),
                    _legalLinks(),
                    const SizedBox(height: 10),
                    const Center(
                      child: Text('Powered by Collxct', style: TextStyle(color: AppColors.muted2, fontSize: 12)),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _forgotPassword() async {
    final controller = TextEditingController(text: _email.text.trim());
    final baseUrl = _baseUrl.text.trim().replaceAll(RegExp(r'/+$'), '');
    final email = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Reset password', style: TextStyle(color: AppColors.text)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Enter your email and we'll send a reset link.",
                style: TextStyle(color: AppColors.muted, fontSize: 13)),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              autofocus: true,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Email'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: AppColors.muted))),
          TextButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Send link', style: TextStyle(color: AppColors.emeraldBright, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    if (email == null || email.isEmpty) return;
    try {
      await ApiClient.forgotPassword(baseUrl: baseUrl, email: email);
    } catch (_) {/* server responds generically regardless */}
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('If an account exists, we’ve emailed a reset link. Check your inbox.'),
      ));
    }
  }

  Future<void> _openLegal(String path) async {
    final base = _baseUrl.text.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base$path');
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Couldn’t open the page.')));
      }
    }
  }

  Widget _legalLinks() {
    const style = TextStyle(color: AppColors.muted, fontSize: 12.5, decoration: TextDecoration.underline);
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        GestureDetector(onTap: () => _openLegal('/terms'), child: const Text('Terms of Use', style: style)),
        const Text('   ·   ', style: TextStyle(color: AppColors.muted2, fontSize: 12.5)),
        GestureDetector(onTap: () => _openLegal('/privacy'), child: const Text('Privacy Policy', style: style)),
      ],
    );
  }

  Widget _card() {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppColors.borderStrong),
        boxShadow: const [BoxShadow(color: Color(0x40000000), blurRadius: 40, offset: Offset(0, 20))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('Welcome back', style: TextStyle(color: AppColors.text, fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          const Text('Sign in to manage your orders.', style: TextStyle(color: AppColors.muted)),
          const SizedBox(height: 20),
          TextField(
            controller: _email,
            decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline, size: 20)),
            keyboardType: TextInputType.emailAddress,
            autofillHints: const [AutofillHints.email],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _password,
            decoration: const InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline, size: 20)),
            obscureText: true,
          ),
          if (_needs2fa) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _code,
              decoration: const InputDecoration(
                  labelText: 'Authenticator code', prefixIcon: Icon(Icons.shield_outlined, size: 20)),
              keyboardType: TextInputType.number,
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 14),
            Row(
              children: [
                const Icon(Icons.error_outline, color: AppColors.dangerSoft, size: 18),
                const SizedBox(width: 8),
                Expanded(child: Text(_error!, style: const TextStyle(color: AppColors.dangerSoft, fontSize: 13))),
              ],
            ),
          ],
          const SizedBox(height: 22),
          GradientButton(label: 'Sign in', busy: _busy, onPressed: _busy ? null : _submit),
          const SizedBox(height: 4),
          Align(
            alignment: Alignment.center,
            child: TextButton(
              onPressed: _busy ? null : _forgotPassword,
              child: const Text('Forgot your password?', style: TextStyle(color: AppColors.emeraldBright, fontSize: 13)),
            ),
          ),
          Align(
            alignment: Alignment.center,
            child: TextButton(
              onPressed: () => setState(() => _showAdvanced = !_showAdvanced),
              child: Text(
                _showAdvanced ? 'Hide server settings' : 'Server settings',
                style: const TextStyle(color: AppColors.muted, fontSize: 13),
              ),
            ),
          ),
          if (_showAdvanced)
            TextField(
              controller: _baseUrl,
              decoration: const InputDecoration(labelText: 'Server address', prefixIcon: Icon(Icons.dns_outlined, size: 20)),
              keyboardType: TextInputType.url,
            ),
        ],
      ),
    );
  }
}
