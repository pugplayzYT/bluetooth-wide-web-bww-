package dev.bww;

import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothSocket;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.*;

/** One request and response at a time; newline-delimited UTF-8 JSON over secure RFCOMM. */
final class BwwConnection implements Closeable {
    static final UUID SERVICE = BluetoothServices.BWW;
    private volatile boolean validated;
    private volatile int chunkBytes;
    private volatile int maxSiteBytes = 524288;
    int maxSiteBytes() { return maxSiteBytes; }
    private volatile BluetoothSocket socket;
    private InputStream input;
    private OutputStream output;
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor();

    private static void closeSocket(BluetoothSocket socket) { try { socket.close(); } catch (IOException ignored) { } }
    void connect(BluetoothDevice device) throws Exception {
        disconnect();
        try {
            Exception last = null;
            for (UUID service : BluetoothServices.forDevice(device.getName())) {
                BluetoothSocket attempt = device.createRfcommSocketToServiceRecord(service);
                socket = attempt;
                ScheduledFuture<?> timeout = timer.schedule(() -> closeSocket(attempt), 20, TimeUnit.SECONDS);
                try {
                    attempt.connect();
                    input = new BufferedInputStream(attempt.getInputStream());
                    output = attempt.getOutputStream();
                } catch (IOException e) { last = e; disconnect(); continue; }
                finally { timeout.cancel(false); }
                try {
                    JSONObject hello = request(new JSONObject().put("op", "hello"));
                    if (hello.getInt("protocol") != 1) throw new IOException("Unsupported server protocol");
                    maxSiteBytes = BluetoothServices.siteLimit(hello.optInt("maxSiteBytes", 524288));
                    if ("chunk-v1".equals(hello.optString("siteTransfer"))) {
                        chunkBytes = hello.getInt("chunkBytes");
                        if (chunkBytes < 4 || chunkBytes > SiteChunks.MAX_CHUNK_BYTES) throw new IOException("Unsupported server chunk size");
                    }
                    validated = true; return;
                } catch (IOException | org.json.JSONException | IllegalArgumentException e) { last = e; disconnect(); }
            }
            throw new IOException("Could not connect to a BWW server. Check the computer/ESP32 is running and paired.", last);
        } catch (SecurityException e) {
            disconnect();
            throw new IOException("Bluetooth permission was revoked. Grant permission and connect again.", e);
        }
    }
    synchronized JSONObject envelope(JSONObject request) throws Exception {
        if (socket == null || !socket.isConnected()) throw new IOException("Connect to a server first");
        if (!validated && !"hello".equals(request.optString("op"))) throw new IOException("BWW handshake is required before account or site requests");
        BluetoothSocket current = socket;
        String op = request.optString("op");
        int seconds = "register".equals(op) || "login".equals(op) ? 120 : 60;
        ScheduledFuture<?> timeout = timer.schedule(() -> closeSocket(current), seconds, TimeUnit.SECONDS);
        try {
            byte[] bytes = (request.toString() + "\n").getBytes(StandardCharsets.UTF_8);
            if (bytes.length > 4 * 1024 * 1024) throw new IOException("Request is too large");
            output.write(bytes); output.flush();
            ByteArrayOutputStream frame = new ByteArrayOutputStream();
            int b;
            while ((b = input.read()) != '\n') {
                if (b < 0) throw new EOFException("Server disconnected");
                if (frame.size() >= 4 * 1024 * 1024) throw new IOException("Server response is too large");
                frame.write(b);
            }
            JSONObject reply = new JSONObject(frame.toString("UTF-8"));
            if (!reply.getBoolean("ok")) throw new ApiException(reply.getString("error"), reply.getString("message"));
            return reply;
        } catch (ApiException e) { throw e; }
        catch (IOException e) { disconnect(); throw e; }
        finally { timeout.cancel(false); }
    }
    private JSONObject direct(JSONObject request) throws Exception { return envelope(request).getJSONObject("data"); }
    synchronized JSONObject request(JSONObject request) throws Exception {
        if (chunkBytes > 0 && "publish".equals(request.optString("op"))) return publishChunks(request);
        JSONObject result = direct(request);
        if ("get".equals(request.optString("op")) && "chunk-v1".equals(result.optString("transferMode"))) {
            JSONObject chunks = result.getJSONObject("chunks"); long total = 0; int count = 0;
            for (String asset : new String[]{"html", "css", "js"}) {
                org.json.JSONArray entries = chunks.getJSONArray(asset); ByteArrayOutputStream content = new ByteArrayOutputStream();
                for (int i = 0; i < entries.length(); ++i) {
                    if (++count > maxSiteBytes / SiteChunks.MAX_CHUNK_BYTES + 3) throw new IOException("Too many site chunks");
                    int expected = entries.getJSONObject(i).getInt("bytes");
                    if (expected < 1 || expected > SiteChunks.MAX_CHUNK_BYTES || total + expected > maxSiteBytes) throw new IOException("Site exceeds server size limit");
                    JSONObject reply = direct(new JSONObject().put("op","get_chunk").put("domain",result.getString("domain")).put("revision",result.getLong("revision")).put("asset",asset).put("index",i));
                    byte[] bytes = SiteChunks.unhex(reply.getString("data"));
                    if (bytes.length != expected) throw new IOException("Site chunk length mismatch");
                    content.write(bytes); total += bytes.length;
                }
                result.put(asset, SiteChunks.utf8(content.toByteArray()));
            }
        }
        return result;
    }
    private JSONObject publishChunks(JSONObject request) throws Exception {
        String token = request.getString("token"); long total = 0;
        for (String asset : new String[]{"html", "css", "js"}) total += request.getString(asset).getBytes(StandardCharsets.UTF_8).length;
        if (total > maxSiteBytes) throw new IOException("Site exceeds server size limit");
        JSONObject begin = direct(new JSONObject().put("op","publish_begin").put("token",token).put("domain",request.getString("domain")));
        String transfer = begin.getString("transfer");
        try {
            for (String asset : new String[]{"html", "css", "js"}) {
                byte[] bytes = request.getString(asset).getBytes(StandardCharsets.UTF_8); int index = 0;
                for (int start = 0; start < bytes.length; ++index) {
                    int end = SiteChunks.end(bytes, start, chunkBytes);
                    direct(new JSONObject().put("op","publish_chunk").put("token",token).put("transfer",transfer).put("asset",asset).put("index",index).put("data",SiteChunks.hex(bytes,start,end)));
                    start = end;
                }
            }
            return direct(new JSONObject().put("op","publish_commit").put("token",token).put("transfer",transfer));
        } catch (Exception e) {
            if (connected()) try { direct(new JSONObject().put("op","publish_cancel").put("token",token).put("transfer",transfer)); } catch (Exception ignored) { }
            throw e;
        }
    }
    void disconnect() {
        BluetoothSocket s = socket;
        socket = null; validated = false; chunkBytes = 0; maxSiteBytes = 524288;
        if (s != null) try { s.close(); } catch (IOException ignored) { }
    }
    boolean connected() { BluetoothSocket s = socket; return validated && s != null && s.isConnected(); }
    @Override public void close() { disconnect(); timer.shutdownNow(); }
    static final class ApiException extends IOException {
        final String code;
        ApiException(String code, String message) { super(message); this.code = code; }
    }
}
