// Data models mirroring the backend's JSON (see `order_to_json` in app/main.py).

class OrderItem {
  final String name;
  final int qty;
  final int price;

  OrderItem({required this.name, required this.qty, required this.price});

  factory OrderItem.fromJson(Map<String, dynamic> json) => OrderItem(
        name: (json['name'] ?? 'Item').toString(),
        qty: (json['qty'] ?? 1) as int,
        price: (json['price'] ?? 0) as int,
      );
}

/// What a refund on this order would return, and what it would not.
/// Mirrors `order_refund_breakdown` in app/main.py.
class RefundBreakdown {
  /// Items + delivery — the part the customer gets back.
  final int refundable;

  /// The service fee, kept because it recovers WhatsApp messages already sent.
  final int retainedServiceFee;

  /// Everything the customer paid, refundable + retained.
  final int customerPaid;

  /// Our commission, which is reversed on a refund.
  final int commissionReversed;

  const RefundBreakdown({
    required this.refundable,
    required this.retainedServiceFee,
    required this.customerPaid,
    required this.commissionReversed,
  });

  factory RefundBreakdown.fromJson(Map<String, dynamic> j) => RefundBreakdown(
        refundable: (j['refundable'] ?? 0) as int,
        retainedServiceFee: (j['retained_service_fee'] ?? 0) as int,
        customerPaid: (j['customer_paid'] ?? 0) as int,
        commissionReversed: (j['commission_reversed'] ?? 0) as int,
      );
}

class AppOrder {
  final int id;
  final int? businessId;
  final String business;
  final String customer;
  final String customerPhone;
  final String address;
  final List<OrderItem> items;
  final int subtotal;
  final int deliveryFee;
  final int total;
  final String status;
  final String statusLabel;
  final String action;
  final List<String> availableActions;
  final bool canCancel;
  final String age;
  final RefundBreakdown? refund;
  final int refundAmount;
  final String? refundReason;
  final String? refundedAt;

  /// When the business accepted this order (and its refund liability) by
  /// pricing the delivery. Null on orders priced before that was recorded.
  final String? termsAcceptedAt;

  AppOrder({
    required this.id,
    required this.businessId,
    required this.business,
    required this.customer,
    required this.customerPhone,
    required this.address,
    required this.items,
    required this.subtotal,
    required this.deliveryFee,
    required this.total,
    required this.status,
    required this.statusLabel,
    required this.action,
    required this.availableActions,
    required this.canCancel,
    required this.age,
    this.refund,
    this.refundAmount = 0,
    this.refundReason,
    this.refundedAt,
    this.termsAcceptedAt,
  });

  factory AppOrder.fromJson(Map<String, dynamic> json) => AppOrder(
        id: json['id'] as int,
        businessId: json['business_id'] as int?,
        business: (json['business'] ?? '').toString(),
        customer: (json['customer'] ?? '').toString(),
        customerPhone: (json['customer_phone'] ?? '').toString(),
        address: (json['address'] ?? '').toString(),
        items: ((json['items'] ?? []) as List)
            .map((e) => OrderItem.fromJson(e as Map<String, dynamic>))
            .toList(),
        subtotal: (json['subtotal'] ?? 0) as int,
        deliveryFee: (json['delivery_fee'] ?? 0) as int,
        total: (json['total'] ?? 0) as int,
        status: (json['status'] ?? '').toString(),
        statusLabel: (json['status_label'] ?? '').toString(),
        action: (json['action'] ?? '').toString(),
        availableActions:
            ((json['available_actions'] ?? []) as List).map((e) => e.toString()).toList(),
        canCancel: json['can_cancel'] == true,
        age: (json['age'] ?? '').toString(),
        refund: json['refund'] is Map<String, dynamic>
            ? RefundBreakdown.fromJson(json['refund'] as Map<String, dynamic>)
            : null,
        refundAmount: (json['refund_amount'] ?? 0) as int,
        refundReason: json['refund_reason'] as String?,
        refundedAt: json['refunded_at'] as String?,
        termsAcceptedAt: json['terms_accepted_at'] as String?,
      );

  /// Statuses where the order is blocked on the business rather than on the
  /// customer or the courier — the same two the backend flags in
  /// ACTION_NEEDED_STATUSES and returns from /api/action-required.
  ///
  /// Deliberately not "has any available action": refund is offered on paid,
  /// out-for-delivery and delivered orders, and a finished order must not
  /// nag the owner as though something were outstanding.
  static const Set<String> actionNeededStatuses = {'awaiting_delivery_fee', 'payment_claimed'};

  bool get needsAction => actionNeededStatuses.contains(status);

  bool get isRefunded => status == 'refunded';
}

/// Human labels for the action verbs the backend accepts.
const Map<String, String> actionLabels = {
  'set_delivery_fee': 'Set delivery fee',
  'mark_paid': 'Confirm payment',
  'dispatch': 'Mark dispatched',
  'mark_delivered': 'Mark delivered',
  'refund': 'Refund order',
};

class CatalogueCategory {
  final int id;
  final String name;
  CatalogueCategory({required this.id, required this.name});
  factory CatalogueCategory.fromJson(Map<String, dynamic> j) =>
      CatalogueCategory(id: j['id'] as int, name: (j['name'] ?? '').toString());
}

class CatalogueItem {
  final int id;
  final String name;
  final int price;
  final String description;
  final int? categoryId;
  final bool isActive;
  final bool isOutOfStock;
  final String? imageUrl;

  CatalogueItem({
    required this.id,
    required this.name,
    required this.price,
    required this.description,
    required this.categoryId,
    required this.isActive,
    required this.isOutOfStock,
    required this.imageUrl,
  });

  factory CatalogueItem.fromJson(Map<String, dynamic> j) => CatalogueItem(
        id: j['id'] as int,
        name: (j['name'] ?? '').toString(),
        price: (j['price'] ?? 0) as int,
        description: (j['description'] ?? '').toString(),
        categoryId: j['category_id'] as int?,
        isActive: j['is_active'] == true,
        isOutOfStock: j['is_out_of_stock'] == true,
        imageUrl: j['image_url'] as String?,
      );
}

/// A business's saved delivery rider — just enough to populate a picker when
/// pricing an order. Mirrors an entry in GET /api/riders.
class RiderOption {
  final int id;
  final String name;
  RiderOption({required this.id, required this.name});
  factory RiderOption.fromJson(Map<String, dynamic> j) =>
      RiderOption(id: j['id'] as int, name: (j['name'] ?? '').toString());
}

/// One business this affiliate referred, and what it's earned them so far.
/// Mirrors an entry in GET /api/affiliate/summary's `referred_businesses`.
class ReferredBusiness {
  final String businessName;
  final String? referredAt;
  final int accrued;

  ReferredBusiness({required this.businessName, required this.referredAt, required this.accrued});

  factory ReferredBusiness.fromJson(Map<String, dynamic> j) => ReferredBusiness(
        businessName: (j['business_name'] ?? '').toString(),
        referredAt: j['referred_at'] as String?,
        accrued: (j['accrued'] ?? 0) as int,
      );
}

/// One payout Collxct has already logged as paid to this affiliate.
class AffiliatePayoutEntry {
  final int amount;
  final String? note;
  final String? paidAt;

  AffiliatePayoutEntry({required this.amount, required this.note, required this.paidAt});

  factory AffiliatePayoutEntry.fromJson(Map<String, dynamic> j) => AffiliatePayoutEntry(
        amount: (j['amount'] ?? 0) as int,
        note: j['note'] as String?,
        paidAt: j['paid_at'] as String?,
      );
}

/// An affiliate's own earnings snapshot. Mirrors GET /api/affiliate/summary.
class AffiliateSummary {
  final int accruedTotal;
  final int paidTotal;
  final int outstanding;
  final List<ReferredBusiness> referredBusinesses;
  final List<AffiliatePayoutEntry> payouts;

  AffiliateSummary({
    required this.accruedTotal,
    required this.paidTotal,
    required this.outstanding,
    required this.referredBusinesses,
    required this.payouts,
  });

  factory AffiliateSummary.fromJson(Map<String, dynamic> j) => AffiliateSummary(
        accruedTotal: (j['accrued_total'] ?? 0) as int,
        paidTotal: (j['paid_total'] ?? 0) as int,
        outstanding: (j['outstanding'] ?? 0) as int,
        referredBusinesses: ((j['referred_businesses'] ?? []) as List)
            .map((e) => ReferredBusiness.fromJson(e as Map<String, dynamic>))
            .toList(),
        payouts: ((j['payouts'] ?? []) as List)
            .map((e) => AffiliatePayoutEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
