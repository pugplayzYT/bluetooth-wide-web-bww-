# Bluetooth-wide Web (BWW)

Publish a small HTML/CSS/JavaScript site on your computer and browse it from a paired Android phone, using Bluetooth Classic RFCOMM. No Wi-Fi or Internet is needed while using the app.

The project includes a Windows console server, a standalone ESP32 + SD card host, and a native Android browser/editor. See [the ESP32 setup and wiring guide](esp32/README.md) for the PlatformIO C++ firmware and your GPIO5/18/23/19 wiring. The server is the authority for accounts and domains. `bww://garden.bww` is unique **on that computer**, not globally across every Bluetooth server. Connect to another computer to explore its sites; accounts and sessions are separate on each computer.

## ESP32 upload crash patch

[Download ESP32 firmware 0.5.1 for PlatformIO](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-ESP32-PlatformIO-0.5.1.zip), extract it, open its `esp32` folder in VS Code, and click **Upload**. This patch reduces cleanup RAM use and checks memory headroom before opening SD files, addressing the observed upload-start allocation failure. Existing SD accounts/sites and the three-client/512 KiB defaults remain compatible. [Prebuilt binaries and matching crash-decoder ELF](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-ESP32-Binaries-0.5.1.zip) are also available. See [the firmware guide](esp32/README.md).

## Copy between your computer and ESP32 SD card

For Bluetooth sync without removing the SD card, [download the Windows sync tool](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-Windows-Sync-0.5.0.zip), update to [ESP32 firmware 0.5.0](esp32/README.md), and run **Sync-BWW.bat**. Select/pair the device, sign into the same username on both hosts, compare websites, choose directions, and approve the selected changes. See [the Bluetooth sync guide](SYNC_README.md).

[Download BWW SD Copy](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-SD-Copy.zip), extract it, and run **Run-BWW-SD-Copy.bat** on Windows (Python 3.10+). Choose your computer's `store.json`, the SD card drive, and a copy direction. The tool previews changes, backs up the destination, and converts accounts/sites into the correct format. It never formats the card. Stop both hosts before copying. See [the short copy-tool guide](BWW_SD_COPY_README.md).

## Use the built app

[Download Android app 0.5.0](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-Android-0.5.0.apk). This update adds Bluetooth reconnect attempts, saved publish uploads that continue through a background service, and loading/status feedback for publishing and opening the editor. See [reconnect and upload behavior](ANDROID_UPLOADS_README.md), including cancellation, conflict review and Android background limits. Existing PC/ESP32 hosts at 0.5.0 support safe automatic publish retries without another host update; older hosts can require review after an interrupted write. The app retains the authentication spinner and the temporary full-screen exit hint, top-edge swipe and top-edge double-tap exit, so in-game taps keep working. Install over your existing app to preserve its data.

Build outputs in this workspace:

- `artifacts/windows-x64/Bww.Server.exe`: self-contained Windows x64 server; .NET need not be installed to run it.
- `android/app/build/outputs/apk/debug/app-debug.apk`: installable Android development build, signed with a local debug key. Android 8 or newer is required. Distribution releases need your own stable release signing key; never publish that private key.

1. Copy the Windows executable to your Windows 10/11 computer with a Bluetooth Classic adapter. Open PowerShell in its folder and run `./Bww.Server.exe`. Wait for `READY Bluetooth`. Keep the console open while clients use the server.
2. Install the APK on the Android phone. You may need to allow installation from your chosen file manager. Keep Android System WebView updated.
3. Pair the phone with the computer using Android and Windows Bluetooth settings. Confirm the pairing code on both devices. The app lists already paired devices; it does not scan for unpaired devices.
4. Open **Bluetooth-wide Web**, tap **Connect**, grant Bluetooth permission, and choose the paired computer running the server.
5. Tap **Account → Register**. Choose a username and a password of at least 10 characters. The session is saved on the phone for that computer, for up to 30 days; passwords are not saved on the phone.
6. Tap **Create Site**, choose a domain, edit HTML, CSS, and JavaScript, then **Publish**. **Check domain** is advisory; publishing claims the name atomically and prevents another account overwriting it.
7. Type `bww://your-domain.bww` in the URL bar or tap **Sites**. Guests can browse published sites without registering. Use **My Sites** to edit or delete your own sites. Deletion asks for confirmation.

The server persists accounts, hashed session tokens, and sites in `%LOCALAPPDATA%\Bww\store.json`. Stop the server before backing up that file. To use another storage location, run `./Bww.Server.exe --data C:\path\store.json`. One server process may own a store at a time. Do not delete the store unless you intend to remove all accounts and sites. Sessions remain valid across server restarts; signing out revokes that session.

Tap **Full screen** to hide the app controls and system bars while viewing a website. The page keeps running without a reload. A brief “Swipe down from top to exit full screen” hint appears each time you enter, then disappears automatically. Swipe down from the top edge, double-tap the top edge, or press Android Back / Esc to return; Back exits full-screen before navigating away. HTML/video fullscreen requests use the same gesture. There is no persistent exit button or ugly overlay. Normal taps, double-taps during games, and scrolling continue reaching the page without accidentally exiting.

Editor drafts save locally as you type, separately by server and account. Reopening Create Site or the relevant existing site restores its draft. Publishing removes that draft; Close retains it; Discard draft removes it. A disconnected device can retain a draft, but publishing needs a live connection.

## Site format and boundaries

Each site contains three UTF-8 text assets: `index.html`, `style.css`, and `script.js`, limited to **512 KiB combined on Windows and ESP32**. The editor displays the connected host's limit. The browser automatically includes the CSS and JavaScript assets. HTML may be a full document or a fragment. Use data URLs for small images/fonts. Other paths, uploads, external scripts/images, fetch requests, forms, iframes, and Internet navigation are not supported in this version. Links between BWW domains load another site from the same server.

The WebView internally uses an intercepted HTTPS origin containing the site label and a stable identifier derived from the paired computer's Bluetooth address. This isolates browser storage by **computer and website**, while the visible URL remains `bww://domain.bww`. `.bww` does not resolve through Internet DNS. Site JavaScript runs inside the WebView with no native bridge or access to account tokens. Website local storage is retained across reconnects, app restarts, and switching between computers; the same domain on another computer has separate data. Local file access and content-provider access are disabled, and the app has no Internet permission. CSP restricts content to these local assets and inline scripts/styles. HTML and JavaScript are intentionally executable site content, not sanitized text.

Passwords use salted PBKDF2-SHA256 with 210,000 iterations. Session tokens are random 256-bit values; the server stores only their SHA-256 digest. Bluetooth uses the secure Android RFCOMM API and the server requires link authentication/encryption before handling requests. There is no additional application-layer encryption or independent server certificate; trust the computer you pair with. Domain ownership is server-side. Each account may publish up to 50 sites and keep up to 10 active sessions; the server handles up to 16 simultaneous connections. This is intended for trusted nearby peers, not a hardened public multi-tenant service. The local Windows user and anyone who can read the data file can access published content and password hashes. Forgotten-password recovery is not implemented.

### Save a score with local storage

Sites can use the standard JavaScript `localStorage` API; no special permissions or native bridge are needed:

```javascript
// Load the saved high score when the page opens.
let bestScore = Number(localStorage.getItem("bestScore") || "0");

// Save a new high score.
function saveScore(score) {
  bestScore = Math.max(bestScore, score);
  localStorage.setItem("bestScore", String(bestScore));
}
```

This data lives on the Android phone, separately for each site on each computer. It is not uploaded to the server or synchronized to other phones, and it is independent of the native BWW login account. Updating a site keeps its saved data. Uninstalling the app or clearing its Android app data removes it; normal WebView storage quotas still apply. Upgrading from version 0.1 uses new isolated origins; data from the old shared origins is not imported because its computer cannot be identified safely.

## Build and test

Prerequisites: .NET SDK 8, a **full JDK 17 or 21** including `javac` and `jlink`, Android SDK platform 35 and build-tools 35.0.0, and Python 3 for server integration tests. Set `JAVA_HOME` and `ANDROID_HOME` as appropriate. Android Studio can install the SDK components. Gradle 8.9 is pinned by the checked-in wrapper and its distribution checksum. NuGet dependencies are pinned by `server/packages.lock.json`.

From the repository root:

```sh
dotnet restore server --locked-mode
dotnet build server -c Release --no-restore
python3 tests/integration.py
cd android
./gradlew --no-daemon assembleDebug assembleDebugAndroidTest testDebugUnitTest lintDebug
```

On Windows use `gradlew.bat`. To package the server from the repository root:

```sh
dotnet publish server -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:NuGetLockFilePath=obj/packages.publish.lock.json -o artifacts/windows-x64
```

Or run `scripts/package.ps1` in PowerShell to create a Windows ZIP. GitHub Actions builds the desktop server, Android app, and ESP32 firmware, runs the protocol suites and Android unit tests, and Android lint, and uploads the executable and debug APK after successful checks. The workflow has been added but is not claimed to have run on GitHub.

For Linux/macOS development, the same server supports **loopback-only TCP**, using exactly the same framing and API as Bluetooth:

```sh
dotnet run --project server -- --tcp --data /tmp/bww-dev/store.json
```

This does not turn the Android Bluetooth client into a TCP client. Twenty Android JVM tests cover domain normalization, rejected addresses, HTML asset injection, fragments, routing restrictions, stable computer/site storage isolation, ESP32/desktop service selection, advertised site limits, and bounded Unicode chunk transfers; these do not run Android WebView on a device. Three instrumented Android tests exercise actual WebView local storage across activity recreation and computer/site switching, native full-screen exit controls, and HTML custom-view exit callbacks. Their APK is compiled by CI, but running them requires a connected Android device/emulator: `cd android && ./gradlew connectedDebugAndroidTest`. They load test sites through the real app resource interceptor and require no Bluetooth computer. Instrumentation uses an isolated set of test site/computer identities to avoid touching real scores. The integration suite starts its own isolated TCP servers and tests registration, authentication, publishing, ownership, concurrent domain collision, persisted sites/sessions after restart, logout, expiration, limits, malformed messages, and fragmented/coalesced frames. It uses temporary stores, not your real account data.

In this prepared cloud snapshot, `python3 scripts/cloud_build.py` uses the retained SDKs in `/workspace/.tools`, writable caches, and the platform's existing HTTPS proxy. Proxy values and account credentials are not embedded in the repository. Cloud tasks already have an isolated checkout; use it directly without creating a Git worktree.

## Device validation still required

The C# build, protocol integration suite, Windows cross-publish, and Android compilation/lint can be checked in this Linux cloud machine. It has no Windows Bluetooth adapter or Android device, so **real Bluetooth connectivity and Android WebView interaction remain unverified here**. Before relying on the app, perform this device check:

- Pair a Windows computer and Android phone; connect and browse the built-in site template. Confirm the button changes the message and the CSS applies.
- Publish a site, close/reopen the app, and restart the server. Confirm the account session and published site remain.
- Connect a second Android phone, sign in as a different account, and confirm it can browse but cannot claim/update the first account's domain.
- Disable Bluetooth or walk out of range. Confirm connection errors appear; reconnect, reopen a saved draft, and publish again.
- Revoke Bluetooth permission and confirm the app asks for it on the next connection attempt.
- Tap Full screen while playing a game. Confirm the hint disappears, normal in-game taps and rapid clicks work without exiting, the page keeps running, and swipe down from the top edge, top-edge double-tap, Esc, or Android Back restore the browser. Test an HTML/video fullscreen request too.
- Use localStorage to save a score, fully close/reopen the app, reconnect, and reopen the same site. Confirm the score remains. Switch to another computer hosting the same domain and confirm its score is separate; return to the first computer and confirm its original score remains.

If Connect fails, verify the server says READY Bluetooth, Windows Bluetooth is enabled, the devices are paired, and the chosen device is the Windows computer. The server uses classic Bluetooth, not BLE; BLE-only adapters are insufficient. Use the console to inspect startup errors. There is no macOS/Linux Bluetooth host implementation enabled in this app.

For the SD-backed Bluetooth host, follow [esp32/README.md](esp32/README.md). Its three-client default, chunked SD transfers, and powered-time session expiry are documented there.

See [PROTOCOL.md](PROTOCOL.md) for the wire format and operation list.
