# Validation

## Android background uploads 0.6.1

The connected-device foreground upload service renews its non-reference-counted CPU wake lock every minute, with a ten-minute fallback timeout, through transfers and reconnect waits. Shutdown removes the heartbeat and releases the lock. The manifest explicitly retains the service when the activity task is removed. Upload notifications explain slow transfers, report acknowledged chunk bytes, and distinguish final saving/verification. The browser socket remains separate from the service socket; no host or SD-format update is included.

The Android APK and instrumentation APK built, all **27 JVM tests** passed, and lint passed without a wake-lock timeout warning. All seven PC wire-protocol compatibility tests passed. The APK signature matches the previous Android 0.6.0 download, allowing an in-place update preserving data; download SHA-256 sums were regenerated. Physical Bluetooth, screen-off/Doze, task dismissal and multi-hour uploads have not been tested in this cloud environment. Force-stop and manufacturer battery restrictions can still interrupt the service; saved jobs resume when BWW is reopened.

## Activity LED 0.6.2

The original ESP32 target builds with a GPIO2 activity indicator. A native simulation of the actual LED implementation verified idle off, a visible pulse, continuous flashing during repeated traffic, return to off within four 80 ms timer ticks, active-high/active-low wiring and timer-creation failure. The existing fake-SDK Bluetooth adapter checks passed for secure three-client startup, thirteen failure diagnostics, lossless interleaved receive bursts and bounded stalled-reader handling. These checks do not establish physical LED wiring on every ESP32 board. No Android, Windows, SD format or quota change is included.

## Matching account quotas 0.6.1

PC and ESP32 advertise and enforce **50 websites per account**, without a separate total-site count cap. PC's existing quota is retained; ESP32 checks new-domain inline/chunk/sync publication and rechecks chunk commits. Existing collections above 50 remain readable/editable/deletable; additions require fewer than 50 current sites. The paged SD format, storage reserve, 512 KiB per-site size, and account/session/client bounds remain unchanged. Android 0.6.0 remains compatible.

Validation passed **31 firmware integration, 15 SD-copy, 8 PC-to-firmware sync and 7 PC wire-protocol tests (61 total), none skipped**. New tests cover two staged uploads competing for the last account slot, inline/chunk/sync quota rejection, editing at the quota, deletion freeing a slot, another account publishing beyond 50 total sites, persistence over restart, and preserving/editing a legitimate over-quota catalog from 0.6.0. PC wire tests publish 100 total sites across two accounts and verify independent 50-site quotas, sync rejection, editing, deletion and restart.

Conversion tests copy fifty sites PC → paged SD → PC, preserve credentials/content, reject additions over fifty in both directions before writing, and permit updates to existing over-quota collections without trimming them. The copy tool no longer has an unrelated 64 MiB ceiling on an entire desktop store; a valid fifty-site escaped-Unicode JSON collection above 64 MiB loads successfully while each site's 512 KiB limit remains enforced. Conversion still loads collections into computer RAM, so actual resources and transfer time remain practical constraints. Existing checksum, backup, conflict, session-preservation, preview/change-detection and legacy-format checks remain included.

The pinned original ESP32 target build, PC Release build and Windows x64 self-contained publish succeeded. Firmware/source/Windows/copy packages were verified with matching images/ELF, ZIP contents and SHA-256 sums. This update was tested in the cloud/native protocol harness, not on physical Bluetooth/SD/Windows hardware. No Android code or APK update was needed; automatic reconnection remains unchanged.


## Firmware / clients 0.6.0 SD-space catalog

The firmware now stores website records in eight-entry, 2 KiB SD catalog pages instead of the RAM account/session snapshot. Three slots and read-back SHA-256 proofs preserve active/fallback pages while staging edits. Interrupted proof writes are ignored; uncommitted generations are discarded at startup and on failed root commits so later checkpoints cannot accidentally activate them. Disposable domain lookup files fall back to verified page scanning. Upload admission detects actual usable/free SD space and leaves 128 KiB for metadata/recovery; deletion can use this reserve. The 512 KiB individual website and 12-account/24-session/three-client limits remain.

The full native suite passed **29 firmware integration, 13 SD-copy and 8 PC-to-firmware sync tests (50 total), none skipped**. New cases publish 41 websites for one account and preserve them over restart under a 64 KiB JSON-allocation budget; migrate a legacy 0.5.2 card with existing accounts, sessions and content; exercise multiple listing pages and mutation detection; copy 41 sites via the Python tool; and sync all 35 sites across a paginated PC/device comparison. Failure tests cover exhausted space at admission and mid-upload, deleting with only reserved space available, root-write rollback followed by checkpoint/restart, partial future page proofs, and damaged disposable lookup files. Existing full-512-KiB Unicode, chunk verification, ownership, session, corruption, cleanup and 0.5.2 commit-memory regressions remain included. The harness now tracks 2 KiB catalog and 512-byte document allocations in addition to the existing state/RPC allocations. Five commit/recovery/memory/deletion tests were rerun after the final backup-page read-error guard.

The original esp32dev / pinned Arduino 2.0.17 target build passed, using approximately 40 KiB static RAM and 1.21 MB flash. Android 0.6.0 debug APK and instrumentation APK built; **27 JVM tests and lint passed**. The APK signature was verified to use the same certificate as the existing 0.5.0 download, allowing installation over it. PC Release build and self-contained Windows x64 publication passed. Firmware ZIP packaging verifies matching ELF/image SHA-256 and ZIP integrity. Published SHA256SUMS cover the downloads.

These are cloud builds and native filesystem/protocol tests; no physical ESP32, SD card, Android UI or Bluetooth radio was available for this update. Actual card capacity/space queries use Arduino SD.totalBytes()/usedBytes(). Larger catalogs increase filesystem traversal time, even though index RAM remains bounded. First startup upgrades the index without formatting; back up /bww before upgrading and do not downgrade to firmware 0.5.2 or earlier afterward. Install Android 0.6.0 and Windows sync 0.6.0 to follow every list page. Automatic reconnection remains enabled.


## Firmware 0.5.2 commit-memory fix

The pinned ESP32 target build passed; static RAM is 40,096 bytes and flash fits the existing huge-app partition. All 21 firmware integration tests, 12 SD-copy tests and seven PC↔firmware sync tests passed, none skipped. Existing startup/receive-burst/client-slot/password/cooperation checks passed as well.

Two new regressions specifically exercise this failure. The allocation-instrumented native harness tracks real C++ buffer allocation lifetimes and refuses state writes while the last full-sized verification chunk is retained. The original 0.5.1 transfer code fails with `Could not commit site to SD`; 0.5.2 publishes repeatedly, verifies the contents and preserves them across restart. A second test runs the production file-open policy for state reads at the user's exact `free=21512 largest=8180` sample. The 0.5.1 policy fails that test with the same commit error, and the corrected policy passes. Headroom checks also verify that a fresh 8 KiB chunk allocation is refused at that sample, adequate memory is accepted, and inadequate/overflow-sized requests stay blocked.

The verifier buffer is destroyed before state commit. JSON documents and outbound chunks already allocated by callers now reserve file-I/O headroom only; chunk reads reserve any new chunk buffer separately and avoid geometric capacity growth. The new binary image's checksum/hash and matching ELF are verified during packaging. These are target-build and native simulation results, not measurements on a physical ESP32. The user subsequently reported successful publication on the physical board with 0.5.2. Android 0.5.0 and SD account/site formats remain compatible.

## Firmware 0.5.1 cleanup allocation patch

The pinned PlatformIO ESP32 target build passed using espressif32 6.9.0, Arduino ESP32 2.0.17, ArduinoJson 6.21.5 and the Xtensa 8.4.0 toolchain. Flash and static RAM fit the existing original-ESP32/huge-app layout. This cloud now has the target toolchain; historical build restrictions described below do not apply to this patch's build.

All 19 portable firmware integration tests, 12 SD-copy tests and seven PC↔firmware sync tests passed, none skipped. The new cleanup regression tracks actual ArduinoJson malloc/free calls: repeated chunked publishes, reads and commits stay within 64 KiB of live JSON pools (40 KiB permanent + one 24 KiB temporary pool), with no rejected allocations. The original cleanup fails that same regression with 15 rejected allocations. That budget measures JSON pools, not total ESP32 heap. Additional regressions exercise 1,500 orphan chunks, live/staged chunk preservation, retained generations across restart, and unreadable metadata preventing deletion. The existing Bluetooth fake-SDK burst/startup, client-slot, HMAC/PBKDF2 and cooperation checks passed.

The source ZIP and binary ZIP are verified against the patched sources/build outputs; the binary package includes its matching ELF and checksums. No physical ESP32/SD card is attached: the new heap guards, on-card streaming directory deletion, three-client radio timing and resolution of the reported crash still need hardware verification. Heap headroom checks reduce allocation risk; they cannot guarantee allocation under concurrent system activity or diagnose heap corruption. Existing data formats remain unchanged and no SD formatting or flash erase is part of the documented upgrade.

## Android 0.5.0 reconnect and persistent uploads

The APK and instrumented test APK build passed. All 27 JVM tests passed with zero failures/errors/skips, including interrupted staging, lost commit replies without duplicate writes, destination/ownership conflicts, legacy-host replay restrictions and Unicode fingerprint compatibility. Lint passed with zero errors and only the existing reviewed JavaScript warning. The APK passed ZIP integrity checks and its v2 signature verified with the same development signing certificate as Android 0.4.2.

Three additional instrumented tests cover real Android AtomicFile queue persistence without credentials, cancellation versus a stale worker, and per-device isolation/duplicate prevention. Together with the three existing WebView/full-screen tests, all six device tests compile; none ran because no Android device/emulator is available. Real radio dropouts, background-service restart, battery restrictions and notification/editor rendering remain unverified on hardware. The queue saves uploads before transmission, binds them to the paired address/account, and uses the existing 0.5.0 host conditional-publish protocol. No PC or firmware code changed for this update. See ANDROID_UPLOADS_README.md for older-host behavior and background limits.

## Android 0.4.2 full-screen exit gesture

The persistent exit button is removed. Entry shows an automatically disappearing hint (“Swipe down from top to exit full screen”), and the activity observes top-edge downward swipes and top-edge double-clicks to exit both browser and HTML custom full-screen views. In-game taps, rapid clicks, double-taps, and scrolling within the content area are dispatched to the existing page without triggering an exit; Back and Escape remain exit paths. Updated instrumented tests verify that in-page double taps remain full screen without disrupting gameplay, top-edge swipe down restores the browser/page instance, top-edge double-tap restores the browser, Back works, and custom-view exit callbacks run. APK build and unit test compilation are verified via cloud CI.

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
