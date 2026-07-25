import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../theme.dart';
import 'item_edit_screen.dart';

class CatalogueScreen extends StatefulWidget {
  const CatalogueScreen({super.key});

  @override
  State<CatalogueScreen> createState() => _CatalogueScreenState();
}

class _CatalogueScreenState extends State<CatalogueScreen> {
  late Future<({List<CatalogueCategory> categories, List<CatalogueItem> items})> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<({List<CatalogueCategory> categories, List<CatalogueItem> items})> _load() async {
    final client = await ApiClient.current();
    return client.getCatalogue();
  }

  Future<void> _refresh() async {
    final f = _load();
    setState(() => _future = f);
    await f;
  }

  Future<void> _openEditor({CatalogueItem? item, required List<CatalogueCategory> categories}) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => ItemEditScreen(item: item, categories: categories)),
    );
    if (changed == true) _refresh();
  }

  Future<void> _addCategory() async {
    final controller = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('New category', style: TextStyle(color: AppColors.text)),
        content: TextField(controller: controller, autofocus: true, decoration: const InputDecoration(hintText: 'e.g. Dresses, Drinks')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: AppColors.muted))),
          TextButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Add', style: TextStyle(color: AppColors.emeraldBright, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    if (name == null || name.isEmpty) return;
    try {
      final client = await ApiClient.current();
      await client.createCategory(name);
      _refresh();
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Couldn’t add category.')));
    }
  }

  Future<void> _toggleStock(CatalogueItem item, bool outOfStock) async {
    try {
      final client = await ApiClient.current();
      await client.setItemStock(item.id, outOfStock);
      _refresh();
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Couldn’t update stock.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: const Text('Catalogue'),
        actions: [
          IconButton(tooltip: 'Add category', icon: const Icon(Icons.create_new_folder_outlined), onPressed: _addCategory),
          const SizedBox(width: 4),
        ],
      ),
      floatingActionButton: FutureBuilder(
        future: _future,
        builder: (context, snap) {
          final cats = snap.hasData ? snap.data!.categories : <CatalogueCategory>[];
          return FloatingActionButton.extended(
            backgroundColor: AppColors.emerald,
            foregroundColor: AppColors.onEmerald,
            icon: const Icon(Icons.add),
            label: const Text('Add item', style: TextStyle(fontWeight: FontWeight.w700)),
            onPressed: () => _openEditor(categories: cats),
          );
        },
      ),
      body: GlowBackground(
        child: SafeArea(
          child: RefreshIndicator(
            color: AppColors.emeraldBright,
            backgroundColor: AppColors.surface,
            onRefresh: _refresh,
            child: FutureBuilder(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator(color: AppColors.emeraldBright));
                }
                if (snap.hasError) {
                  return _msg('Couldn’t load your catalogue. Pull down to retry.');
                }
                final data = snap.data!;
                final items = data.items;
                if (items.isEmpty) {
                  return _msg('No items yet.\nTap “Add item” to build your catalogue.');
                }
                final catName = {for (final c in data.categories) c.id: c.name};
                return ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (_, i) => _ItemCard(
                    item: items[i],
                    categoryName: items[i].categoryId != null ? catName[items[i].categoryId] : null,
                    onTap: () => _openEditor(item: items[i], categories: data.categories),
                    onStock: (v) => _toggleStock(items[i], v),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget _msg(String text) => ListView(children: [
        SizedBox(
          height: MediaQuery.of(context).size.height * 0.55,
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Text(text, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
            ),
          ),
        ),
      ]);
}

class _ItemCard extends StatelessWidget {
  final CatalogueItem item;
  final String? categoryName;
  final VoidCallback onTap;
  final ValueChanged<bool> onStock;
  const _ItemCard({required this.item, required this.categoryName, required this.onTap, required this.onStock});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(16), border: Border.all(color: AppColors.border)),
          child: Row(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: item.imageUrl != null
                    ? Image.network(item.imageUrl!, width: 56, height: 56, fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => _placeholder())
                    : _placeholder(),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w700, fontSize: 15)),
                    const SizedBox(height: 2),
                    Text('₦${item.price}${categoryName != null ? '  ·  $categoryName' : ''}',
                        style: const TextStyle(color: AppColors.muted, fontSize: 13)),
                    const SizedBox(height: 6),
                    Row(children: [
                      if (!item.isActive) _badge('Hidden', AppColors.muted),
                      if (item.isOutOfStock) _badge('Out of stock', AppColors.danger),
                    ]),
                  ],
                ),
              ),
              Column(
                children: [
                  const Text('In stock', style: TextStyle(color: AppColors.muted2, fontSize: 10)),
                  Switch(value: !item.isOutOfStock, onChanged: (v) => onStock(!v)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _placeholder() => Container(
        width: 56, height: 56, color: AppColors.surface2,
        child: const Icon(Icons.image_outlined, color: AppColors.muted2),
      );

  Widget _badge(String text, Color color) => Container(
        margin: const EdgeInsets.only(right: 6),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(color: color, fontSize: 10.5, fontWeight: FontWeight.w700)),
      );
}
