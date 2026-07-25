import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../models.dart';
import '../theme.dart';

class ItemEditScreen extends StatefulWidget {
  final CatalogueItem? item; // null = create
  final List<CatalogueCategory> categories;
  const ItemEditScreen({super.key, this.item, required this.categories});

  @override
  State<ItemEditScreen> createState() => _ItemEditScreenState();
}

class _ItemEditScreenState extends State<ItemEditScreen> {
  late final TextEditingController _name;
  late final TextEditingController _price;
  late final TextEditingController _desc;
  int? _categoryId;
  late bool _active;
  late bool _outOfStock;
  String? _newImagePath; // freshly picked photo
  bool _busy = false;

  bool get _isEdit => widget.item != null;

  @override
  void initState() {
    super.initState();
    final it = widget.item;
    _name = TextEditingController(text: it?.name ?? '');
    _price = TextEditingController(text: it != null ? it.price.toString() : '');
    _desc = TextEditingController(text: it?.description ?? '');
    _categoryId = it?.categoryId;
    _active = it?.isActive ?? true;
    _outOfStock = it?.isOutOfStock ?? false;
  }

  @override
  void dispose() {
    _name.dispose();
    _price.dispose();
    _desc.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: AppColors.surface,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined, color: AppColors.emeraldBright),
              title: const Text('Take a photo', style: TextStyle(color: AppColors.text)),
              onTap: () => Navigator.pop(ctx, ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined, color: AppColors.emeraldBright),
              title: const Text('Choose from gallery', style: TextStyle(color: AppColors.text)),
              onTap: () => Navigator.pop(ctx, ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    final picked = await ImagePicker().pickImage(source: source, maxWidth: 1400, imageQuality: 85);
    if (picked != null) setState(() => _newImagePath = picked.path);
  }

  Future<void> _save() async {
    final price = int.tryParse(_price.text.trim());
    if (_name.text.trim().isEmpty || price == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Enter a name and a valid price.')));
      return;
    }
    setState(() => _busy = true);
    try {
      final client = await ApiClient.current();
      await client.saveItem(
        id: widget.item?.id,
        name: _name.text.trim(),
        price: price,
        description: _desc.text.trim(),
        categoryId: _categoryId,
        isActive: _active,
        isOutOfStock: _outOfStock,
        imagePath: _newImagePath,
      );
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      _toast(e.friendly);
    } catch (_) {
      _toast('Couldn’t save. Check your connection.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        title: const Text('Delete item?', style: TextStyle(color: AppColors.text)),
        content: Text('“${widget.item!.name}” will be removed from your catalogue.', style: const TextStyle(color: AppColors.muted)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel', style: TextStyle(color: AppColors.muted))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete', style: TextStyle(color: AppColors.danger, fontWeight: FontWeight.w700))),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final client = await ApiClient.current();
      await client.deleteItem(widget.item!.id);
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      _toast('Couldn’t delete.');
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String m) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        title: Text(_isEdit ? 'Edit item' : 'New item'),
        actions: [
          if (_isEdit)
            IconButton(tooltip: 'Delete', icon: const Icon(Icons.delete_outline, color: AppColors.dangerSoft), onPressed: _busy ? null : _delete),
        ],
      ),
      body: GlowBackground(
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
            children: [
              _photoPicker(),
              const SizedBox(height: 18),
              TextField(controller: _name, decoration: const InputDecoration(labelText: 'Item name')),
              const SizedBox(height: 12),
              TextField(
                controller: _price,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Price', prefixText: '₦ '),
              ),
              const SizedBox(height: 12),
              TextField(controller: _desc, minLines: 2, maxLines: 4, decoration: const InputDecoration(labelText: 'Description (optional)')),
              const SizedBox(height: 12),
              DropdownButtonFormField<int?>(
                initialValue: _categoryId,
                dropdownColor: AppColors.surface2,
                decoration: const InputDecoration(labelText: 'Category'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('No category', style: TextStyle(color: AppColors.text))),
                  ...widget.categories.map((c) => DropdownMenuItem(value: c.id, child: Text(c.name, style: const TextStyle(color: AppColors.text)))),
                ],
                onChanged: (v) => setState(() => _categoryId = v),
              ),
              const SizedBox(height: 8),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Visible to customers', style: TextStyle(color: AppColors.text, fontSize: 14)),
                subtitle: const Text('Hidden items don’t show in the WhatsApp catalogue', style: TextStyle(color: AppColors.muted, fontSize: 12)),
                value: _active,
                onChanged: (v) => setState(() => _active = v),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Out of stock', style: TextStyle(color: AppColors.text, fontSize: 14)),
                value: _outOfStock,
                onChanged: (v) => setState(() => _outOfStock = v),
              ),
              const SizedBox(height: 20),
              GradientButton(label: _isEdit ? 'Save changes' : 'Add item', busy: _busy, onPressed: _busy ? null : _save),
            ],
          ),
        ),
      ),
    );
  }

  Widget _photoPicker() {
    Widget preview;
    if (_newImagePath != null) {
      preview = Image.file(File(_newImagePath!), fit: BoxFit.cover);
    } else if (widget.item?.imageUrl != null) {
      preview = Image.network(widget.item!.imageUrl!, fit: BoxFit.cover, errorBuilder: (_, __, ___) => _empty());
    } else {
      preview = _empty();
    }
    return GestureDetector(
      onTap: _pickPhoto,
      child: Container(
        height: 180,
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          fit: StackFit.expand,
          children: [
            preview,
            Positioned(
              right: 10,
              bottom: 10,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.55), borderRadius: BorderRadius.circular(20)),
                child: const Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.photo_camera_outlined, color: Colors.white, size: 16),
                  SizedBox(width: 6),
                  Text('Photo', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                ]),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _empty() => const ColoredBox(
        color: AppColors.surface2,
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.add_a_photo_outlined, color: AppColors.muted2, size: 32),
            SizedBox(height: 8),
            Text('Add a photo', style: TextStyle(color: AppColors.muted)),
          ]),
        ),
      );
}
