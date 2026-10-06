package dev.bww;
import android.Manifest;
import android.app.*;
import android.bluetooth.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import org.json.JSONObject;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;

/** A visible connected-device foreground service owns pending uploads while the app is backgrounded. */
public final class PublishService extends Service {
    static final String CHANGED = "dev.bww.UPLOAD_CHANGED", CANCEL = "cancel-upload", CHANNEL = "bww-uploads";
    private static final int NOTIFICATION = 42;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final BwwConnection connection = new BwwConnection();
    private volatile String currentId = "";
    private boolean running;
    private volatile int latestStart;
    private PowerManager.WakeLock wakeLock;
    private final Handler wakeHandler = new Handler(Looper.getMainLooper());
    private final Runnable renewWakeLock = new Runnable() {
        @Override public void run() {
            // Renewal keeps arbitrarily long uploads awake, with a safety
            // timeout if the service stops scheduling its heartbeat.
            wakeLock.acquire(10 * 60 * 1000L);
            wakeHandler.postDelayed(this, 60 * 1000L);
        }
    };
    private boolean completed;
    static void start(Context context) { context.startForegroundService(new Intent(context, PublishService.class)); }
    @Override public void onCreate() {
        super.onCreate(); getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL, "Website uploads", NotificationManager.IMPORTANCE_LOW));
        wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dev.bww:publish");
        wakeLock.setReferenceCounted(false);
        startForeground(NOTIFICATION, notification("Preparing queued uploads", null, true));
        // Scope CPU wakefulness to this foreground service, not a ten-minute
        // attempt. Long transfers and reconnect backoff must survive screen-off.
        renewWakeLock.run();
        connection.progress = message -> notifyStatus(message, currentId.isEmpty() ? null : currentId, true);
    }
    private Notification notification(String message, String id, boolean active) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_bww).setContentTitle("BWW website uploads").setContentText(message)
            .setStyle(new Notification.BigTextStyle().bigText(active
                ? message + "\nUploads can take a while, especially on ESP32. You can leave the app or turn off the screen; uploading continues in the background. Keep the host powered on and nearby."
                : message)).setContentIntent(open).setOnlyAlertOnce(true).setOngoing(active);
        if (active) builder.setSubText("Uploads can take a while");
        if (active) builder.setProgress(0, 0, true);
        if (id != null) {
            Intent cancel = new Intent(this, PublishService.class).setAction(CANCEL).putExtra("id", id);
            PendingIntent action = PendingIntent.getForegroundService(this, id.hashCode(), cancel, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.addAction(new Notification.Action.Builder(null, "Cancel upload", action).build());
        }
        return builder.build();
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStart = startId;
        if (intent != null && CANCEL.equals(intent.getAction())) {
            String id = intent.getStringExtra("id");
            try { if (id != null) PublishQueue.cancel(this, id); } catch (Exception e) { notifyStatus("Could not cancel upload: " + e.getMessage(), id, false); }
            if (currentId.equals(id)) connection.disconnect(); changed();
        }
        if (!running) { running = true; worker.execute(this::drain); }
        return START_STICKY;
    }
    private void changed() { sendBroadcast(new Intent(CHANGED).setPackage(getPackageName())); }
    private void notifyStatus(String message, String id, boolean active) { getSystemService(NotificationManager.class).notify(NOTIFICATION, notification(message, id, active)); }
    private boolean update(JSONObject job, String state, String message) throws Exception {
        job.put("state", state).put("message", message);
        boolean saved = PublishQueue.update(this, job); if (saved) { notifyStatus(message, "done".equals(state) ? null : job.getString("id"), "queued".equals(state)); changed(); } return saved;
    }
    private void drain() {
        try {
            while (!Thread.currentThread().isInterrupted()) {
                int iterationStart = latestStart;
                List<JSONObject> pending = PublishQueue.pending(this);
                JSONObject job = null;
                for (JSONObject item : pending) if (!"attention".equals(item.optString("state"))) { job = item; break; }
                if (job == null) {
                    // Serialize worker completion with new start commands on the service's main thread.
                    new Handler(Looper.getMainLooper()).post(() -> {
                        running = false;
                        if (iterationStart != latestStart) { running = true; worker.execute(this::drain); return; }
                        if (!pending.isEmpty()) { notifyStatus("An upload needs attention. Open BWW to review your saved draft.", pending.get(0).optString("id"), false); stopForeground(STOP_FOREGROUND_DETACH); }
                        else stopForeground(completed ? STOP_FOREGROUND_DETACH : STOP_FOREGROUND_REMOVE);
                        stopSelfResult(iterationStart);
                    });
                    return;
                }
                final JSONObject work = job; currentId = job.getString("id");
                int backoffSeconds = 0;
                try {
                    if (Build.VERSION.SDK_INT >= 31 && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED)
                        throw new PublishTransaction.ReviewRequired("Bluetooth permission is needed. Open BWW to grant it and retry.");
                    SharedPreferences prefs = getSharedPreferences("bww", MODE_PRIVATE);
                    String address = job.getString("address"), owner = job.getString("owner"), token = prefs.getString("token:" + address, "");
                    if (token.isEmpty() || !owner.equals(prefs.getString("user:" + address, ""))) throw new PublishTransaction.ReviewRequired("Sign in to this host again, then review and publish your saved draft.");
                    if (!update(job, "queued", "Connecting to your Bluetooth host…")) continue;
                    BluetoothAdapter adapter = getSystemService(BluetoothManager.class).getAdapter();
                    if (adapter == null || !adapter.isEnabled()) throw new IOException("Bluetooth is switched off");
                    // Never switch destinations based on a nearby name; keep the queued address.
                    connection.connect(adapter.getRemoteDevice(address));
                    JSONObject me = connection.request(new JSONObject().put("op", "me").put("token", token));
                    if (!owner.equals(me.getString("username"))) throw new PublishTransaction.ReviewRequired("The saved session belongs to another account.");
                    if (!update(job, "queued", "Publishing " + job.getString("domain") + "… Keep the host in range.")) continue;
                    PublishTransaction.attempt(new PublishTransaction.Peer() {
                        public PublishTransaction.Snapshot read() throws Exception {
                            try {
                                JSONObject site = connection.request(new JSONObject().put("op", "get").put("domain", work.getString("domain")));
                                return new PublishTransaction.Snapshot(site.getString("owner"), SiteFingerprint.of(site.getString("html"), site.getString("css"), site.getString("js")));
                            } catch (BwwConnection.ApiException e) { if ("not_found".equals(e.code)) return null; throw e; }
                        }
                        public boolean conditional() { return connection.safePublish(); }
                        public void write(String baseline) throws Exception {
                            work.put("interrupted", true);
                            if (!PublishQueue.update(PublishService.this, work)) throw new IOException("Upload cancelled");
                            JSONObject payload = new JSONObject().put("op", conditional() ? "sync_publish" : "publish").put("token", token).put("domain", work.getString("domain"))
                                .put("html", work.getString("html")).put("css", work.getString("css")).put("js", work.getString("js"));
                            if (conditional()) payload.put("expectedFingerprint", baseline);
                            connection.request(payload);
                        }
                    }, owner, job.getString("baseline"), job.getString("desired"), job.optBoolean("interrupted"));
                    JSONObject latest = PublishQueue.get(this, currentId);
                    if (latest == null || "cancelled".equals(latest.optString("state"))) continue;
                    // Clear only the exact draft that was sent; newer edits remain saved.
                    String key = job.getString("draftKey"), draft = prefs.getString(key, "");
                    if (!draft.isEmpty()) {
                        JSONObject saved = new JSONObject(draft);
                        if (job.getString("desired").equals(SiteFingerprint.of(saved.optString("html"), saved.optString("css"), saved.optString("js")))) prefs.edit().remove(key).apply();
                    }
                    PublishQueue.clearPayload(job); completed = update(job, "done", "Published · bww://" + job.getString("domain"));
                } catch (BwwConnection.ApiException | PublishTransaction.ReviewRequired e) {
                    update(job, "attention", e.getMessage() + " Your draft is saved.");
                } catch (IOException e) {
                    int attempts = job.optInt("attempts") + 1; int seconds = (int)Math.min(30, 5L << Math.min(attempts - 1, 3)); job.put("attempts", attempts);
                    if (update(job, "queued", "Connection interrupted. Upload saved; reconnecting in " + seconds + " seconds…")) backoffSeconds = seconds;
                } catch (Exception e) { update(job, "attention", "Upload needs review: " + e.getMessage()); }
                finally { connection.disconnect(); currentId = ""; }
                if (backoffSeconds > 0) Thread.sleep(backoffSeconds * 1000L);
            }
        } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        catch (Exception e) { notifyStatus("Upload queue needs attention: " + e.getMessage(), null, false); stopForeground(STOP_FOREGROUND_DETACH); stopSelf(); }
    }
    @Override public android.os.IBinder onBind(Intent intent) { return null; }
    @Override public void onDestroy() {
        wakeHandler.removeCallbacks(renewWakeLock);
        worker.shutdownNow(); connection.close();
        if (wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }
}
