package dev.bww;

import android.content.Context;
import android.content.ContextWrapper;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real Android AtomicFile persistence; isolated from the user's queue and drafts. */
@RunWith(AndroidJUnit4.class)
public class PublishQueueTest {
    private Context context;
    private File root;
    @Before public void prepare() {
        Context base = ApplicationProvider.getApplicationContext();
        root = new File(base.getCacheDir(), "queue-test-" + UUID.randomUUID());
        context = new ContextWrapper(base) { @Override public File getFilesDir() { return root; } };
    }
    @After public void cleanup() { remove(root); }
    private void remove(File file) {
        File[] children = file.listFiles(); if (children != null) for (File child : children) remove(child);
        file.delete();
    }
    private String enqueue(String address) throws Exception {
        return PublishQueue.enqueue(context, address, "alice", "draft:test",
            new JSONObject().put("domain", "test.bww").put("html", "<h1>Hello</h1>").put("css", "").put("js", ""), "missing");
    }
    @Test public void interruptedAttemptPersistsWithoutCredentials() throws Exception {
        String id = enqueue("AA:00:00:00:00:01"); JSONObject job = PublishQueue.get(context, id);
        job.put("interrupted", true); assertTrue(PublishQueue.update(context, job));
        JSONObject reopened = PublishQueue.pending(context).get(0);
        assertTrue(reopened.getBoolean("interrupted")); assertEquals("<h1>Hello</h1>", reopened.getString("html"));
        assertFalse(reopened.has("token")); assertFalse(reopened.has("password"));
    }
    @Test public void cancellationCannotBeOverwrittenByStaleWorker() throws Exception {
        String id = enqueue("AA:00:00:00:00:01"); JSONObject stale = PublishQueue.get(context, id);
        PublishQueue.cancel(context, id); stale.put("state", "done"); assertFalse(PublishQueue.update(context, stale));
        assertEquals("cancelled", PublishQueue.get(context, id).getString("state")); assertTrue(PublishQueue.pending(context).isEmpty());
        assertEquals("", PublishQueue.get(context, id).getString("html"));
    }
    @Test public void destinationsRemainSeparateAndDuplicateIsRejected() throws Exception {
        enqueue("AA:00:00:00:00:01"); enqueue("AA:00:00:00:00:02");
        try { enqueue("AA:00:00:00:00:01"); fail("Duplicate queued destination"); } catch (java.io.IOException expected) { }
        assertEquals(2, PublishQueue.pending(context).size());
    }
}
