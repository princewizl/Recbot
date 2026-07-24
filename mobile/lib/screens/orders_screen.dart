import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../push.dart';
import '../storage.dart';
import '../theme.dart';
import 'login_screen.dart';
import 'order_detail_screen.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late Future<List<AppOrder>> _future;
  bool _onlyActionRequired = true;
  String? _businessName;
  bool? _acceptingOrders;
  bool _togglingOpen = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
    Storage.readBusinessName().then((v) => setState(() => _businessName = v));
    _loadOpenState();
    PushService.registerWithBackend();
  }

  Future<List<AppOrder>> _load() async {
    final client = await ApiClient.current();
    return client.listOrders(onlyActionRequired: _onlyActionRequired);
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() => _future = future);
    await future;
    _loadOpenState();
  }

  Future<void> _loadOpenState() async {
    try {
      final client = await ApiClient.current();
      final accepting = await client.getAcceptingOrders();
      if (mounted) setState(() => _acceptingOrders = accepting);
    } catch (_) {/* non-fatal */}
  }

  Future<void> _setOpen(bool accepting) async {
    setState(() => _togglingOpen = true);
    try {
      final client = await ApiClient.current();
      final result = await client.setAcceptingOrders(accepting);
      if (mounted) {
        setState(() => _acceptingOrders = result);
        _toast(result ? 'Open — accepting orders.' : 'Paused — new orders are blocked.');
      }
    } on ApiException catch (e) {
      _toast(e.friendly);
    } catch (_) {
      _toast('Couldn’t reach the server.');
    } finally {
      if (mounted) setState(() => _togglingOpen = false);
    }
  }

  void _toast(String msg) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _logout() async {
    await PushService.unregister();
    await Storage.clearToken();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        toolbarHeight: 64,
        title: Row(
          children: [
            const BrandLogo(size: 34),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('Hello 👋', style: TextStyle(color: AppColors.muted, fontSize: 12, fontWeight: FontWeight.w500)),
                  Text(_businessName ?? 'Your storefront',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.text, fontSize: 18, fontWeight: FontWeight.w800)),
                ],
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout_rounded, color: AppColors.muted),
            onPressed: _logout,
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: GlowBackground(
        child: SafeArea(
          child: Column(
            children: [
              const SizedBox(height: 8),
              if (_acceptingOrders != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                  child: _openCard(),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                child: _filterToggle(),
              ),
              Expanded(
                child: RefreshIndicator(
                  color: AppColors.emeraldBright,
                  backgroundColor: AppColors.surface,
                  onRefresh: _refresh,
                  child: FutureBuilder<List<AppOrder>>(
                    future: _future,
                    builder: (context, snapshot) {
                      if (snapshot.connectionState == ConnectionState.waiting) {
                        return const Center(child: CircularProgressIndicator(color: AppColors.emeraldBright));
                      }
                      if (snapshot.hasError) {
                        final err = snapshot.error;
                        if (err is ApiException && err.code == 'unauthorized') {
                          WidgetsBinding.instance.addPostFrameCallback((_) => _logout());
                        }
                        return _emptyState(Icons.wifi_off_rounded,
                            'Couldn’t load orders', err is ApiException ? err.friendly : 'Pull down to retry.');
                      }
                      final orders = snapshot.data ?? [];
                      if (orders.isEmpty) {
                        return _emptyState(
                          _onlyActionRequired ? Icons.check_circle_outline_rounded : Icons.receipt_long_outlined,
                          _onlyActionRequired ? 'You’re all caught up' : 'No recent orders',
                          _onlyActionRequired
                              ? 'Nothing needs your attention right now. 🎉'
                              : 'New orders will show up here.',
                        );
                      }
                      return ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                        itemCount: orders.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 10),
                        itemBuilder: (_, i) => _OrderCard(order: orders[i], onChanged: _refresh),
                      );
                    },
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _openCard() {
    final open = _acceptingOrders!;
    final color = open ? AppColors.emeraldBright : AppColors.danger;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          Icon(open ? Icons.storefront_rounded : Icons.pause_circle_filled_rounded, color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(open ? 'Open — accepting orders' : 'Paused — orders blocked',
                    style: TextStyle(fontWeight: FontWeight.w800, color: color, fontSize: 15)),
                const SizedBox(height: 2),
                Text(open ? 'Customers can order on WhatsApp.' : 'New WhatsApp orders are turned away.',
                    style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
              ],
            ),
          ),
          if (_togglingOpen)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 10),
              child: SizedBox(height: 22, width: 22, child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.emeraldBright)),
            )
          else
            Switch(value: open, onChanged: _setOpen),
        ],
      ),
    );
  }

  Widget _filterToggle() {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          _filterPill('Needs action', true),
          _filterPill('All recent', false),
        ],
      ),
    );
  }

  Widget _filterPill(String label, bool value) {
    final selected = _onlyActionRequired == value;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          if (_onlyActionRequired != value) {
            setState(() {
              _onlyActionRequired = value;
              _future = _load();
            });
          }
        },
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(vertical: 10),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            gradient: selected ? AppGradients.brand : null,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? AppColors.onEmerald : AppColors.muted,
              fontWeight: FontWeight.w700,
              fontSize: 13.5,
            ),
          ),
        ),
      ),
    );
  }

  Widget _emptyState(IconData icon, String title, String subtitle) {
    return ListView(
      children: [
        SizedBox(
          height: MediaQuery.of(context).size.height * 0.5,
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 56, color: AppColors.muted2),
                const SizedBox(height: 16),
                Text(title, style: const TextStyle(color: AppColors.text, fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 6),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 40),
                  child: Text(subtitle, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _OrderCard extends StatelessWidget {
  final AppOrder order;
  final Future<void> Function() onChanged;
  const _OrderCard({required this.order, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final color = statusColor(order.status);
    final needs = order.needsAction;
    return Material(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => OrderDetailScreen(orderId: order.id)),
          );
          await onChanged();
        },
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: needs ? color.withValues(alpha: 0.35) : AppColors.border),
          ),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(12),
                ),
                alignment: Alignment.center,
                child: Text('#${order.id}',
                    style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 13)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(order.customer,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w700, fontSize: 15)),
                    const SizedBox(height: 3),
                    Row(
                      children: [
                        Text('₦${order.total}', style: const TextStyle(color: AppColors.muted, fontSize: 13, fontWeight: FontWeight.w600)),
                        const Text('  ·  ', style: TextStyle(color: AppColors.muted2)),
                        Flexible(
                          child: Text(order.statusLabel,
                              maxLines: 1, overflow: TextOverflow.ellipsis,
                              style: const TextStyle(color: AppColors.muted, fontSize: 13)),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              if (needs)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.16),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(order.action,
                      style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 11.5)),
                )
              else
                Text(order.age, style: const TextStyle(color: AppColors.muted2, fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }
}
