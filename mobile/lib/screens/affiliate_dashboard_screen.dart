import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import '../storage.dart';
import '../theme.dart';
import 'login_screen.dart';

/// Read-only earnings view for the "affiliate" role — a referrer sees what
/// they've accrued and what's already been paid, but there's nothing to
/// manage here: payouts are logged by an admin, not requested from the app.
class AffiliateDashboardScreen extends StatefulWidget {
  const AffiliateDashboardScreen({super.key});

  @override
  State<AffiliateDashboardScreen> createState() => _AffiliateDashboardScreenState();
}

class _AffiliateDashboardScreenState extends State<AffiliateDashboardScreen> {
  AffiliateSummary? _summary;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final client = await ApiClient.current();
      final summary = await client.getAffiliateSummary();
      if (mounted) setState(() { _summary = summary; _loading = false; _error = null; });
    } catch (e) {
      if (mounted) {
        setState(() => _loading = false);
        if (e is ApiException && e.code == 'unauthorized') {
          _logout();
        } else {
          setState(() => _error = e is ApiException ? e.friendly : 'Couldn’t load your earnings.');
        }
      }
    }
  }

  Future<void> _logout() async {
    await Storage.clearToken();
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  String _fmt(int n) => n.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');

  @override
  Widget build(BuildContext context) {
    final s = _summary;
    return Scaffold(
      extendBodyBehindAppBar: true,
      body: GlowBackground(
        child: SafeArea(
          child: RefreshIndicator(
            color: AppColors.emeraldBright,
            backgroundColor: AppColors.surface,
            onRefresh: _load,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
              children: [
                Row(
                  children: [
                    const BrandLogo(size: 44),
                    const SizedBox(width: 14),
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Affiliate earnings', style: TextStyle(color: AppColors.muted, fontSize: 13)),
                          Text('Your referrals',
                              style: TextStyle(color: AppColors.text, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: 'Sign out',
                      icon: const Icon(Icons.logout_rounded, color: AppColors.muted),
                      onPressed: _logout,
                    ),
                  ],
                ),
                const SizedBox(height: 22),
                if (_loading)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 40),
                    child: Center(child: CircularProgressIndicator(color: AppColors.emeraldBright)),
                  )
                else if (_error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    child: Center(child: Text(_error!, style: const TextStyle(color: AppColors.muted))),
                  )
                else if (s != null) ...[
                  Row(children: [
                    Expanded(child: _stat('Accrued', '₦${_fmt(s.accruedTotal)}', Icons.trending_up_rounded, AppColors.emeraldBright)),
                    const SizedBox(width: 12),
                    Expanded(child: _stat('Paid out', '₦${_fmt(s.paidTotal)}', Icons.check_circle_rounded, AppColors.muted)),
                  ]),
                  const SizedBox(height: 12),
                  _stat('Outstanding', '₦${_fmt(s.outstanding)}', Icons.hourglass_bottom_rounded, AppColors.gold, wide: true),
                  const SizedBox(height: 22),
                  _sectionLabel('Referred businesses'),
                  if (s.referredBusinesses.isEmpty)
                    _emptyCard('No businesses referred yet.')
                  else
                    for (final b in s.referredBusinesses) _businessRow(b),
                  const SizedBox(height: 22),
                  _sectionLabel('Payout history'),
                  if (s.payouts.isEmpty)
                    _emptyCard('No payouts logged yet — Collxct transfers manually and logs it here.')
                  else
                    for (final p in s.payouts) _payoutRow(p),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _sectionLabel(String t) => Padding(
        padding: const EdgeInsets.only(bottom: 10, top: 2),
        child: Text(t.toUpperCase(),
            style: const TextStyle(color: AppColors.muted, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 1)),
      );

  Widget _emptyCard(String text) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.border),
        ),
        child: Text(text, style: const TextStyle(color: AppColors.muted, fontSize: 13)),
      );

  Widget _businessRow(ReferredBusiness b) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(b.businessName, style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w700)),
                  if (b.referredAt != null)
                    Text('Referred ${b.referredAt!.split('T').first}', style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                ],
              ),
            ),
            Text('₦${_fmt(b.accrued)}', style: const TextStyle(color: AppColors.emeraldBright, fontWeight: FontWeight.w800)),
          ],
        ),
      );

  Widget _payoutRow(AffiliatePayoutEntry p) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('₦${_fmt(p.amount)}', style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w700)),
                  if (p.note != null && p.note!.isNotEmpty)
                    Text(p.note!, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                ],
              ),
            ),
            if (p.paidAt != null)
              Text(p.paidAt!.split('T').first, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
          ],
        ),
      );

  Widget _stat(String label, String value, IconData icon, Color color, {bool wide = false}) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.border),
          boxShadow: const [BoxShadow(color: Color(0x24000000), blurRadius: 16, offset: Offset(0, 6))],
        ),
        child: Row(
          mainAxisAlignment: wide ? MainAxisAlignment.start : MainAxisAlignment.spaceBetween,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(value, style: const TextStyle(color: AppColors.text, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.8)),
                const SizedBox(height: 2),
                Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 13)),
              ],
            ),
            if (wide) const SizedBox(width: 16),
            Container(
              width: 42, height: 42,
              decoration: BoxDecoration(color: color.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(12)),
              child: Icon(icon, color: color, size: 22),
            ),
          ],
        ),
      );
}
