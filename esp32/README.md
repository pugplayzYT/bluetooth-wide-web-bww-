# BWW ESP32 host

This PlatformIO C++ project turns an original ESP32 and SPI SD card into a standalone Bluetooth-wide Web server. The Android app connects, registers/logs in, and creates, edits, browses, and deletes HTML/CSS/JavaScript sites. Accounts and websites live on the SD card. Wi-Fi and an Internet connection are not needed during use.

Use an **original ESP32 with Bluetooth Classic**, such as an ESP32-WROOM-32 development board with at least 4 MB flash. ESP32-S3, C3, C6 and other BLE-only boards cannot run this RFCOMM firmware. The default PlatformIO board is `esp32dev`. This project uses a 3 MB application partition without OTA updates.

## Activity LED

Firmware **0.6.2** flashes the controllable onboard LED while Bluetooth request data is received or sent, including uploads and website downloads. It stays off when idle and stops flashing within about 320 ms of the last traffic. A separate timer keeps the indicator responsive while the main task accesses the SD card; the indicator does not delay transfers. Merely being connected does not keep it lit.

The default is an active-high LED on **GPIO2**, common on original ESP32 development boards. The power LED is wired to the supply and cannot be switched off by firmware. Boards without a GPIO-controlled LED need an external LED with a suitable series resistor. For a different LED, add `-DBWW_ACTIVITY_LED_PIN=your_gpio` to `build_flags` in `platformio.ini`; use `-DBWW_ACTIVITY_LED_ACTIVE_LOW=1` for an active-low LED, or pin `-1` to disable it. Choose a free GPIO, avoiding the SD card's GPIO5/18/23/19 and BOOT GPIO0.

## Default wiring

The D labels below mean ESP32 **GPIO numbers**, not another board's pin numbering:

| SD module pin | ESP32 pin |
| --- | --- |
| CS | D5 / GPIO5 |
| CK / CLK / SCK | D18 / GPIO18 |
| MOSI | D23 / GPIO23 |
| MISO | D19 / GPIO19 |
| VCC | Vin **only for an SD module rated for that supply** |
| GND | GND |

Vin is commonly approximately 5 V on a USB-powered development board. A bare SD card or 3.3 V-only module must use **3.3 V**, not Vin. Confirm your module has the required regulator and compatible SPI level circuitry before connecting Vin. ESP32 GPIOs are not 5 V tolerant. Use a common ground, short wires, and a stable supply. Insert a FAT32 SD card before booting; this firmware never formats the card automatically.

## Build, flash, and pair

[Download the ESP32-only PlatformIO project (version 0.6.2)](https://github.com/pugplayzYT/bluetooth-wide-web-bww-/raw/refs/heads/main/downloads/Bww-ESP32-PlatformIO-0.6.2.zip). Extract the ZIP, then open its `esp32` folder in VS Code. This download contains the firmware source and configuration; host-side tests require the full repository.

Version **0.6.1** sets the same **50-websites-per-account** quota as the PC server while retaining the SD-backed index and removing the old separate 24-websites-per-device limit. Website records live in checksummed SD catalog pages containing at most eight entries, with three page slots protecting the active snapshot, fallback snapshot and pending write. Total website storage depends on detected free SD space, with a 128 KiB reserve for metadata and recovery. The existing 12-account limit still applies. Existing over-quota collections from 0.6.0 are kept and can be edited or deleted; only new domains are refused at/above 50. Individual sites retain the 512 KiB limit; the 12-account and session/client limits still apply. All 0.5.2 crash/commit memory protections remain included.

The first startup migrates older `/bww/state-*.json` site indexes automatically. Back up `/bww` before upgrading. Do not downgrade to 0.5.2 or earlier after migration: older firmware does not understand the SD catalog. Use the updated SD-copy tool when moving cards between hosts. Android **0.6.0** and the updated Windows sync tool follow paginated listings; older Android apps display only the first 32 matching websites, but can still open a website directly by domain.

Version **0.5.1** patches the upload-start cleanup memory problem seen in `pruneSites → readJson → fopen → lock_init_generic → abort`. Backup, verification and metadata JSON buffers are released before the next phase. Cleanup tracks bounded transfer IDs instead of every chunk filename and scans the SD directory one entry at a time, servicing incoming Bluetooth bytes between entries. It skips deletion if retained metadata or the fallback state cannot be read. File operations check internal free heap and largest free block first, printing a low-memory diagnostic rather than knowingly opening files without headroom. This reduces known memory pressure; physical-board testing is still needed to verify your particular crash is resolved.

The patch keeps GPIO5/18/23/19 wiring, three Bluetooth clients, the 512 KiB site limit, and existing SD accounts/site content. It also includes 0.5.0 conditional publication, so Android 0.5.0 can safely retry interrupted uploads. Updating firmware does not format the card.

[Download prebuilt ESP32 0.6.2 binaries](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-ESP32-Binaries-0.6.2.zip) if you prefer flashing without compiling. The ZIP includes `firmware.bin`, the matching `firmware.elf` for crash decoding, and upgrade instructions. For VS Code/PlatformIO, use the source ZIP above: extract it, open **its `esp32` folder**, close the serial monitor, and click **Upload**. Replacing files alone does not flash the board. Confirm `firmware 0.6.2` and `READY Bluetooth` afterward.

Version 0.5.0 adds authenticated account website comparison and conditional Bluetooth sync from the Windows host. [The sync guide](../SYNC_README.md) covers device selection/pairing, reviewing differences, choosing transfer directions and approving changes. Existing accounts/sites remain compatible; Android does not need an update. Passwords and sessions are not copied. Earlier startup, password-hashing and receive-queue fixes remain included.

Version 0.4.3 fixes disconnection when an upload burst fills the 4 KiB receive queue. An 8 KiB site chunk uses about 16 KiB on the wire because of hex encoding. The listener now waits for the main task to drain the queue to encrypted SD spools, with a two-second total wait budget per incoming indication. Queue memory stays bounded and the SD adapter remains on one task. A stalled reader still disconnects with a `Bluetooth receive stalled` diagnostic. Real-card stalls, heap usage and three-phone throughput require device testing.

Version 0.4.2 speeds password hashing by preparing the HMAC key states once per login/signup and yielding by elapsed time. It preserves PBKDF2-SHA256's 210,000 iterations and the existing account format; no account migration is needed. Serial reports `Password check: ... elapsed=... ms` and `Authentication processing and reply: elapsed=... ms` without logging credentials. Measure on your board: host benchmarks do not establish an ESP32 login time.

Version 0.4.1 fixed startup linking so Arduino retains Bluetooth memory before `setup()` runs; this fix remains included, with the three-client default. Build and upload this project to update an existing board; replacing files alone does not update the firmware. After reset, the serial monitor prints `firmware 0.6.2` and, on successful Bluetooth startup, `READY Bluetooth`. If startup fails, copy the preceding named step, error code and heap information. The older generic “original ESP32 Classic required” runtime message did not establish that your board was incompatible.

Install VS Code with the PlatformIO extension, then open this `esp32` folder as a PlatformIO project. Alternatively install PlatformIO Core 6.1.18 and run from the repository root:

```sh
python3 -m pip install platformio==6.1.18
pio run -d esp32
pio run -d esp32 -t upload
pio device monitor -d esp32
```

Specify your serial port if detection is ambiguous, for example `pio run -d esp32 -t upload --upload-port COM5`. On Linux it may be `/dev/ttyUSB0`. If flashing does not start, hold BOOT while the uploader connects. Release BOOT after flashing; holding it during reset enters the bootloader. The monitor runs at 115200 baud.

1. Boot with the SD card connected. The serial monitor must report `READY Bluetooth`.
2. In Android Bluetooth settings, pair with **BWW-ESP32**. Compare the phone's code with the serial monitor's six-digit code. Approve on the phone, then type `Y` in the monitor or briefly press the board's BOOT button. Type `N` to reject; pairing expires after 60 seconds. Legacy fixed-PIN pairing is rejected.
3. Install Android app **version 0.4.0 or newer**, tap Connect, and select the paired board. The app supports the ESP32's standard Serial Port Profile UUID as well as the Windows server's custom UUID, and checks BWW protocol 1 before sending account credentials.
4. Register an account, create a site, and publish. Public browsing does not require login. Domains and accounts belong to this board/card; they are separate from your Windows host.

Website full screen and `localStorage` work in the Android WebView just as with the desktop host. Browser storage stays on each phone, isolated by website and paired Bluetooth host; it is not written to the SD card or synchronized between phones.

## Storage and persistence

| Setting | Firmware default |
| --- | --- |
| Simultaneous Bluetooth clients | 3 |
| HTML + CSS + JavaScript combined | 512 KiB UTF-8 per site |
| Accounts | 12 |
| Sites per account | 50 (new domains); editing/deleting existing sites remains allowed |
| Total sites | No separate count quota; limited by storage and the existing account limit |
| SD free-space reserve | 128 KiB, plus space for each pending write |
| Active sessions | 24 total, 4 per account |
| Password hashing | Salted PBKDF2-SHA256, 210,000 iterations |
| Session duration | 30 days of accumulated powered runtime |
| SD SPI frequency | 4 MHz |

The firmware has three independent authenticated SPP connection slots with separate receive queues and request files, and handles completed requests in turn. The controller is explicitly configured for three Classic ACL links (the bundled Bluedroid host supports four). Long password hashing and reply waits continue receiving the other clients' requests. A fourth connection is disconnected; pair phones one at a time.

Sites transfer as up to 8 KiB UTF-8 chunks saved directly to SD, so a 512 KiB site never requires a 512 KiB ESP32 heap allocation. The JSON request/reply buffer stays at 24 KiB; each chunk is checked with SHA-256, and publish commits only after its metadata/chunks are verified. Up to three uploads can be staged; each is bound to the authenticated session and expires after five powered minutes without activity. Incomplete uploads are removed after reboot. HTML/CSS/JS share the 512 KiB total. Older version 0.3 clients can access legacy inline sites up to 16 KiB, but cannot browse newly chunked sites. Upgrade to Android 0.4 before using this firmware.

Incoming request spools are AES-CTR encrypted with a fresh RAM-only key each boot and per-request nonces, then deleted after processing. Passwords and bearer tokens are not written in plaintext to the card. This protects residual request files; it does not encrypt published sites or the account database.

The Android editor displays the connected host's size limit. ESP32 hashing is slower than desktop hashing; login/register may take several seconds. The Android client allows up to 120 seconds for authentication and 60 seconds for other operations.

There is no RTC or Internet clock. Sessions survive reboot, but time while powered off does not count toward expiration. The powered clock is saved on mutations and every five minutes; abrupt power loss can lose up to five minutes. The API reports `expires: null` and `expiresAfterPoweredSeconds`, and site `updated` is null with an increasing `revision`, rather than claiming a calendar timestamp.

The firmware reserves `/bww` on the SD card. Two checksummed state snapshots track users, hashed tokens, and site ownership. Site metadata versions are separately checksummed JSON files, with individually checksummed binary UTF-8 chunks under `/bww/sites`. Publishing writes a new site generation before committing the inactive snapshot and checking it back. A truncated latest snapshot can recover the previous valid snapshot; recent changes can be lost during that recovery. If both snapshots are invalid, boot fails without wiping the card. FAT/SD hardware still cannot guarantee survival of every power loss. Back up the entire `/bww` directory with the board powered off, and never remove the card during use. The firmware prunes obsolete site generations inside its reserved directory.

Persisted credentials contain salted password hashes and session-token digests; Serial never prints passwords or bearer tokens. Temporary request files contain only ciphertext as described above. People with physical access to the card can read public content and password hashes; keep backups private. Forgotten-password recovery is not implemented. Link authentication and encryption are required by the SPP listener, but there is no independent application certificate.

## Developer guide and validation

Edit `include/BwwConfig.h` to change SD pins and limits (`MAX_BT_CLIENTS = 3`, `MAX_SITE_BYTES = 512 * 1024`). Pin changes also require rewiring; larger JSON limits consume ESP32 heap and must be tested on hardware. `src/BwwCore.cpp` and `src/BwwTransfers.cpp` implement the same operations documented in [../PROTOCOL.md](../PROTOCOL.md). `src/main.cpp` adapts SD storage and mbedTLS crypto; `src/BwwBluetooth.cpp` provides secure Classic SPP, numeric pairing confirmation, bounded receiving, and congestion-aware replies. The desktop and SD storage formats are intentionally separate; copying desktop `store.json` to the card is not an import. Use [BWW SD Copy](../BWW_SD_COPY_README.md) to convert computer accounts/sites onto an already FAT32 card, or copy SD sites back to a computer.

After installing PlatformIO dependencies, Linux developers can test the actual portable C++ core and prepared password HMAC using g++, OpenSSL and Mbed TLS 2.x development headers (Ubuntu: `sudo apt-get install g++ libssl-dev libmbedtls-dev`):

```sh
python3 scripts/test_firmware.py
```

Run that command from the repository root. Alternatively pass `--mbedtls-source /path/to/mbedtls-2.x` to build the password tests against an existing source tree. It tests account operations/ownership, quotas, persisted sessions/sites, powered-time expiration, interrupted writes, corrupt snapshots/site content, framing, and PBKDF2 compatibility with OpenSSL, including long and Unicode passwords and timed cooperation at clock rollover. This uses temporary directories and does not touch your card. It does not exercise the ESP-IDF Bluetooth stack or SD electrical behavior.

Before relying on hardware, build and flash it, verify the reported flash/RAM usage, then pair a phone, register, publish near the 512 KiB limit, reconnect and reboot, and verify the saved site/session. Test rejected pairing, three phones browsing/publishing at once, a fourth rejected while all slots are occupied, missing/invalid SD cards, and scores retained in the Android app. Check Serial for mount/pairing errors without logging account secrets.

Current cloud results and limitations are recorded in [../VALIDATION.md](../VALIDATION.md). This repository contains source firmware; a board binary is only produced after a successful PlatformIO build. Cloud package installation currently requires the PlatformIO registry domains enabled in environment settings.
