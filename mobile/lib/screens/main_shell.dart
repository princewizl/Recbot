import 'package:flutter/material.dart';

import '../theme.dart';
import 'business_config_screen.dart';
import 'catalogue_screen.dart';
import 'home_screen.dart';
import 'orders_screen.dart';

/// The signed-in app: four tabs behind a premium bottom nav.
class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _index = 0;
  late final List<Widget> _tabs = [
    HomeScreen(onGoToOrders: () => setState(() => _index = 1)),
    const OrdersScreen(),
    const CatalogueScreen(),
    const BusinessConfigScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: IndexedStack(index: _index, children: _tabs),
      bottomNavigationBar: _BottomNav(index: _index, onTap: (i) => setState(() => _index = i)),
    );
  }
}

class _BottomNav extends StatelessWidget {
  final int index;
  final ValueChanged<int> onTap;
  const _BottomNav({required this.index, required this.onTap});

  static const _items = <(IconData, String)>[
    (Icons.home_rounded, 'Home'),
    (Icons.receipt_long_rounded, 'Orders'),
    (Icons.inventory_2_rounded, 'Catalogue'),
    (Icons.tune_rounded, 'Settings'),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.bgElevated,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          child: Row(children: [for (int i = 0; i < _items.length; i++) _item(i)]),
        ),
      ),
    );
  }

  Widget _item(int i) {
    final selected = i == index;
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onTap(i),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          margin: const EdgeInsets.symmetric(horizontal: 4),
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(
            gradient: selected ? AppGradients.brand : null,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(_items[i].$1, size: 22, color: selected ? AppColors.onEmerald : AppColors.muted),
              const SizedBox(height: 3),
              Text(
                _items[i].$2,
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: selected ? AppColors.onEmerald : AppColors.muted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
