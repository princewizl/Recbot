import 'package:flutter/material.dart';

/// Brand design system — mirrors the Recbot/Collxct web portal: a premium dark
/// "luxe fintech" look, emerald + gold on near-black, gradient CTAs and glows.
class AppColors {
  static const bg = Color(0xFF090C0B);
  static const bgElevated = Color(0xFF0E1412);
  static const surface = Color(0xFF141B18);
  static const surface2 = Color(0xFF1B2320);
  static const border = Color(0x14FFFFFF); // white @ 8%
  static const borderStrong = Color(0x26FFFFFF);

  static const text = Color(0xFFF1F5F3);
  static const muted = Color(0xFF8B9792);
  static const muted2 = Color(0xFF5E6A65);

  static const emerald = Color(0xFF10B981);
  static const emeraldBright = Color(0xFF34D399);
  static const emeraldDeep = Color(0xFF059669);
  static const onEmerald = Color(0xFF03130C);

  static const gold = Color(0xFFF59E0B);
  static const goldSoft = Color(0xFFFFD866);

  static const danger = Color(0xFFFF5E7A);
  static const dangerSoft = Color(0xFFFF8FA3);
}

class AppGradients {
  static const brand = LinearGradient(
    colors: [AppColors.emeraldBright, AppColors.emeraldDeep],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
  static const hero = LinearGradient(
    colors: [Color(0xFF0D2F24), Color(0xFF0A231C), Color(0xFF071710)],
    stops: [0, 0.48, 1],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
  static const headline = LinearGradient(
    colors: [AppColors.emeraldBright, AppColors.gold],
  );
}

ThemeData buildAppTheme() {
  const scheme = ColorScheme.dark(
    primary: AppColors.emerald,
    onPrimary: AppColors.onEmerald,
    secondary: AppColors.gold,
    onSecondary: AppColors.onEmerald,
    surface: AppColors.surface,
    onSurface: AppColors.text,
    error: AppColors.danger,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bg,
    canvasColor: AppColors.bg,
    splashColor: AppColors.emerald.withValues(alpha: 0.10),
    highlightColor: AppColors.emerald.withValues(alpha: 0.06),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      foregroundColor: AppColors.text,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: AppColors.text,
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
      ),
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    dividerColor: AppColors.border,
    textTheme: const TextTheme(
      headlineMedium: TextStyle(color: AppColors.text, fontWeight: FontWeight.w800, letterSpacing: -0.5),
      titleMedium: TextStyle(color: AppColors.text, fontWeight: FontWeight.w700),
      bodyMedium: TextStyle(color: AppColors.text),
      bodySmall: TextStyle(color: AppColors.muted),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface2,
      hintStyle: const TextStyle(color: AppColors.muted2),
      labelStyle: const TextStyle(color: AppColors.muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.emerald, width: 1.6),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: AppColors.surface2,
      contentTextStyle: const TextStyle(color: AppColors.text),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? AppColors.emeraldBright : AppColors.muted,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected)
            ? AppColors.emerald.withValues(alpha: 0.45)
            : AppColors.surface2,
      ),
    ),
  );
}

/// Maps an order status to a brand accent colour.
Color statusColor(String status) {
  switch (status) {
    case 'awaiting_delivery_fee':
    case 'payment_claimed':
      return AppColors.gold;
    case 'paid':
    case 'out_for_delivery':
      return AppColors.emeraldBright;
    case 'delivered':
      return AppColors.muted;
    default:
      return AppColors.muted; // awaiting_payment etc. — waiting on the customer
  }
}

/// Full-bleed dark background with two ambient brand glows (emerald + gold),
/// matching the web portal's radial-gradient backdrop.
class GlowBackground extends StatelessWidget {
  final Widget child;
  const GlowBackground({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(color: AppColors.bg),
      child: Stack(
        children: [
          Positioned(
            top: -160,
            left: -120,
            child: _glow(const Color(0xFF10B981), 340, 0.18),
          ),
          Positioned(
            top: -80,
            right: -140,
            child: _glow(const Color(0xFFF59E0B), 300, 0.08),
          ),
          child,
        ],
      ),
    );
  }

  Widget _glow(Color color, double size, double opacity) => IgnorePointer(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(
              colors: [color.withValues(alpha: opacity), color.withValues(alpha: 0)],
            ),
          ),
        ),
      );
}

/// The signature emerald gradient CTA.
class GradientButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final bool busy;
  final IconData? icon;
  const GradientButton({super.key, required this.label, this.onPressed, this.busy = false, this.icon});

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null && !busy;
    return Opacity(
      opacity: enabled ? 1 : 0.55,
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: AppGradients.brand,
          borderRadius: BorderRadius.circular(14),
          boxShadow: [
            BoxShadow(
              color: AppColors.emerald.withValues(alpha: 0.35),
              blurRadius: 22,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: enabled ? onPressed : null,
            child: Container(
              height: 52,
              alignment: Alignment.center,
              child: busy
                  ? const SizedBox(
                      height: 22, width: 22,
                      child: CircularProgressIndicator(strokeWidth: 2.2, color: AppColors.onEmerald),
                    )
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (icon != null) ...[
                          Icon(icon, color: AppColors.onEmerald, size: 20),
                          const SizedBox(width: 8),
                        ],
                        Text(label,
                            style: const TextStyle(
                                color: AppColors.onEmerald, fontWeight: FontWeight.w800, fontSize: 15)),
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Emerald→gold gradient text, for headline accents.
class GradientText extends StatelessWidget {
  final String text;
  final TextStyle style;
  const GradientText(this.text, {super.key, required this.style});

  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      shaderCallback: (bounds) => AppGradients.headline.createShader(Rect.fromLTWH(0, 0, bounds.width, bounds.height)),
      child: Text(text, style: style.copyWith(color: Colors.white)),
    );
  }
}

/// Rounded gradient app mark (bell in a squircle).
class BrandLogo extends StatelessWidget {
  final double size;
  const BrandLogo({super.key, this.size = 64});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        gradient: AppGradients.brand,
        borderRadius: BorderRadius.circular(size * 0.28),
        boxShadow: [
          BoxShadow(color: AppColors.emerald.withValues(alpha: 0.4), blurRadius: 28, offset: const Offset(0, 10)),
        ],
      ),
      child: Icon(Icons.notifications_active_rounded, color: AppColors.onEmerald, size: size * 0.5),
    );
  }
}
