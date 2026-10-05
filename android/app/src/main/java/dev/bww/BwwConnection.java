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
    JSONObject request(JSONObject request) throws Exception { return envelope(request).getJSONObject("data"); }
    void disconnect() {
        BluetoothSocket s = socket;
        socket = null; validated = false; maxSiteBytes = 524288;
        if (s != null) try { s.close(); } catch (IOException ignored) { }
    }
    boolean connected() { BluetoothSocket s = socket; return validated && s != null && s.isConnected(); }
    @Override public void close() { disconnect(); timer.shutdownNow(); }
    static final class ApiException extends IOException {
        final String code;
        ApiException(String code, String message) { super(message); this.code = code; }
    }
}
