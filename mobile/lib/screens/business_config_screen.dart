import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';

class BusinessConfigScreen extends StatefulWidget {
  const BusinessConfigScreen({super.key});

  @override
  State<BusinessConfigScreen> createState() => _BusinessConfigScreenState();
}

class _BusinessConfigScreenState extends State<BusinessConfigScreen> {
  final _c = <String, TextEditingController>{};
  String _paymentMethod = 'bank_transfer';
  bool _autocalc = false;
  bool _loading = true;
  bool _busy = false;
  String? _error;

  static const _textFields = <String, String>{
    'name': 'Business name',
    'whatsapp_number': 'WhatsApp number',
    'owner_notify_number': 'Owner alert number (optional)',
    'bank_name': 'Bank name',
    'bank_account_number': 'Bank account number',
    'bank_account_name': 'Account holder name',
    'bank_code': 'Bank code (for payouts, e.g. 058)',
    'open_time': 'Opens at (HH:MM, blank = 24/7)',
    'close_time': 'Closes at (HH:MM)',
    'location_address': 'Pickup address (for delivery pricing)',
    'delivery_base_fee': 'Delivery base fee (₦)',
    'delivery_per_km': 'Delivery fee per km (₦)',
  };

  @override
  void initState() {
    super.initState();
    for (final k in _textFields.keys) {
      _c[k] = TextEditingController();
    }
    _load();
  }

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final client = await ApiClient.current();
      final cfg = await client.getBusinessConfig();
      for (final k in _textFields.keys) {
        _c[k]!.text = (cfg[k] ?? '').toString();
      }
      setState(() {
        _paymentMethod = (cfg['payment_method'] ?? 'bank_transfer').toString();
        _autocalc = cfg['delivery_autocalc'] == true;
        _loading = false;
      });
    } catch (_) {
      setState(() {
        _error = 'Couldn’t load your settings.';
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final client = await ApiClient.current();
      final data = <String, dynamic>{
        for (final k in _textFields.keys) k: _c[k]!.text.trim(),
        'payment_method': _paymentMethod,
        'delivery_autocalc': _autocalc,
        'delivery_base_fee': int.tryParse(_c['delivery_base_fee']!.text.trim()) ?? 0,
        'delivery_per_km': int.tryParse(_c['delivery_per_km']!.text.trim()) ?? 0,
      };
      await client.saveBusinessConfig(data);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Settings saved.')));
      }
    } on ApiException catch (e) {
      _toast(e.friendly);
    } catch (_) {
      _toast('Couldn’t save. Check your connection.');
    } finally {
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
      appBar: AppBar(title: const Text('Business settings')),
      body: GlowBackground(
        child: SafeArea(
          child: _loading
              ? const Center(child: CircularProgressIndicator(color: AppColors.emeraldBright))
              : _error != null
                  ? Center(child: Text(_error!, style: const TextStyle(color: AppColors.muted)))
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
                      children: [
                        _section('Business'),
                        _field('name'),
                        _field('whatsapp_number'),
                        _field('owner_notify_number'),
                        _section('Opening hours'),
                        Row(children: [Expanded(child: _field('open_time')), const SizedBox(width: 12), Expanded(child: _field('close_time'))]),
                        _section('Payments'),
                        DropdownButtonFormField<String>(
                          initialValue: _paymentMethod,
                          dropdownColor: AppColors.surface2,
                          decoration: const InputDecoration(labelText: 'How customers pay'),
                          items: const [
                            DropdownMenuItem(value: 'bank_transfer', child: Text('Bank transfer (manual)', style: TextStyle(color: AppColors.text))),
                            DropdownMenuItem(value: 'paystack', child: Text('Paystack (auto-confirmed)', style: TextStyle(color: AppColors.text))),
                          ],
                          onChanged: (v) => setState(() => _paymentMethod = v ?? 'bank_transfer'),
                        ),
                        const SizedBox(height: 12),
                        _field('bank_name'),
                        _field('bank_account_number'),
                        _field('bank_account_name'),
                        _field('bank_code'),
                        _section('Delivery'),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Auto-calculate delivery by distance', style: TextStyle(color: AppColors.text, fontSize: 14)),
                          value: _autocalc,
                          onChanged: (v) => setState(() => _autocalc = v),
                        ),
                        _field('location_address'),
                        Row(children: [Expanded(child: _field('delivery_base_fee')), const SizedBox(width: 12), Expanded(child: _field('delivery_per_km'))]),
                        const SizedBox(height: 22),
                        GradientButton(label: 'Save settings', busy: _busy, onPressed: _busy ? null : _save),
                      ],
                    ),
        ),
      ),
    );
  }

  Widget _section(String title) => Padding(
        padding: const EdgeInsets.only(top: 18, bottom: 8),
        child: Text(title.toUpperCase(),
            style: const TextStyle(color: AppColors.muted, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
      );

  Widget _field(String key) {
    final numeric = key == 'delivery_base_fee' || key == 'delivery_per_km';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: _c[key],
        keyboardType: numeric ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(labelText: _textFields[key]),
      ),
    );
  }
}
