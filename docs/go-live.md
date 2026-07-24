# Recbot — deployment & app-store go-live

End-to-end checklist to take the backend to production and both apps live on the
Google Play Store and Apple App Store.

---

## Part 0 — Shared prerequisites (do these once)

Needed for **both** stores before you can submit:

- [ ] **Privacy Policy URL** — live at `https://collxct.com.ng:8443/privacy`
- [ ] **Terms of Use URL** — live at `https://collxct.com.ng:8443/terms`
      (Both were added to the web portal. Have a lawyer review the template text —
      see the note at the top of each page.)
- [ ] **App icon** — the app still uses the default Flutter icon. Design a
      512×512 icon (emerald/gold brand) before submitting. (`flutter_launcher_icons`
      makes this one command.)
- [ ] **Screenshots** — phone screenshots of the login, orders, and order screens
      (Play needs 2+, Apple needs a set per device size).
- [ ] **Account deletion** — both stores require apps with login to let users
      delete their account. Interim: the Privacy Policy documents email-based
      deletion. Recommended before public launch: add an in-app "Delete account"
      action.
- [ ] **Release signing keys** — the sideload APKs use the *debug* key, which the
      stores reject. Android needs an upload keystore; iOS signing is handled by
      Codemagic/Xcode. See each part below.

---

## Part 1 — Backend to production

The apps need the production backend (`collxct.com.ng:8443`) running this
branch's `/api/*` code + FCM. Full steps: **[push-deploy.md](push-deploy.md)**.
Summary:

```bash
scp secrets/firebase-service-account.json  user@server:/path/to/Recbot/secrets/
# server .env:  FCM_CREDENTIALS_FILE=/secrets/firebase-service-account.json
docker compose build recbot && docker compose up -d
docker compose logs recbot | grep -i push        # → "Push enabled..."
```

`device_tokens` and the `accepting_orders` column migrate automatically on boot.

---

## Part 2 — Android → Google Play Store

1. **Google Play Developer account** — one-time **$25**, https://play.google.com/console.
2. **Release signing** — create an upload keystore and wire it up
   (`android/key.properties` + `keystore`), then enable **Play App Signing**
   (Google holds the app signing key; you sign with the upload key).
3. **Build the App Bundle** (Play requires AAB, not APK):
   ```powershell
   C:\src\flutter\bin\flutter.bat build appbundle --release
   ```
   Output: `build/app/outputs/bundle/release/app-release.aab`.
4. **Create the app** in Play Console; fill the store listing (title, short +
   full description, screenshots, feature graphic, icon).
5. **Policy forms**: Data safety (declare email, push token, order/customer data),
   content rating questionnaire, target audience, privacy policy URL.
6. **Testing tracks**: upload the AAB to Internal testing → then Closed testing.
   ⚠️ **New personal developer accounts** (created after Nov 2023) must run a
   **closed test with at least 12 testers for 14 days** before they can promote
   to Production. Company/organization accounts are exempt. Plan for this delay.
7. **Submit to Production** → Google review (a few days, sometimes up to ~1–2 weeks
   for a first app).

Sideload testing meanwhile (no Play Store): share
`build/app/outputs/flutter-apk/app-release.apk` directly — already on your Desktop
as `recbot-release.apk`.

---

## Part 3 — iOS → Apple App Store

Full detail: **[../mobile/IOS-SETUP.md](../mobile/IOS-SETUP.md)**. Summary:

1. **Apple Developer Program** — **$99/year** (mandatory; the free tier can't do
   push). Individual enrolment ~1–2 days.
2. **Firebase iOS app** + `GoogleService-Info.plist`; create an **APNs Auth Key
   (.p8)** and upload it to Firebase (this is what lets FCM reach iPhones). No Mac
   needed for these.
3. **Build in the cloud with Codemagic** (`../codemagic.yaml`) — builds, signs,
   and uploads to TestFlight without you owning a Mac.
4. **TestFlight** — install on your iPhone (internal testers, no review, minutes
   after processing). Real push only works on a physical iPhone.
5. **Submit for review** — provide a reviewer demo login, privacy labels, privacy
   policy URL, and the account-deletion path. Review is usually 24–48h.

---

## Part 4 — Legal & compliance checklist

- [ ] Terms of Use published (`/terms`) and **reviewed by a lawyer**.
- [ ] Privacy Policy published (`/privacy`) and reviewed — covers Nigeria's NDPA
      2023 and GDPR-style rights for global users.
- [ ] Nigeria: if you process personal data at scale, check whether you must file
      with the **Nigeria Data Protection Commission (NDPC)** and/or appoint a DPO.
- [ ] Payment/refund terms accurate (Paystack; onboarding + subscription fees).
- [ ] Account & data deletion path in place (email now; in-app recommended).
- [ ] Store listings link the Privacy Policy URL (required by both stores).
- [ ] Push notifications are opt-in and transactional (they are).

---

## Part 5 — Costs & timeline at a glance

| Item | Cost | Time / notes |
|---|---|---|
| Google Play account | $25 once | instant; **+14-day / 12-tester** closed test for new personal accounts |
| Apple Developer | $99 / year | enrolment 1–2 days |
| Codemagic (iOS cloud build) | Free tier (~500 min/mo) | build 15–30 min |
| Backend deploy | — | minutes (docker compose) |
| Play review (first app) | — | days → ~1–2 weeks |
| Apple review | — | ~24–48h |
| Lawyer review of Terms/Privacy | varies | do before public launch |

**Fastest path to real testing without either store:** sideload
`recbot-release.apk` on Android now; TestFlight on iOS once the Apple account is live.
