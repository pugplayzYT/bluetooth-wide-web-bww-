using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Bww;
using InTheHand.Net.Sockets;

const string ServiceUuid = "731e9c72-48a1-4e6b-a842-d1ea7cc89010";
var tcp = args.Contains("--tcp");
var pathIndex = Array.IndexOf(args, "--data");
if (args.Contains("--help"))
{
    Console.WriteLine("Bww.Server [--tcp] [--port 8877] [--data /path/store.json]\nBww.Server --sync [--data /path/store.json]\nDefault: Windows Bluetooth RFCOMM. --sync compares/applies account websites to a selected Bluetooth ESP32. Stop this PC's host before sync. --sync-tcp PORT is loopback-only sync development transport.");
    return;
}
var dataPath = pathIndex >= 0 && pathIndex + 1 < args.Length ? args[pathIndex + 1] :
    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Bww", "store.json");
using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };
// A single process owns a store; concurrent servers must not overwrite each other's data.
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(dataPath))!);
using var storeLock = new FileStream(dataPath + ".lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
var store = new Store(dataPath);
if (args.Contains("--sync"))
{
    try { await SyncConsole.Run(store, dataPath, args, cancellation.Token); }
    catch (Exception e) { Console.Error.WriteLine($"Sync failed: {e.Message}"); Environment.ExitCode = 1; }
    return;
}
var slots = new SemaphoreSlim(16);
Console.WriteLine($"Bluetooth-wide Web · protocol 1 · storage: {Path.GetFullPath(dataPath)}");

async Task Serve(Stream stream, IDisposable client)
{
    using (client)
    using (stream)
    {
        try
        {
            var reader = new FrameReader(stream);
            while (!cancellation.IsCancellationRequested)
            {
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token);
                deadline.CancelAfter(TimeSpan.FromMinutes(2));
                var line = await reader.Read(deadline.Token);
                if (line == null) break;
                object reply;
                try
                {
                    using var document = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 16 });
                    if (document.RootElement.ValueKind != JsonValueKind.Object) throw new ApiError("invalid_request", "Expected a JSON object");
                    reply = new { ok = true, data = store.Execute(document.RootElement) };
                }
                catch (ApiError e) { reply = new { ok = false, error = e.Code, message = e.Message }; }
                catch (JsonException) { reply = new { ok = false, error = "invalid_json", message = "Invalid JSON request" }; }
                catch (IOException e) { Console.Error.WriteLine($"Storage error: {e.Message}"); reply = new { ok = false, error = "storage_error", message = "Could not save data; contact the server owner" }; }
                var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(reply) + "\n");
                await stream.WriteAsync(bytes, deadline.Token);
                await stream.FlushAsync(deadline.Token);
                await Task.Delay(100, cancellation.Token);
            }
        }
        catch (Exception e) when (e is IOException or OperationCanceledException or SocketException or DecoderFallbackException)
        { Console.WriteLine($"Client disconnected: {e.GetType().Name}"); }
        finally { slots.Release(); }
    }
}

try
{
    if (tcp)
    {
        var pi = Array.IndexOf(args, "--port");
        var port = pi >= 0 ? int.Parse(args[pi + 1]) : 8877;
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        Console.WriteLine($"READY TCP 127.0.0.1:{port} (development only)");
        try
        {
            while (!cancellation.IsCancellationRequested)
            {
                var client = await listener.AcceptTcpClientAsync(cancellation.Token);
                if (!slots.Wait(0)) { client.Dispose(); continue; }
                _ = Serve(client.GetStream(), client);
            }
        }
        finally { listener.Stop(); }
    }
    else
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Bluetooth hosting requires Windows. Use --tcp for development on other systems.");
        var listener = new BluetoothListener(Guid.Parse(ServiceUuid)) { ServiceName = "Bluetooth-wide Web" };
        listener.Start();
        Console.WriteLine($"READY Bluetooth · {ServiceUuid}\nPair your Android device with this computer in system Bluetooth settings, then connect in BWW.");
        using var registration = cancellation.Token.Register(listener.Stop);
        try
        {
            while (!cancellation.IsCancellationRequested)
            {
                var client = await Task.Run(listener.AcceptBluetoothClient);
                try { client.Authenticate = true; client.Encrypt = true; }
                catch (SocketException) { client.Dispose(); Console.Error.WriteLine("Rejected an unauthenticated Bluetooth connection"); continue; }
                if (!slots.Wait(0)) { client.Dispose(); continue; }
                _ = Serve(client.GetStream(), client);
            }
        }
        finally { listener.Stop(); }
    }
}
catch (Exception) when (cancellation.IsCancellationRequested) { }
catch (Exception e) { Console.Error.WriteLine($"Server could not start: {e.Message}"); Environment.ExitCode = 1; }

sealed class FrameReader(Stream stream)
{
    private readonly byte[] buffer = new byte[8192];
    private int offset, count;
    public async Task<string?> Read(CancellationToken ct)
    {
        using var frame = new MemoryStream();
        while (true)
        {
            if (offset == count)
            {
                count = await stream.ReadAsync(buffer, ct); offset = 0;
                if (count == 0) return frame.Length == 0 ? null : throw new IOException("Incomplete frame");
            }
            var end = Array.IndexOf(buffer, (byte)10, offset, count - offset);
            var length = end < 0 ? count - offset : end - offset;
            if (frame.Length + length > 4 * 1024 * 1024) throw new IOException("Request exceeds 4 MiB");
            frame.Write(buffer, offset, length);
            offset += length;
            if (end >= 0)
            {
                offset++;
                return new UTF8Encoding(false, true).GetString(frame.ToArray());
            }
        }
    }
}
