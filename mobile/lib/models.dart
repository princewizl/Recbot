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
  final String age;

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
    required this.age,
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
        age: (json['age'] ?? '').toString(),
      );

  // True whenever the business still has something to do on this order — set the
  // fee, confirm payment, dispatch, or mark delivered. (awaiting_payment waits on
  // the customer, so it has no action.)
  bool get needsAction => availableActions.isNotEmpty;
}

/// Human labels for the action verbs the backend accepts.
const Map<String, String> actionLabels = {
  'set_delivery_fee': 'Set delivery fee',
  'mark_paid': 'Confirm payment',
  'dispatch': 'Mark dispatched',
  'mark_delivered': 'Mark delivered',
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
