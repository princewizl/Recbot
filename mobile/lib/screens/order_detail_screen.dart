import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../theme.dart';

class OrderDetailScreen extends StatefulWidget {
  final int orderId;
  const OrderDetailScreen({super.key, required this.orderId});

  @override
  State<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends State<OrderDetailScreen> {
  late Future<AppOrder> _future;
  bool _acting = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<AppOrder> _load() async {
    final client = await ApiClient.current();
    return client.getOrder(widget.orderId);
  }

  Future<void> _runAction(String action, {int? deliveryFee}) async {
    setState(() => _acting = true);
    try {
      final client = await ApiClient.current();
      final updated = await client.doAction(widget.orderId, action, deliveryFee: deliveryFee);
      setState(() => _future = Future.value(updated));
      _toast('Done — ${updated.statusLabel}.');
    } on ApiException catch (e) {
      _toast(e.friendly);
    } catch (_) {
      _toast('Couldn’t reach the server.');
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  void _toast(String msg) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _promptDeliveryFee() async {
    final controller = TextEditingController();
    final fee = await showDialog<int>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Set delivery fee', style: TextStyle(color: AppColors.text)),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(prefixText: '₦ ', hintText: 'e.g. 500'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: AppColors.muted))),
          TextButton(
            onPressed: () => Navigator.pop(ctx, int.tryParse(controller.text.trim())),
            child: const Text('Send to customer', style: TextStyle(color: AppColors.emeraldBright, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    if (fee != null) _runAction('set_delivery_fee', deliveryFee: fee);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(title: Text('Order #${widget.orderId}')),
      body: GlowBackground(
        child: SafeArea(
          child: FutureBuilder<AppOrder>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Center(child: CircularProgressIndicator(color: AppColors.emeraldBright));
              }
              if (snapshot.hasError) {
                final err = snapshot.error;
                return Center(
                    child: Text(err is ApiException ? err.friendly : 'Failed to load.',
                        style: const TextStyle(color: AppColors.muted)));
              }
              final order = snapshot.data!;
              return ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
                children: [
                  _statusBanner(order),
                  const SizedBox(height: 14),
                  _card('Customer', [
                    _row('Name', order.customer),
                    _row('Phone', order.customerPhone),
                    _row('Deliver to', order.address),
                  ]),
                  const SizedBox(height: 14),
                  _card('Items', [
                    for (final it in order.items) _row('${it.qty} × ${it.name}', '₦${it.price * it.qty}'),
                    const Divider(color: AppColors.border, height: 20),
                    _row('Subtotal', '₦${order.subtotal}'),
                    _row('Delivery', '₦${order.deliveryFee}'),
                    _row('Total', '₦${order.total}', strong: true),
                  ]),
                  const SizedBox(height: 24),
                  ..._actionButtons(order),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _statusBanner(AppOrder order) {
    final color = statusColor(order.status);
    final needs = order.needsAction;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: color.withValues(alpha: 0.30)),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(color: color.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(12)),
            child: Icon(needs ? Icons.priority_high_rounded : Icons.check_circle_outline_rounded, color: color),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(order.statusLabel, style: TextStyle(fontWeight: FontWeight.w800, color: color, fontSize: 15)),
                const SizedBox(height: 2),
                Text('Updated ${order.age}', style: const TextStyle(color: AppColors.muted, fontSize: 12.5)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _actionButtons(AppOrder order) {
    if (order.availableActions.isEmpty) {
      return const [
        Center(
          child: Padding(
            padding: EdgeInsets.all(8),
            child: Text('No further action needed.', style: TextStyle(color: AppColors.muted)),
          ),
        ),
      ];
    }
    return order.availableActions.map((action) {
      final label = actionLabels[action] ?? action;
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: GradientButton(
          label: label,
          busy: _acting,
          icon: _actionIcon(action),
          onPressed: _acting
              ? null
              : () => action == 'set_delivery_fee' ? _promptDeliveryFee() : _runAction(action),
        ),
      );
    }).toList();
  }

  IconData _actionIcon(String action) {
    switch (action) {
      case 'set_delivery_fee':
        return Icons.local_shipping_outlined;
      case 'mark_paid':
        return Icons.payments_outlined;
      case 'dispatch':
        return Icons.delivery_dining_outlined;
      case 'mark_delivered':
        return Icons.task_alt_rounded;
      default:
        return Icons.check_rounded;
    }
  }

  Widget _card(String title, List<Widget> rows) => Container(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title.toUpperCase(),
                style: const TextStyle(color: AppColors.muted, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
            const SizedBox(height: 12),
            ...rows,
          ],
        ),
      );

  Widget _row(String label, String value, {bool strong = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 104,
              child: Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 13.5)),
            ),
            Expanded(
              child: Text(value,
                  style: TextStyle(
                    color: AppColors.text,
                    fontWeight: strong ? FontWeight.w800 : FontWeight.w500,
                    fontSize: strong ? 16 : 14,
                  )),
            ),
          ],
        ),
      );
}
