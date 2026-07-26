import 'package:flutter/material.dart';

import '../api.dart';
import '../push.dart';
import '../storage.dart';
import '../theme.dart';
import 'login_screen.dart';

class HomeScreen extends StatefulWidget {
  final VoidCallback? onGoToOrders;
  const HomeScreen({super.key, this.onGoToOrders});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  Map<String, dynamic>? _stats;
  bool? _accepting;
  bool _toggling = false;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
    PushService.registerWithBackend();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load();
  }

  Future<void> _load() async {
    try {
      final client = await ApiClient.current();
      final stats = await client.getStats();
      if (mounted) {
        setState(() {
          _stats = stats;
          _accepting = stats['accepting_orders'] == true;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _loading = false);
        if (e is ApiException && e.code == 'unauthorized') _logout();
      }
    }
  }

  Future<void> _setOpen(bool v) async {
    setState(() => _toggling = true);
    try {
      final client = await ApiClient.current();
      final result = await client.setAcceptingOrders(v);
      if (mounted) setState(() => _accepting = result);
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Couldn’t update.')));
    } finally {
      if (mounted) setState(() => _toggling = false);
    }
  }

  Future<void> _logout() async {
    await PushService.unregister();
    await Storage.clearToken();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _stats;
    return Scaffold(
      extendBodyBehindAppBar: true,
      body: GlowBackground(
        child: SafeArea(
          child: RefreshIndicator(
            color: AppColors.emeraldBright,
            backgroundColor: AppColors.surface,
            onRefresh: _load,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
              children: [
                Row(
                  children: [
                    const BrandLogo(size: 44),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Welcome back', style: TextStyle(color: AppColors.muted, fontSize: 13)),
                          Text(
                            (s?['business_name'] as String?)?.isNotEmpty == true ? s!['business_name'] : 'Your storefront',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: AppColors.text, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.5),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: 'Sign out',
                      icon: const Icon(Icons.logout_rounded, color: AppColors.muted),
                      onPressed: _logout,
                    ),
                  ],
                ),
                const SizedBox(height: 22),
                if (_accepting != null) _openCard(),
                const SizedBox(height: 16),
                if (_loading)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 40),
                    child: Center(child: CircularProgressIndicator(color: AppColors.emeraldBright)),
                  )
                else ...[
                  _sectionLabel('Today'),
                  Row(children: [
                    Expanded(child: _stat('Orders', '${s?['orders_today'] ?? 0}', Icons.receipt_long_rounded, AppColors.emeraldBright)),
                    const SizedBox(width: 12),
                    Expanded(child: _stat('Revenue', '₦${_fmt(s?['revenue_today'])}', Icons.payments_rounded, AppColors.gold)),
                  ]),
                  const SizedBox(height: 12),
                  _sectionLabel('Right now'),
                  Row(children: [
                    Expanded(
                      child: _stat(
                        'Needs action', '${s?['needs_action'] ?? 0}', Icons.priority_high_rounded,
                        (s?['needs_action'] ?? 0) > 0 ? AppColors.danger : AppColors.muted,
                        onTap: widget.onGoToOrders,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: _stat('Active orders', '${s?['active_orders'] ?? 0}', Icons.local_shipping_rounded, AppColors.emeraldBright, onTap: widget.onGoToOrders)),
                  ]),
                  const SizedBox(height: 12),
                  _stat('Catalogue items', '${s?['item_count'] ?? 0}', Icons.inventory_2_rounded, AppColors.muted, wide: true),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _fmt(dynamic n) {
    final v = (n ?? 0) as num;
    return v.toInt().toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');
  }

  Widget _sectionLabel(String t) => Padding(
        padding: const EdgeInsets.only(bottom: 10, top: 2),
        child: Text(t.toUpperCase(),
            style: const TextStyle(color: AppColors.muted, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 1)),
      );

  Widget _openCard() {
    final open = _accepting!;
    final color = open ? AppColors.emeraldBright : AppColors.danger;
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 16, 14, 16),
      decoration: BoxDecoration(
        gradient: LinearGradient(colors: [color.withValues(alpha: 0.16), color.withValues(alpha: 0.04)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          Icon(open ? Icons.storefront_rounded : Icons.pause_circle_filled_rounded, color: color, size: 30),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(open ? 'Open — taking orders' : 'Paused', style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 16)),
                const SizedBox(height: 2),
                Text(open ? 'Customers can order on WhatsApp' : 'New orders are turned away', style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
              ],
            ),
          ),
          if (_toggling)
            const SizedBox(height: 22, width: 22, child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.emeraldBright))
          else
            Switch(value: open, onChanged: _setOpen),
        ],
      ),
    );
  }

  Widget _stat(String label, String value, IconData icon, Color color, {VoidCallback? onTap, bool wide = false}) {
    final card = Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
        boxShadow: const [BoxShadow(color: Color(0x24000000), blurRadius: 16, offset: Offset(0, 6))],
      ),
      child: Row(
        mainAxisAlignment: wide ? MainAxisAlignment.start : MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value, style: const TextStyle(color: AppColors.text, fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: -0.8)),
              const SizedBox(height: 2),
              Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 13)),
            ],
          ),
          if (wide) const SizedBox(width: 16),
          Container(
            width: 42, height: 42,
            decoration: BoxDecoration(color: color.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(12)),
            child: Icon(icon, color: color, size: 22),
          ),
        ],
      ),
    );
    if (onTap == null) return card;
    return Material(
      color: Colors.transparent,
      child: InkWell(borderRadius: BorderRadius.circular(18), onTap: onTap, child: card),
    );
  }
}
