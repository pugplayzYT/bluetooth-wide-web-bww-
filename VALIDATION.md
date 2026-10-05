# Validation

## Android 0.4.2 full-screen exit gesture

The persistent exit button is removed. Entry shows an automatically disappearing hint, and the activity observes double taps/clicks to exit both browser and HTML custom full-screen views. Single taps and scrolling are dispatched to the existing page; Back remains an exit path. Updated instrumented tests check that a single tap stays full screen, a double tap restores the browser/page instance, Back works, and custom-view exit callbacks run. No device/emulator is available here, so those tests are compiled, not executed. APK build passed, all 20 existing JVM tests passed with no failures/errors/skips, lint passed with only the previously reviewed JavaScript warning, and the development APK's v2 signature verified.

## Bluetooth account website sync 0.5.0

The PC Release build passed with zero warnings/errors, and the Windows x64 self-contained single-file publish produced a PE32+ executable. Six real PC wire-protocol scenarios passed, including authenticated fingerprints and conditional publication. Seven end-to-end sync scenarios passed using the actual C# sync console/client against the actual portable C++ firmware core over a loopback bridge: preview/cancellation, PC → ESP and repeat/no-op, ESP → PC with backups/credential preservation, a full 512 KiB Unicode round trip, source edits after comparison, destination edits before commit, ownership conflicts, authenticated manifests, chunk corruption, and equivalent content stored with different chunk segmentation. No tests in those suites were skipped.

All 16 existing firmware integration tests, all 12 SD-copy tests and the password/slot/startup/receive-burst checks also passed during this change. No real accounts or SD cards were used.

Windows Bluetooth device discovery, Windows pairing UI, the batch launcher and Bluetooth sync to a physical ESP32 have not run here. Firmware target cross-build remains blocked by PlatformIO registry access, as described below. The C++ core tests do not validate actual SD heap/timing or the Bluetooth radio. The PC executable is a development build without Authenticode signing. Transfers commit one site at a time; the batch is not a distributed transaction. Follow SYNC_README.md before using real stores.

## Android 0.4.1 authentication loading UI

The Android app now displays an indeterminate spinner in its account dialog during login and registration, with an ESP32 explanation selected by the paired device's `BWW-ESP32` name prefix. It restores controls after failure and dismisses the dialog on success. It uses the existing authentication protocol and requires no firmware change. Android APK build and all 20 existing JVM tests passed with no failures/errors/skips; the existing instrumented test APK compiled. Lint passed with only the previously reviewed JavaScript warning, and the APK's v2 signature verified. No Android device is available here to verify the spinner rendering, keyboard behavior, or Bluetooth authentication in person. The downloadable APK is signed with the workspace's development key.

## Firmware 0.4.3 publish transport fix

The actual Bluetooth adapter passed a host regression harness with bounded fake FreeRTOS queues and a simulated main-task consumer. Three clients each received 16,480 bytes in interleaved bursts through 4 KiB queues, preserving every byte and client isolation without disconnecting. A non-draining consumer disconnected only its client with a diagnostic. A slowly draining consumer exhausted the two-second total indication budget rather than renewing the timeout per byte. The previous 0.4.2 adapter fails the same lossless-burst regression due to its immediate queue-full disconnect. Startup/linking and 13 failure-diagnostic checks also passed. This simulates queue scheduling, not Bluetooth radio, SD or FreeRTOS timing on a physical board.

For this update, all 16 firmware-core integration tests and all 12 SD-copy tests passed, none skipped, along with the password compatibility/cooperation and client-slot checks. The target cross-build is still blocked by the registry access restriction below; actual Android publication, SD stalls and simultaneous Bluetooth clients need physical-board verification.

## Firmware 0.4.2 password-hashing optimization

The production `PasswordHmac.h` passed 56 HMAC comparisons and eight full 210,000-round PBKDF2 comparisons against OpenSSL using real Mbed TLS 2.28.9. Cases include empty input, 63/64/65/256-byte keys, Unicode and embedded NULs; existing PBKDF2 output remains unchanged. The timed cooperation schedule passed its boundary and millisecond-rollover checks. A host-only comparison on the same software SHA backend measured 260 ms with repeated key pads and 135 ms with prepared states; this is not an ESP32 measurement.

An additional host check compiled Espressif's ESP-IDF 4.4.7 parallel-engine SHA driver and alternate context header against an emulated SHA engine backed by OpenSSL. The same vectors passed through the driver's hardware-to-software cloning path, including lock/unlock assertions. This checks the context transition, not ESP32 hardware performance. Sources: [Espressif SHA driver](https://github.com/espressif/esp-idf/blob/v4.4.7/components/mbedtls/port/sha/parallel_engine/esp_sha256.c), [alternate context](https://github.com/espressif/esp-idf/blob/v4.4.7/components/mbedtls/port/include/sha256_alt.h).

All 16 portable firmware integration tests and all 12 SD-copy compatibility tests passed, none skipped; Bluetooth startup, PBKDF2 and client-slot checks also passed. Physical-board login/signup duration, concurrent Bluetooth throughput and target cross-build remain unverified here. Firmware prints password-hash and authentication-processing/reply durations to enable real-board measurement without logging usernames, passwords or tokens. The PlatformIO download restriction described below remains.

## Firmware 0.4.1 startup fix

The actual Bluetooth adapter source passed a host regression harness with a fake ESP-IDF SDK: Arduino's HAL archive is retained before `setup()`, the controller requests Classic Bluetooth with three clients, the listener requires authentication/encryption, and 13 injected startup failures produce specific diagnostics. The harness uses static archives, LTO and section garbage collection to exercise the weak/strong `btInUse()` link. The previous adapter fails the same test because Arduino's weak default reports Bluetooth unused. This is a link/startup regression check, not a real ESP32 cross-build or Bluetooth device test.

For this firmware update, all 16 portable firmware integration tests and all 12 SD-copy compatibility tests passed, none skipped; the PBKDF2 and client-slot checks also passed. The PlatformIO registry restriction below still prevents a cloud target build; cold boot, pairing and three-client transfers require physical-board validation after reflashing.

## Existing application validation

Verified in the Linux cloud workspace:

| Check | Result |
| --- | --- |
| C# Release build (.NET SDK 8.0.425) | Passed; zero compiler warnings/errors |
| Wire-protocol integration suite | 5 scenarios passed, none skipped |
| Windows x64 self-contained single-file publish | Passed; generated PE32+ console executable |
| Android debug APK build (SDK 35, full JDK 21, Gradle 8.9) | Passed |
| Android JVM tests | 20 tests passed, zero failures/errors/skips |
| Instrumented Android test APK | Compiled; 3 device tests added, not executed in this cloud |
| Android lint | Passed; zero errors, one reviewed warning for enabling JavaScript |
| Android APK signature | Valid APK Signature Scheme v2, one debug signer |
| Portable firmware C++ core (g++ with warnings as errors) | Built successfully; 16 integration tests passed |
| Firmware Bluetooth slot registry | Three clients accepted; fourth rejected; reuse/stale callbacks checked |
| Firmware PBKDF2 implementation | Matched OpenSSL reference output |
| ESP32 PlatformIO cross-build | Blocked: cloud policy denies PlatformIO registry downloads (HTTP 403) |
| Development server smoke check | Protocol-1 hello and site listing succeeded on loopback TCP |

The JavaScript lint warning is expected for an HTML/CSS/JavaScript browser. There is no native JS bridge; file/content access is disabled, no Internet permission is declared, external requests are restricted by CSP and resource interception, and account/session operations are native UI operations. JavaScript is intentionally supported.

The protocol scenarios cover account validation/login, password and token hashing in the store, site creation/read/update/delete, owner restrictions, simultaneous domain collision, persisted content and sessions across restart, revoked and expired sessions, invalid requests and domains, site size limits, and fragmented/coalesced wire messages. Android JVM tests validate routing, markup assembly, stable computer/site origins, and prevention of cross-computer resource access; they do not run a real WebView. The three instrumented tests use an actual Android WebView to test saved scores across activity recreation, data isolation between sites/computers, full-screen page continuity and native/custom-view exit behavior. Their compilation does not establish that they passed on a device.

Not executed here: the Windows binary on Windows, Bluetooth adapter/SDP/RFCOMM behavior between real devices, APK installation and native Android UI/WebView interaction, release signing, or the GitHub Actions workflow. The cloud machine lacks the required Windows/Android devices. Follow README.md's device checklist before treating the complete Bluetooth workflow as verified.

Generated binaries are development artifacts, not a published GitHub release. The Windows executable is not Authenticode signed. The Android APK uses a development signing key, not a production distribution key. Installation, packaging and device instructions are in README.md.

Firmware tests exercise the actual C++ core with ArduinoJson 6.21.5 and a temporary filesystem adapter, including failed SD snapshot writes, previous-snapshot recovery, checksum corruption, ownership, quotas, UTF-8 site limits, session persistence/expiry, and malformed/coalesced JSON frames. They do not compile or validate the ESP-IDF Bluetooth/Arduino SD adapters. The ESP32 target binary, device flashing, real SD wiring, ESP32 heap usage, and Bluetooth pairing/transfer remain unverified. The PlatformIO project pins espressif32 6.9.0 and ArduinoJson 6.21.5; CI includes its cross-build and native tests, but a successful GitHub Actions run is not claimed here.

Required network additions were saved to the cloud environment draft: `api.registry.platformio.org`, `dl.registry.platformio.org`, and `registry.platformio.org`. Review and save the environment network settings to unblock toolchain installation; saving the draft alone does not change the running network policy.

Version 0.4 host validation includes full 512 KiB Unicode publish/read/reboot via bounded 8 KiB chunks, three interleaved independent session uploads, fourth-upload rejection, session binding, concurrent domain claims, commit rollback with retained chunks, previous-snapshot recovery, upload expiry/reboot cleanup, corrupt chunk rejection, and revision mismatch handling. The Android JVM suite additionally checks 512 KiB Unicode chunk round trips, emoji boundaries, malformed hex, and malformed UTF-8. These results do not establish actual three-phone Bluetooth throughput or ESP32 heap usage. The controller, per-client receive/spool scheduler, and ephemeral AES request spooling remain subject to ESP32 cross-build/device validation.

BWW SD Copy: 12 temporary-folder tests passed with both the actual C++ firmware core and C# server configured, none skipped. Verified desktop → SD → desktop conversion, original-password login on both readers, a full 512 KiB Unicode site, independent destination sessions, checksums, ownership/credential conflicts, backups, prior-snapshot recovery, failed commit/retry, limits, CLI preview/apply/repeat, input changes, and symlink rejection. The standalone Tkinter GUI has no available graphical display in this cloud; Windows dialogs, launcher, volume checks and real card-reader writes are not claimed tested. No real user account stores or SD cards were used.
