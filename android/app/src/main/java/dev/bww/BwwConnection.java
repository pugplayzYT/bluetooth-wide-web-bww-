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
    static final UUID SERVICE = UUID.fromString("731e9c72-48a1-4e6b-a842-d1ea7cc89010");
    private volatile BluetoothSocket socket;
    private InputStream input;
    private OutputStream output;
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor();

    void connect(BluetoothDevice device) throws Exception {
        try {
            socket = device.createRfcommSocketToServiceRecord(SERVICE);
            ScheduledFuture<?> timeout = timer.schedule(this::disconnect, 20, TimeUnit.SECONDS);
            try {
                socket.connect();
                input = new BufferedInputStream(socket.getInputStream());
                output = socket.getOutputStream();
            } finally { timeout.cancel(false); }
            JSONObject hello = request(new JSONObject().put("op", "hello"));
            if (hello.getInt("protocol") != 1) throw new IOException("Unsupported server protocol");
        } catch (SecurityException e) {
            disconnect();
            throw new IOException("Bluetooth permission was revoked. Grant permission and connect again.", e);
        } catch (Exception e) { disconnect(); throw e; }
    }
    synchronized JSONObject envelope(JSONObject request) throws Exception {
        if (socket == null || !socket.isConnected()) throw new IOException("Connect to a server first");
        ScheduledFuture<?> timeout = timer.schedule(this::disconnect, 20, TimeUnit.SECONDS);
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
        socket = null;
        if (s != null) try { s.close(); } catch (IOException ignored) { }
    }
    boolean connected() { BluetoothSocket s = socket; return s != null && s.isConnected(); }
    @Override public void close() { disconnect(); timer.shutdownNow(); }
    static final class ApiException extends IOException {
        final String code;
        ApiException(String code, String message) { super(message); this.code = code; }
    }
}
