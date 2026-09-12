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

  Future<void> _runAction(String action,
      {int? deliveryFee, bool acceptTerms = false, String? refundReason, int? riderId}) async {
    setState(() => _acting = true);
    try {
      final client = await ApiClient.current();
      final updated = await client.doAction(widget.orderId, action,
          deliveryFee: deliveryFee, acceptTerms: acceptTerms, refundReason: refundReason, riderId: riderId);
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

  Future<void> _cancel() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Cancel this order?', style: TextStyle(color: AppColors.text)),
        content: const Text('This clears the order and can’t be undone — use it for abandoned or stale orders.',
            style: TextStyle(color: AppColors.muted)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep it', style: TextStyle(color: AppColors.muted))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Cancel order', style: TextStyle(color: AppColors.danger, fontWeight: FontWeight.w700))),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _acting = true);
    try {
      final client = await ApiClient.current();
      await client.doAction(widget.orderId, 'cancel');
      if (mounted) {
        _toast('Order cancelled.');
        Navigator.pop(context);
      }
    } on ApiException catch (e) {
      _toast(e.friendly);
    } catch (_) {
      _toast('Couldn’t cancel.');
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Widget _cancelButton(AppOrder order) => Padding(
        padding: const EdgeInsets.only(top: 4),
        child: SizedBox(
          height: 50,
          child: OutlinedButton.icon(
            onPressed: _acting ? null : _cancel,
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.dangerSoft,
              side: BorderSide(color: AppColors.danger.withValues(alpha: 0.4)),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            icon: const Icon(Icons.cancel_outlined, size: 18),
            label: const Text('Cancel order', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ),
      );

  /// Pricing an order is the point of no return: it bills the customer and
  /// commits the business to fulfilling (or refunding) it. So the confirm stays
  /// disabled until the liability notice is ticked, and the acceptance is sent
  /// with the fee for the server to record against the order.
  Future<void> _promptDeliveryFee(AppOrder order) async {
    final hasSuggestion = order.deliveryFee > 0;
    final controller = TextEditingController(text: hasSuggestion ? order.deliveryFee.toString() : '');
    var accepted = false;
    RiderOption? selectedRider;
    List<RiderOption> riders = [];
    try {
      final client = await ApiClient.current();
      riders = await client.getRiders();
    } catch (_) {
      // Non-fatal: the rider picker just won't show. Pricing still works.
    }
    if (!mounted) return;
    final result = await showDialog<(int, int?)>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: AppColors.surface,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          title: const Text('Set delivery fee', style: TextStyle(color: AppColors.text)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (hasSuggestion) ...[
                const Text(
                  '📍 Suggested from the customer\'s address — review and adjust if needed.',
                  style: TextStyle(color: AppColors.muted, fontSize: 12.5, height: 1.4),
                ),
                const SizedBox(height: 10),
              ],
              TextField(
                controller: controller,
                autofocus: true,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(prefixText: '₦ ', hintText: 'e.g. 500'),
              ),
              if (riders.isNotEmpty) ...[
                const SizedBox(height: 14),
                DropdownButtonFormField<RiderOption?>(
                  initialValue: selectedRider,
                  decoration: const InputDecoration(labelText: 'Pay delivery fee to a rider? (optional)'),
                  items: [
                    const DropdownMenuItem<RiderOption?>(value: null, child: Text('No — keep it with my payout')),
                    for (final r in riders) DropdownMenuItem<RiderOption?>(value: r, child: Text(r.name)),
                  ],
                  onChanged: (v) => setLocal(() => selectedRider = v),
                ),
              ],
              const SizedBox(height: 16),
              InkWell(
                onTap: () => setLocal(() => accepted = !accepted),
                borderRadius: BorderRadius.circular(12),
                child: Container(
                  padding: const EdgeInsets.fromLTRB(8, 10, 12, 10),
                  decoration: BoxDecoration(
                    border: Border.all(color: AppColors.border),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 24,
                        height: 24,
                        child: Checkbox(
                          value: accepted,
                          onChanged: (v) => setLocal(() => accepted = v ?? false),
                          activeColor: AppColors.emeraldBright,
                          side: const BorderSide(color: AppColors.muted),
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Text(
                          'Pricing this order accepts it. Once the customer pays, refunds for '
                          'it are mine to make — the money settles to my bank, not Collxct’s.',
                          style: TextStyle(color: AppColors.muted, fontSize: 12.5, height: 1.4),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel', style: TextStyle(color: AppColors.muted))),
            TextButton(
              onPressed: accepted
                  ? () {
                      final fee = int.tryParse(controller.text.trim());
                      Navigator.pop(ctx, fee != null ? (fee, selectedRider?.id) : null);
                    }
                  : null,
              child: Text(
                'Accept & send',
                style: TextStyle(
                  color: accepted
                      ? AppColors.emeraldBright
                      : AppColors.muted.withValues(alpha: 0.45),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
      ),
    );
    if (result != null) {
      _runAction('set_delivery_fee', deliveryFee: result.$1, acceptTerms: true, riderId: result.$2);
    }
  }

  Future<void> _promptRefund(AppOrder order) async {
    final reason = TextEditingController();
    final breakdown = order.refund;
    final refundable = breakdown?.refundable ?? order.total;
    final retained = breakdown?.retainedServiceFee ?? 0;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Refund this order?', style: TextStyle(color: AppColors.text)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              breakdown == null
                  ? 'This refunds ₦$refundable (items + delivery).'
                  : 'This refunds ₦$refundable (items + delivery) of the '
                      '₦${breakdown.customerPaid} the customer paid.',
              style: const TextStyle(color: AppColors.muted, height: 1.4),
            ),
            if (retained > 0) ...[
              const SizedBox(height: 8),
              Text(
                'The ₦$retained service fee isn’t refunded — it covers messages already '
                'sent. Our commission is reversed.',
                style: const TextStyle(color: AppColors.muted, fontSize: 12.5, height: 1.4),
              ),
            ],
            const SizedBox(height: 12),
            const Text(
              'You send the money. The payment settled to your bank, so Collxct can’t '
              'return it for you — this records the refund and tells the customer to '
              'expect it from you.',
              style: TextStyle(color: AppColors.gold, fontSize: 12.5, height: 1.4),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: reason,
              maxLength: 200,
              decoration: const InputDecoration(hintText: 'Reason (optional)', counterText: ''),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Close', style: TextStyle(color: AppColors.muted))),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Record refund',
                style: TextStyle(color: AppColors.dangerSoft, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    if (ok == true) _runAction('refund', refundReason: reason.text);
  }

  Widget _refundButton() => Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 12),
        child: SizedBox(
          height: 50,
          child: OutlinedButton.icon(
            onPressed: _acting
                ? null
                : () async {
                    final order = await _future;
                    if (mounted) _promptRefund(order);
                  },
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.dangerSoft,
              side: BorderSide(color: AppColors.danger.withValues(alpha: 0.4)),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            icon: const Icon(Icons.currency_exchange_rounded, size: 18),
            label: const Text('Refund order', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ),
      );

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
                  if (order.isRefunded) ...[
                    const SizedBox(height: 14),
                    _card('Refund', [
                      _row('Refunded', '₦${order.refundAmount}', strong: true),
                      if (order.refundReason != null && order.refundReason!.isNotEmpty)
                        _row('Reason', order.refundReason!),
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text(
                          'You send this to the customer directly — Collxct never held it.',
                          style: TextStyle(color: AppColors.muted, fontSize: 12.5, height: 1.4),
                        ),
                      ),
                    ]),
                  ],
                  const SizedBox(height: 24),
                  ..._actionButtons(order),
                  if (order.availableActions.contains('refund')) _refundButton(),
                  if (order.canCancel) _cancelButton(order),
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
    // Refund is always optional and gets its own quieter button, so it must not
    // sit in the primary column or count towards "nothing left to do".
    final primary = order.availableActions.where((a) => a != 'refund').toList();
    if (primary.isEmpty) {
      return [
        Center(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Text(
              order.isRefunded ? 'This order was refunded.' : 'No further action needed.',
              style: const TextStyle(color: AppColors.muted),
            ),
          ),
        ),
      ];
    }
    return primary.map((action) {
      final label = actionLabels[action] ?? action;
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: GradientButton(
          label: label,
          busy: _acting,
          icon: _actionIcon(action),
          onPressed: _acting
              ? null
              : () => action == 'set_delivery_fee' ? _promptDeliveryFee(order) : _runAction(action),
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
      case 'refund':
        return Icons.currency_exchange_rounded;
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
