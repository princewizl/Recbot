# iOS build & TestFlight — what you need to do

The Flutter code is shared, so the app itself is done. iOS just needs Apple
account setup + a cloud Mac to build. **You cannot build iOS on Windows** — we
use Codemagic (see `../codemagic.yaml`) so you never need to own a Mac.

## Prerequisites (the long pole is Apple)
1. **Apple Developer Program** — $99/year, https://developer.apple.com/programs/.
   Individual enrolment is usually approved in 1–2 days. (Push, TestFlight, and
   submission all require this — the free tier can't do push.)
2. **App Store Connect record** — create an app with bundle id
   `com.collxct.recbot`.

## Firebase for iOS (no Mac needed)
3. Firebase console → project `recbot-10775` → **Add app → iOS**, bundle id
   `com.collxct.recbot`. Download **`GoogleService-Info.plist`**.
4. Apple Developer portal → Keys → create an **APNs Auth Key (.p8)**. Upload it
   in Firebase → Project settings → **Cloud Messaging → Apple app configuration**
   (with your Key ID + Team ID). This is what lets FCM deliver to iPhones.
5. In the Apple Developer portal, enable the **Push Notifications** capability
   for App ID `com.collxct.recbot`.

## Build via Codemagic (cloud Mac → TestFlight)
6. Sign up at codemagic.io, connect this repo. It auto-detects `codemagic.yaml`.
7. In the app's Codemagic settings, add:
   - **App Store Connect API key** (Issuer ID + Key ID + .p8) — for signing &
     TestFlight upload.
   - Environment variable **`GOOGLE_SERVICE_INFO_PLIST`** (group `firebase`,
     secure) = base64 of the `GoogleService-Info.plist` from step 3.
     (`base64 -w0 GoogleService-Info.plist` on Linux/Mac, or
     `[Convert]::ToBase64String([IO.File]::ReadAllBytes("GoogleService-Info.plist"))`
     in PowerShell.)
8. Run the **`ios-testflight`** workflow. It builds, signs, and uploads to
   TestFlight (~15–30 min).

## Test on your iPhone
9. Install **TestFlight** from the App Store, sign in with your Apple ID (added
   as an internal tester in App Store Connect), and install the build. Internal
   builds appear minutes after processing, no review.
10. Real push only works on a **physical iPhone** (the Simulator can't receive
    real FCM/APNs pushes).

## App Store submission notes (when you're ready to go public)
- **Account deletion** (Guideline 5.1.1(v)): because the app has login, Apple
  requires an in-app way to delete the account. Plan to add one.
- Provide a **reviewer demo login** (a working business-owner account).
- **Privacy policy** URL + App Privacy labels (declare: email, device push
  token, order data).
- **No purchase UI in the app** — keep billing on the web (Paystack) to stay
  clear of Apple's in-app-purchase rules.
- Sign in with Apple is **not** required (no third-party social login).

## Local note
`ios/Runner/Info.plist` already declares the `remote-notification` background
mode, and `ios/Runner/Runner.entitlements` has `aps-environment`. Enabling the
Push Notifications capability during signing (Codemagic/Xcode) flips it to
`production` for release builds.
