# Validation of version 0.1.0

Verified in the Linux cloud workspace:

| Check | Result |
| --- | --- |
| C# Release build (.NET SDK 8.0.425) | Passed; zero compiler warnings/errors |
| Wire-protocol integration suite | 5 scenarios passed, none skipped |
| Windows x64 self-contained single-file publish | Passed; generated PE32+ console executable |
| Android debug APK build (SDK 35, full JDK 21, Gradle 8.9) | Passed |
| Android JVM tests | 5 tests passed, zero failures/errors/skips |
| Android lint | Passed; zero errors, one reviewed warning for enabling JavaScript |
| Android APK signature | Valid APK Signature Scheme v2, one debug signer |
| Development server smoke check | Protocol-1 hello and site listing succeeded on loopback TCP |

The JavaScript lint warning is expected for an HTML/CSS/JavaScript browser. There is no native JS bridge; file/content access is disabled, no Internet permission is declared, external requests are restricted by CSP and resource interception, and account/session operations are native UI operations. JavaScript is intentionally supported.

The protocol scenarios cover account validation/login, password and token hashing in the store, site creation/read/update/delete, owner restrictions, simultaneous domain collision, persisted content and sessions across restart, revoked and expired sessions, invalid requests and domains, site size limits, and fragmented/coalesced wire messages. Android JVM tests validate routing and markup assembly rules; they do not run a real WebView.

Not executed here: the Windows binary on Windows, Bluetooth adapter/SDP/RFCOMM behavior between real devices, APK installation and native Android UI/WebView interaction, release signing, or the GitHub Actions workflow. The cloud machine lacks the required Windows/Android devices. Follow README.md's device checklist before treating the complete Bluetooth workflow as verified.

Generated binaries are development artifacts, not a published GitHub release. The Windows executable is not Authenticode signed. The Android APK uses a development signing key, not a production distribution key. Installation, packaging and device instructions are in README.md.
