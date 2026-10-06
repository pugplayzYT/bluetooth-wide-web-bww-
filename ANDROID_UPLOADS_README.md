# Android reconnects and saved uploads

[Download Android 0.6.3](https://raw.githubusercontent.com/pugplayzYT/bluetooth-wide-web-bww-/main/downloads/Bww-Android-0.6.3.apk) and install it over the earlier app to retain accounts, drafts and website local storage.

When Bluetooth drops during browsing, listing sites or opening an editor, the app shows a loading bar and makes up to two reconnect attempts to the same paired device. It does not switch to a different nearby host. Bluetooth cannot carry data while the host is out of range; the app waits for the connection to return.

## Publish and edit

Tap **Publish** to save the upload privately on the phone before sending it. The editor shows an indeterminate loading bar and a status message. Close the editor or switch apps: the connected-device foreground service continues working, with a **BWW website uploads** notification. Allow notification permission to see status and the cancel action in the notification shade. The notification explains that uploads can take a while, shows acknowledged bytes as chunks finish, and distinguishes transferring from saving/verifying on the host.

Android **0.6.1** renews its CPU wake lock every minute for the lifetime of the upload foreground service, including reconnect waits, rather than letting it expire after ten minutes. Each renewal has a ten-minute safety timeout, and service shutdown cancels renewals and releases the lock. You can press Home, switch apps, turn the screen off or swipe BWW out of recent apps while the service continues uploading. The upload service owns a separate Bluetooth socket from the browser, so closing the activity does not close the upload socket. The wake lock is released when the service stops after finishing/cancelling the queue or pausing it for review. It does not keep the display on. Existing saved uploads and drafts are retained; no firmware update is required.

An interrupted upload stays queued and reconnects after 5, 10, 20, then 30 seconds between attempts. Each connection/request also has its own timeout, so an attempt can take longer than that interval. Queued uploads survive process termination and resume when you reopen BWW; Android may also restart the service. Force-stopping the app, rebooting, or Android battery restrictions can stop or delay background work. Reopen BWW to resume it. Up to 16 uploads are retained, and uploads run one at a time.

The queue stores the site, paired Bluetooth address, account name and the original site's fingerprint. Passwords and session tokens are not copied into upload files. The service uses your saved session for that specific host and account. Expired sessions or revoked permissions pause uploads for review; sign in/grant permission again, reopen your saved draft and publish it.

The current **PC/ESP32 host 0.5.0** already supports conditional publication: no further host update is needed if you have that version. After reconnecting, the app checks the current site. If your content already committed and only the reply was lost, it finishes without publishing again. If another edit changed the original site, it pauses for review instead of overwriting that edit. An incomplete upload is restarted from the saved content, rather than resumed at a byte offset.

Older hosts still support initial publication. After an ambiguous interrupted write, an older host may require you to review and publish the saved draft again because it lacks conditional publication. This app update cannot add that host-side guarantee to old firmware.

## Cancel or review

Use **Uploads** to see pending uploads and cancel one, or use **Cancel upload** in its notification. Cancellation keeps the editor draft. It cannot undo a publication already accepted by the host. To review a paused edit, open **My Sites**, select the published site, review the restored draft against the latest version, then publish again. A paused new-site draft is available in **Create Site**.

Closing the editor keeps the upload running. While that editor is uploading, its code fields and Publish/Delete buttons are disabled to prevent accidental duplicate submissions. The Close button remains available. Separate new uploads for the same host/domain are blocked until the first finishes or is cancelled. Draft changes made after an upload was queued are retained when the older upload finishes.
