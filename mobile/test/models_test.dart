import 'package:flutter_test/flutter_test.dart';
import 'package:recbot/models.dart';

// Pure-Dart unit tests (no plugins), safe to run in CI (Codemagic `flutter test`).
void main() {
  test('AppOrder.fromJson parses items, totals, and actions', () {
    final order = AppOrder.fromJson({
      'id': 7,
      'business_id': 2,
      'business': 'Collxct',
      'customer': 'Ada',
      'customer_phone': '2348012345678',
      'address': '12 Marina Road',
      'items': [
        {'name': 'Jollof Rice', 'qty': 2, 'price': 1500},
      ],
      'subtotal': 3000,
      'delivery_fee': 500,
      'total': 3500,
      'status': 'awaiting_delivery_fee',
      'status_label': 'Awaiting delivery fee',
      'action': 'Set delivery fee',
      'available_actions': ['set_delivery_fee'],
      'age': '2m',
    });

    expect(order.id, 7);
    expect(order.items.single.name, 'Jollof Rice');
    expect(order.items.single.qty, 2);
    expect(order.total, 3500);
    expect(order.needsAction, isTrue);
    expect(order.availableActions, contains('set_delivery_fee'));
  });

  test('an order out for delivery is not in the needs-action state', () {
    final order = AppOrder.fromJson({
      'id': 9,
      'business_id': 2,
      'business': 'Collxct',
      'customer': 'Ada',
      'customer_phone': '2348012345678',
      'address': '12 Marina Road',
      'items': const [],
      'subtotal': 3000,
      'delivery_fee': 500,
      'total': 3500,
      'status': 'out_for_delivery',
      'status_label': 'Out for delivery',
      'action': '',
      'available_actions': ['mark_delivered'],
      'age': '10m',
    });

    expect(order.needsAction, isFalse);
    expect(order.availableActions, contains('mark_delivered'));
  });
}
