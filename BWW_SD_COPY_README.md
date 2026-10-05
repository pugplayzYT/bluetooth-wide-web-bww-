# BWW SD Copy

Copy your Bluetooth-wide Web websites and accounts **between the Windows C# server and an ESP32 SD card**. The tool converts their different storage formats, including the firmware's 512 KiB chunked sites. It never formats a drive, accesses a raw disk, or copies unrelated files from your card.

[Download the small tool ZIP](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-SD-Copy.zip) · [Download Python script only](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/bww_sd_copy.py)

## Run on Windows

1. Install **Python 3.10 or newer** from python.org if needed. Its normal Windows installer includes Tkinter; no extra Python packages are required.
2. Download and extract the tool ZIP. Double-click **Run-BWW-SD-Copy.bat**, or open a terminal in that folder and run:

   ```powershell
   py -3 bww_sd_copy.py
   ```

3. Stop the C# BWW server. Power off the ESP32, remove its SD card, and put the card in a computer card reader. The card must already be FAT32; this tool does not format or repair it.
4. Choose **Computer → SD card** or **SD card → Computer**.
5. Select the computer's `store.json`. The tool fills in the normal Windows location, `%LOCALAPPDATA%\Bww\store.json`. If you started the server with `--data`, select that file instead. For SD → Computer, you may choose a new destination `store.json` file.
6. Select the **SD card's drive root**, such as `E:\`, rather than a folder containing just your HTML files. The ESP32 uses a `bww` folder at the card root.
7. Click **Preview**. It lists accounts/sites to add, sites to update, and unchanged sites. Check that the selected drive and direction are right.
8. Check that both hosts are stopped, then click **Back up and copy** and review the confirmation. Backups go to `BwwBackups` in your Windows user folder; the success message gives the exact backup path.
9. Safely eject the card before putting it back into the powered-off ESP32. Start the ESP32 or desktop server and sign in on that host.

On Linux/macOS, run `python3 bww_sd_copy.py` with a graphical desktop and Tkinter installed. The window uses standard folder/file pickers. Windows GUI dialogs and physical card-reader operation still require a device check; the Linux cloud has no graphical display.

## What gets copied

- Accounts retain their usernames and original passwords. The tool converts existing salted PBKDF2-SHA256 hashes; it never asks for or stores plaintext passwords.
- Websites retain their domain, owner, HTML, CSS, and JavaScript. SD metadata and chunks get the checksums required by the firmware.
- New accounts/sites are added. Changed sites are updated only when the destination owner and account credentials match; the preview lists those updates.
- Destination-only accounts/sites stay in place. Matching sites do not cause a write. Account-credential conflicts and domains owned by someone else stop the copy without overwriting those records.
- Existing destination sessions stay valid. Source sign-in sessions are **not** copied because the hosts use different clocks and trust boundaries. Sign in on the other host after copying.
- Website `localStorage` scores and native editor drafts live on each Android phone; this tool does not copy them. Browser storage remains separate between the computer and ESP32.

This is a manual copy, not live synchronization. If both hosts edit a site differently, the selected **source** wins for that site after you approve the preview. The ESP32 supports **12 accounts, 24 sites total, 8 sites per account, and 512 KiB combined assets per site**. The tool refuses a copy that exceeds those limits. Use firmware and Android **0.4.0 or newer** for the chunked SD site format.

The desktop server is locked during copying, and input changes since preview stop the operation. The tool backs up the destination before writing, verifies saved files, writes new SD site generations before committing an inactive state snapshot, and retains the previous valid snapshot. It refuses broken stores or both-damaged SD snapshots instead of resetting accounts. FAT/SD hardware still needs stable power and safe ejection; backups contain password hashes and session digests, so keep them private.

## Restore a backup

Keep both hosts stopped. The backup folder contains `COPY_PLAN.txt` and the prior destination data:

- **Desktop backup:** copy its `store.json` back to the destination path recorded in `COPY_PLAN.txt`.
- **SD backup:** restore its complete `bww` folder at the card root. Save the current card data elsewhere first; use the backup folder as a complete replacement to avoid mixing snapshots and chunks from different versions.
- **New empty destination:** the backup contains only the plan because there was no previous BWW data to copy.

If copying reports an error, it gives the backup path. Existing SD snapshots are retained until the commit; a failed copy may leave unreferenced site files. A retry chooses a fresh site generation, and the firmware prunes unreferenced generations on boot. Do not format the card to resolve a tool error.

## Command line

Without `--apply`, commands only preview; they do not create BWW files or backups:

```powershell
py -3 bww_sd_copy.py --computer "C:\Users\You\AppData\Local\Bww\store.json" --sd "E:\"
py -3 bww_sd_copy.py --computer "C:\Users\You\AppData\Local\Bww\store.json" --sd "E:\" --apply
py -3 bww_sd_copy.py --direction to-computer --computer "C:\Bww\imported-store.json" --sd "E:\" --apply
```

Optional: `--backup-dir "C:\BwwBackups"`. Choose a backup folder on the computer, outside the SD card. For a new desktop store, run the server with its location: `Bww.Server.exe --data C:\Bww\imported-store.json`.

Developers can run `python3 tests/test_sd_copy.py`. It exercises conversions, 512 KiB Unicode content, checksum verification, conflicts, limits, backups, failed commits/retries, sessions, preview/change detection, CLI use, and unsafe paths. Optional compatibility cases use `BWW_FIRMWARE_HARNESS` and a built .NET server (`BWW_DOTNET` if `dotnet` is not on PATH). The firmware's native test runner executes the copy tests with its actual C++ harness as well.
