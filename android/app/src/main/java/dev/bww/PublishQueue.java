package dev.bww;
import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Private, atomic files retain website payloads across process death. No tokens/passwords. */
final class PublishQueue {
    private static File folder(Context context) { File folder = new File(context.getFilesDir(), "publish-queue"); if (!folder.isDirectory() && !folder.mkdirs()) throw new IllegalStateException("Could not open upload queue"); return folder; }
    private static File file(Context context, String id) { if (!id.matches("[a-f0-9-]{36}")) throw new IllegalArgumentException("Invalid queue id"); return new File(folder(context), id + ".json"); }
    static synchronized JSONObject get(Context context, String id) throws Exception {
        File path = file(context, id); if (!path.exists() && !new File(path + ".bak").exists()) return null;
        return new JSONObject(new String(new AtomicFile(path).readFully(), StandardCharsets.UTF_8));
    }
    static synchronized void save(Context context, JSONObject job) throws Exception {
        AtomicFile atomic = new AtomicFile(file(context, job.getString("id"))); FileOutputStream stream = null;
        try { stream = atomic.startWrite(); stream.write(job.toString().getBytes(StandardCharsets.UTF_8)); atomic.finishWrite(stream); }
        catch (Exception e) { if (stream != null) atomic.failWrite(stream); throw e; }
    }
    static synchronized boolean update(Context context, JSONObject job) throws Exception {
        JSONObject current = get(context, job.getString("id"));
        if (current == null || "cancelled".equals(current.optString("state")) || "done".equals(current.optString("state"))) return false;
        save(context, job); return true;
    }
    static synchronized List<JSONObject> pending(Context context) throws Exception {
        List<JSONObject> jobs = new ArrayList<>(); File[] files = folder(context).listFiles(); if (files == null) throw new IOException("Could not read upload queue");
        Set<String> ids = new HashSet<>();
        for (File path : files) if (path.getName().matches("[a-f0-9-]{36}\\.json(\\.bak)?")) ids.add(path.getName().substring(0, 36));
        for (String id : ids) { JSONObject job = get(context, id); if (job == null) continue;
            if (!job.optString("state").equals("done") && !job.optString("state").equals("cancelled")) jobs.add(job);
            else if (System.currentTimeMillis() - job.optLong("created") > 86400000) new AtomicFile(file(context, id)).delete();
        }
        jobs.sort(Comparator.comparingLong(j -> j.optLong("created"))); return jobs;
    }
    static synchronized String enqueue(Context context, String address, String owner, String draftKey, JSONObject payload, String baseline) throws Exception {
        List<JSONObject> pending = pending(context);
        for (JSONObject job : pending) if (address.equals(job.getString("address")) && payload.getString("domain").equals(job.getString("domain"))) {
            if (!"attention".equals(job.optString("state"))) throw new IOException("This site already has a queued upload. Cancel it from the notification before replacing it.");
            cancel(context, job.getString("id"));
        }
        if (pending.size() >= 16) throw new IOException("Upload queue is full. Finish or cancel an upload first.");
        JSONObject job = new JSONObject().put("id", UUID.randomUUID().toString()).put("created", System.currentTimeMillis()).put("address", address).put("owner", owner).put("draftKey", draftKey)
            .put("domain", payload.getString("domain")).put("html", payload.getString("html")).put("css", payload.getString("css")).put("js", payload.getString("js"))
            .put("baseline", baseline).put("desired", SiteFingerprint.of(payload.getString("html"), payload.getString("css"), payload.getString("js"))).put("state", "queued").put("message", "Queued for publishing");
        save(context, job); return job.getString("id");
    }
    static synchronized void cancel(Context context, String id) throws Exception {
        JSONObject job = get(context, id); if (job == null || "done".equals(job.optString("state"))) return;
        job.put("state", "cancelled").put("message", "Upload cancelled. Your draft is saved."); clearPayload(job); save(context, job);
    }
    static void clearPayload(JSONObject job) throws Exception { for (String asset : new String[]{"html", "css", "js"}) job.put(asset, ""); }
}
