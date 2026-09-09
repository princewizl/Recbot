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

  test('a refunded order parses its breakdown and stops asking for action', () {
    final order = AppOrder.fromJson({
      'id': 11,
      'business_id': 2,
      'business': 'Collxct',
      'customer': 'Ada',
      'customer_phone': '2348012345678',
      'address': '12 Marina Road',
      'items': const [],
      'subtotal': 3000,
      'delivery_fee': 500,
      'total': 3500,
      'status': 'refunded',
      'status_label': 'Refunded',
      'action': '',
      'available_actions': const [],
      'age': '1h',
      'refund': {
        'refundable': 3500,
        'retained_service_fee': 90,
        'customer_paid': 3590,
        'commission_reversed': 70,
      },
      'refund_amount': 3500,
      'refund_reason': 'Kitchen ran out',
      'refunded_at': '2026-09-09T10:00:00',
      'terms_accepted_at': '2026-09-09T09:00:00',
    });

    expect(order.isRefunded, isTrue);
    expect(order.needsAction, isFalse);
    expect(order.refundAmount, 3500);
    expect(order.refundReason, 'Kitchen ran out');
    expect(order.termsAcceptedAt, isNotNull);
    expect(order.refund!.refundable, 3500);
    expect(order.refund!.retainedServiceFee, 90);
    expect(order.refund!.customerPaid, 3590);
  });

  test('refund is offered on a delivered order without flagging it as pending', () {
    final order = AppOrder.fromJson({
      'id': 12,
      'business_id': 2,
      'business': 'Collxct',
      'customer': 'Ada',
      'customer_phone': '2348012345678',
      'address': '12 Marina Road',
      'items': const [],
      'subtotal': 3000,
      'delivery_fee': 500,
      'total': 3500,
      'status': 'delivered',
      'status_label': 'Delivered',
      'action': '',
      'available_actions': const ['refund'],
      'age': '3h',
    });

    // A finished order must not nag the owner just because it can be refunded.
    expect(order.needsAction, isFalse);
    expect(order.availableActions, contains('refund'));
    expect(order.refund, isNull);
  });

  test('only the two blocked-on-business statuses need action', () {
    Map<String, dynamic> base(String status, List<String> actions) => {
          'id': 1,
          'business_id': 2,
          'business': 'Collxct',
          'customer': 'Ada',
          'customer_phone': '2348012345678',
          'address': '12 Marina Road',
          'items': const [],
          'subtotal': 0,
          'delivery_fee': 0,
          'total': 0,
          'status': status,
          'status_label': status,
          'action': '',
          'available_actions': actions,
          'age': '1m',
        };

    expect(AppOrder.fromJson(base('awaiting_delivery_fee', ['set_delivery_fee'])).needsAction, isTrue);
    expect(AppOrder.fromJson(base('payment_claimed', ['mark_paid'])).needsAction, isTrue);
    // Waiting on the customer, not on us.
    expect(AppOrder.fromJson(base('awaiting_payment', ['mark_paid'])).needsAction, isFalse);
    expect(AppOrder.fromJson(base('paid', ['dispatch', 'refund'])).needsAction, isFalse);
  });
}
