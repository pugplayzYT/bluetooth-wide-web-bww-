# Validation of version 0.2.0

Verified in the Linux cloud workspace:

| Check | Result |
| --- | --- |
| C# Release build (.NET SDK 8.0.425) | Passed; zero compiler warnings/errors |
| Wire-protocol integration suite | 5 scenarios passed, none skipped |
| Windows x64 self-contained single-file publish | Passed; generated PE32+ console executable |
| Android debug APK build (SDK 35, full JDK 21, Gradle 8.9) | Passed |
| Android JVM tests | 12 tests passed, zero failures/errors/skips |
| Instrumented Android test APK | Compiled; 3 device tests added, not executed in this cloud |
| Android lint | Passed; zero errors, one reviewed warning for enabling JavaScript |
| Android APK signature | Valid APK Signature Scheme v2, one debug signer |
| Development server smoke check | Protocol-1 hello and site listing succeeded on loopback TCP |

The JavaScript lint warning is expected for an HTML/CSS/JavaScript browser. There is no native JS bridge; file/content access is disabled, no Internet permission is declared, external requests are restricted by CSP and resource interception, and account/session operations are native UI operations. JavaScript is intentionally supported.

The protocol scenarios cover account validation/login, password and token hashing in the store, site creation/read/update/delete, owner restrictions, simultaneous domain collision, persisted content and sessions across restart, revoked and expired sessions, invalid requests and domains, site size limits, and fragmented/coalesced wire messages. Android JVM tests validate routing, markup assembly, stable computer/site origins, and prevention of cross-computer resource access; they do not run a real WebView. The three instrumented tests use an actual Android WebView to test saved scores across activity recreation, data isolation between sites/computers, full-screen page continuity and native/custom-view exit behavior. Their compilation does not establish that they passed on a device.

Not executed here: the Windows binary on Windows, Bluetooth adapter/SDP/RFCOMM behavior between real devices, APK installation and native Android UI/WebView interaction, release signing, or the GitHub Actions workflow. The cloud machine lacks the required Windows/Android devices. Follow README.md's device checklist before treating the complete Bluetooth workflow as verified.

Generated binaries are development artifacts, not a published GitHub release. The Windows executable is not Authenticode signed. The Android APK uses a development signing key, not a production distribution key. Installation, packaging and device instructions are in README.md.
