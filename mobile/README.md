# Recbot Android app

A native Android client for business owners/staff. Its whole reason to exist is
**reliable push notifications** — a heads-up alert with sound the moment a new
order lands or an order needs action, even with the phone locked and the app
closed. It talks to the FastAPI backend over the JSON API under `/api/*`
(see `app/main.py`).

v1: sign in → see orders that need action (and all recent orders) → open an
order → act on it (set delivery fee, confirm payment, mark dispatched/delivered)
→ get pushed when something new arrives.

Only the app **source** (`lib/`, `pubspec.yaml`) is tracked in git. The generated
`android/` platform folder and `build/` are git-ignored and reproducible.

---

## Status on THIS machine (already set up)

The toolchain and project are fully configured here — you do **not** need to
redo any of this:

- **Flutter SDK** 3.44.7 at `C:\src\flutter` (on PATH for new terminals).
- **Android SDK** at `%LOCALAPPDATA%\Android\Sdk` with cmdline-tools, CMake
  3.22.1, NDK 28.2, platform-35/36, licenses accepted.
- **JDK** = Android Studio's bundled JBR 17 (`flutter config --jdk-dir`).
- **Android project generated** — `applicationId = com.collxct.recbot`.
- **Firebase** project `recbot-10775`: `android/app/google-services.json` is in
  place; the backend service-account key lives at
  `../secrets/firebase-service-account.json` (git-ignored) and `../.env` points
  `FCM_CREDENTIALS_FILE` at it. `firebase-admin` is installed in the backend venv.
- **A debug APK is built:** `build/app/outputs/flutter-apk/app-debug.apk`
  (also copied to your Desktop as `recbot-debug.apk`).

Commands below assume the full Flutter path since this shell may not have it on
PATH: use `C:\src\flutter\bin\flutter.bat` (a fresh terminal will just have
`flutter`).

## Build

```powershell
cd C:\Users\Olufemi\Documents\PROJECTS\Recbot\mobile

# Debug build, arm64 only (fast; covers all modern phones):
C:\src\flutter\bin\flutter.bat build apk --debug --target-platform android-arm64

# Release build for testers (smaller, all ABIs). Uses the debug signing key for
# now — fine for sideloading, not for the Play Store:
C:\src\flutter\bin\flutter.bat build apk --release
```

Output: `build/app/outputs/flutter-apk/app-debug.apk` (or `app-release.apk`).

## Install on a phone (no Play Store)

1. Copy `recbot-debug.apk` (on your Desktop) to the phone — WhatsApp to
   yourself, USB, Google Drive, email, whatever.
2. On the phone, tap it and allow **"Install unknown apps"** for whichever app
   is opening it.
3. Or, with the phone plugged in (USB debugging on):
   ```powershell
   C:\src\flutter\bin\flutter.bat install
   # or: %LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe install -r build\app\outputs\flutter-apk\app-debug.apk
   ```

## Test the notification end-to-end

The app must reach a backend that has this branch's `/api/*` code **and** FCM
configured. Three ways to arrange that:

- **Local backend, same Wi-Fi** — run the backend bound to all interfaces and
  point the app at your PC's LAN IP:
  ```powershell
  cd C:\Users\Olufemi\Documents\PROJECTS\Recbot
  $env:FCM_CREDENTIALS_FILE = "C:/Users/Olufemi/Documents/PROJECTS/Recbot/secrets/firebase-service-account.json"
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
  In the app's **Server address**, enter `http://<your-PC-LAN-IP>:8000`.
- **ngrok** — `ngrok http 8000`, use the HTTPS URL as the Server address (works
  off-Wi-Fi).
- **Deploy** this branch to the production server and set `FCM_CREDENTIALS_FILE`
  there; then the app's default address just works.

Then:

1. Sign in with a **business-owner** account that has a business (push is
   targeted per business; a bare admin has no business to target). Signing in
   registers the device — check the backend has a row in `device_tokens`.
2. Lock the phone / background the app.
3. Place an order to that business over WhatsApp (or drive the `/webhook` flow).
4. A heads-up notification with sound should arrive. Tapping it opens the order;
   the action buttons run the same operations as the web dashboard.

## Later: publish to the Play Store

Same code, different artifact:

```powershell
C:\src\flutter\bin\flutter.bat build appbundle --release
```

Before uploading you'll set up a real release signing key
(`android/key.properties` + keystore), an app icon, and a privacy policy.
Nothing about the app code changes.

---

## Setting up on a different machine

`flutter create` regenerates the platform folders, so a fresh checkout needs:

```bash
cd mobile
flutter create --org com.collxct --platforms=android .
```

Then re-apply what's captured here (all already done on this machine):

- **`android/app/build.gradle.kts`**: `minSdk = maxOf(flutter.minSdkVersion, 23)`;
  `isCoreLibraryDesugaringEnabled = true` in `compileOptions`; a `dependencies`
  block with `coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")`;
  and a conditional google-services apply at the end of the file.
- **`android/settings.gradle.kts`**: declare
  `id("com.google.gms.google-services") version "4.4.2" apply false`.
- **`android/app/src/main/AndroidManifest.xml`**: add `INTERNET` and
  `POST_NOTIFICATIONS` permissions. (INTERNET matters — Flutter only puts it in
  the debug manifest, so a release APK has no network without it.)
- **`android/gradle.properties`**: raised HTTP timeouts for slow links.
- Drop your own `android/app/google-services.json` from the Firebase console.

## Troubleshooting

- **`Read timed out` / `connection aborted` during a build** → slow/flaky link
  while Gradle fetches Flutter-engine or Firebase artifacts, or the SDK installs
  CMake/NDK. Just re-run the build; downloads resume and get cached. The raised
  timeouts in `gradle.properties` help.
- **Build wants CMake/NDK** → a transitive `jni` dependency triggers a native
  build. CMake 3.22.1 + NDK 28.2 are already installed here; elsewhere run
  `sdkmanager "cmake;3.22.1" "ndk;28.2.13676358"`.
- **App can't reach the server** → wrong URL for a phone (`localhost` = the
  phone), firewall, or backend not bound to `0.0.0.0`. Try the ngrok URL.
- **No notification** → confirm the backend boot log says push is enabled;
  confirm a `device_tokens` row exists; confirm `google-services.json` is at
  `android/app/`; on Android 13+ confirm the notification permission was granted.
