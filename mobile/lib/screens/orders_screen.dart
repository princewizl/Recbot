import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../theme.dart';
import 'order_detail_screen.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> with WidgetsBindingObserver {
  late Future<List<AppOrder>> _future;
  bool _activeOnly = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _future = _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<List<AppOrder>> _load() async {
    final client = await ApiClient.current();
    return client.listOrders(scope: _activeOnly ? 'active' : '');
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() => _future = future);
    await future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(title: const Text('Orders')),
      body: GlowBackground(
        child: SafeArea(
          child: Column(
            children: [
              const SizedBox(height: 4),
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
                        return _emptyState(Icons.wifi_off_rounded,
                            'Couldn’t load orders', err is ApiException ? err.friendly : 'Pull down to retry.');
                      }
                      final orders = snapshot.data ?? [];
                      if (orders.isEmpty) {
                        return _emptyState(
                          _activeOnly ? Icons.check_circle_outline_rounded : Icons.receipt_long_outlined,
                          _activeOnly ? 'No active orders' : 'No recent orders',
                          _activeOnly
                              ? 'Orders in progress show here until they’re delivered. 🎉'
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
          _filterPill('Active', true),
          _filterPill('All', false),
        ],
      ),
    );
  }

  Widget _filterPill(String label, bool value) {
    final selected = _activeOnly == value;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          if (_activeOnly != value) {
            setState(() {
              _activeOnly = value;
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
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => OrderDetailScreen(orderId: order.id)),
          );
          await onChanged();
        },
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: needs ? color.withValues(alpha: 0.35) : AppColors.border),
            boxShadow: const [BoxShadow(color: Color(0x2B000000), blurRadius: 16, offset: Offset(0, 6))],
          ),
          clipBehavior: Clip.antiAlias,
          child: Row(
            children: [
              // Status accent stripe down the left edge.
              Container(width: 4, height: 68, color: color.withValues(alpha: needs ? 0.9 : 0.4)),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(order.customer,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w700, fontSize: 15.5, letterSpacing: -0.2)),
                          ),
                          const SizedBox(width: 10),
                          Text('₦${order.total}',
                              style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w800, fontSize: 15.5)),
                        ],
                      ),
                      const SizedBox(height: 7),
                      Row(
                        children: [
                          Text('#${order.id}', style: const TextStyle(color: AppColors.muted2, fontSize: 12, fontWeight: FontWeight.w600)),
                          const Text('   ·   ', style: TextStyle(color: AppColors.muted2, fontSize: 12)),
                          Expanded(
                            child: Text(order.statusLabel,
                                maxLines: 1, overflow: TextOverflow.ellipsis,
                                style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w600)),
                          ),
                          const SizedBox(width: 8),
                          if (needs)
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                              decoration: BoxDecoration(color: color.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(20)),
                              child: Text(order.action, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 11)),
                            )
                          else
                            Text(order.age, style: const TextStyle(color: AppColors.muted2, fontSize: 11.5)),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
