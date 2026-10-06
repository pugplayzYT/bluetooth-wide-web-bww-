# Bluetooth website sync

[Download the Windows host and sync tool](https://github.com/pugplayzYT/bluetooth-wide-web-bww-/blob/main/downloads/README.md#windows-server-and-bluetooth-sync) and [latest ESP32 firmware project](https://github.com/pugplayzYT/bluetooth-wide-web-bww-/blob/main/downloads/README.md#esp32-firmware).

Sync compares websites for the account you sign into on your computer and ESP32. It lists PC-only sites, device-only sites, and sites with different contents. For each difference, choose PC → device, device → PC, or skip. It then shows the selected changes and asks you to type `APPLY` before transferring anything.

## Set up once

1. Build/upload ESP32 firmware **0.5.0 or newer** using the included PlatformIO configuration. Existing SD accounts/sites stay compatible. Wait for `READY Bluetooth`.
2. Extract the Windows ZIP. It contains `Bww.Server.exe`, `Sync-BWW.bat`, and this guide; .NET installation is not required. The executable is a development build, not Authenticode signed.
3. Have an account with the **same username** on each host. Create it using the Android app on each host if needed; passwords may differ. Sync does not create accounts or move passwords. Android **0.4.0 or newer** works without another app update.

## Compare and apply

1. Stop the PC's running BWW server so sync can safely open its store. Leave the ESP32 running with its SD card inserted.
2. Double-click **Sync-BWW.bat**, or run `Bww.Server.exe --sync` in PowerShell. The default PC store is `%LOCALAPPDATA%\Bww\store.json`; use `--data "D:\path\store.json"` if yours is elsewhere.
3. Select the ESP32 from the Bluetooth device list. If it needs pairing, the tool opens Windows Bluetooth settings. Compare the pairing code, approve on Windows and press BOOT on the ESP32 when prompted, then return and press Enter. A serial monitor is optional. If the device is not listed, pair it in Windows settings and run sync again.
4. Enter your username, PC password, and device password. Password input is hidden in the interactive console. ESP32 sign-in can take 10–20 seconds or longer.
5. Review the differences. Enter `P` for PC → device, `D` for device → PC, or Enter to skip. A domain belonging to another account is marked blocked and cannot be selected.
6. Review the final list and type **APPLY**. Other answers cancel. Transfers finish one site at a time. Restart the PC server afterward.

The first comparison uses content fingerprints; dates and revisions are not used to decide which copy wins. You choose the direction when both copies differ. Sync is manual and does not propagate deletions or run continuously. Repeating it after successful transfers reports matching content, even if the two hosts use different storage chunk boundaries.

Before an inbound PC change, the tool creates `store.json.sync-backup-<unique id>` beside the store and prints its path. Keep backups private because they contain your account store. The ESP32 commits each site through its existing verified chunks and alternating snapshots. Updates are atomic per site, not across the entire batch: if sync stops after some sites complete, it reports the count, and you should compare again before retrying. Changed source content or changed destination content since comparison is rejected. A failed/disconnected upload is not published; its staged chunks are cancelled when possible or expire after five powered minutes/reboot. Existing device/account site quotas and the 512 KiB HTML/CSS/JS limit apply.

Passwords, account records and sessions are not synchronized. Both hosts enforce their existing ownership rules. The tool signs out its temporary sessions when it finishes. Keep the Bluetooth link paired/authenticated; it uses secure Classic SPP. No Wi-Fi or Internet is required during sync.

## Developer checks

`Bww.Server --sync --sync-tcp PORT --data /tmp/store.json` connects only to a loopback development peer, not Bluetooth. With the PC server built and .NET available, `python3 scripts/test_firmware.py` runs the actual C# sync client against the portable C++ firmware core using temporary stores and a loopback bridge. See [VALIDATION.md](VALIDATION.md) for results and physical-device limitations.

After publishing the Windows host into `artifacts/windows-x64`, run `python3 scripts/package_sync.py` to recreate the verified download ZIPs and checksums.

Firmware 0.6.0 stores website indexes in SD catalog pages and removes the eight-per-account/24-per-device site quotas. Use Windows sync 0.6.0 to compare all pages when a host has more than 32 sites. Both hosts now allow 50 websites per account in 0.6.1. Individual sites remain limited to 512 KiB. The SD-copy tool enforces the same quota when converting between formats.
