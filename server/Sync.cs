using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using InTheHand.Net.Sockets;
namespace Bww;

public interface ISyncPeer { Task<JsonElement> Call(object request); }
public sealed class LocalSyncPeer(Store store) : ISyncPeer
{
    public Task<JsonElement> Call(object request) => Task.FromResult(JsonSerializer.SerializeToElement(store.Execute(JsonSerializer.SerializeToElement(request))));
}
public sealed class WireSyncPeer(Stream stream, CancellationToken cancellation) : ISyncPeer
{
    private readonly FrameReader reader = new(stream);
    public async Task<JsonElement> Call(object request)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromMinutes(2));
        using var registration = deadline.Token.Register(stream.Close);
        await stream.WriteAsync(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(request) + "\n"), deadline.Token);
        await stream.FlushAsync(deadline.Token);
        var line = await reader.Read(deadline.Token) ?? throw new IOException("Sync peer disconnected");
        using var reply = JsonDocument.Parse(line, new JsonDocumentOptions { MaxDepth = 16 });
        if (!reply.RootElement.GetProperty("ok").GetBoolean())
            throw new ApiError(reply.RootElement.GetProperty("error").GetString()!, reply.RootElement.GetProperty("message").GetString()!);
        return reply.RootElement.GetProperty("data").Clone();
    }
}
public sealed record SyncSite(string Domain, string Owner, string Fingerprint);
public sealed record SyncDifference(string Domain, SyncSite? Pc, SyncSite? Device, string? Blocked = null);
public sealed class SiteSync(ISyncPeer pc, ISyncPeer device, string pcToken, string deviceToken)
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    public async Task<List<SyncDifference>> Compare()
    {
        async Task<Dictionary<string, SyncSite>> Manifest(ISyncPeer peer, string token)
        {
            var owner = (await peer.Call(new { op = "me", token })).GetProperty("username").GetString();
            var result = new Dictionary<string, SyncSite>(StringComparer.Ordinal);
            foreach (var entry in (await peer.Call(new { op = "sync_manifest", token })).EnumerateArray())
            {
                var domain = entry.GetProperty("domain").GetString()!;
                var fingerprint = entry.GetProperty("fingerprint").GetString()!;
                if (Store.Domain(domain) != domain || entry.GetProperty("owner").GetString() != owner || fingerprint.Length != 64 ||
                    fingerprint.Any(c => !"0123456789abcdef".Contains(c)) || !result.TryAdd(domain, new(domain, owner!, fingerprint)))
                    throw new IOException("Invalid sync manifest");
            }
            return result;
        }
        var left = await Manifest(pc, pcToken); var right = await Manifest(device, deviceToken);
        var leftDomains = (await pc.Call(new { op = "list" })).EnumerateArray().Select(e => e.GetProperty("domain").GetString()!).ToHashSet();
        var rightDomains = (await device.Call(new { op = "list" })).EnumerateArray().Select(e => e.GetProperty("domain").GetString()!).ToHashSet();
        return left.Keys.Union(right.Keys).OrderBy(s => s, StringComparer.Ordinal).Select(domain =>
            new SyncDifference(domain, left.GetValueOrDefault(domain), right.GetValueOrDefault(domain),
                !left.ContainsKey(domain) && leftDomains.Contains(domain) ? "domain belongs to another account on PC" :
                !right.ContainsKey(domain) && rightDomains.Contains(domain) ? "domain belongs to another account on device" : null))
            .Where(d => d.Pc?.Fingerprint != d.Device?.Fingerprint).ToList();
    }
    public async Task Copy(SyncDifference change, bool pcToDevice)
    {
        if (change.Blocked != null) throw new IOException(change.Blocked);
        var source = pcToDevice ? pc : device; var destination = pcToDevice ? device : pc;
        var token = pcToDevice ? deviceToken : pcToken;
        var before = pcToDevice ? change.Device : change.Pc;
        var expected = pcToDevice ? change.Pc : change.Device;
        if (expected == null) throw new IOException("The selected source does not have this website");
        var site = await source.Call(new { op = "get", domain = change.Domain });
        if (site.GetProperty("owner").GetString() != expected.Owner) throw new IOException("Source ownership changed; compare again");
        var assets = new Dictionary<string, string>(); long total = 0;
        foreach (var asset in new[] { "html", "css", "js" })
        {
            if (site.TryGetProperty("transferMode", out var mode) && mode.GetString() == "chunk-v1")
            {
                using var content = new MemoryStream(); int index = 0;
                foreach (var item in site.GetProperty("chunks").GetProperty(asset).EnumerateArray())
                {
                    int bytes = item.GetProperty("bytes").GetInt32();
                    if (bytes < 1 || bytes > 8192 || total + bytes > 524288) throw new IOException("Invalid site chunk length");
                    var chunk = await source.Call(new { op = "get_chunk", domain = change.Domain, revision = site.GetProperty("revision").GetInt64(), asset, index });
                    var data = Convert.FromHexString(chunk.GetProperty("data").GetString()!);
                    if (data.Length != bytes || Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant() != item.GetProperty("hash").GetString())
                        throw new IOException("Source chunk checksum mismatch");
                    content.Write(data); total += bytes; ++index;
                }
                assets[asset] = Utf8.GetString(content.ToArray());
            }
            else { assets[asset] = site.GetProperty(asset).GetString()!; total += Utf8.GetByteCount(assets[asset]); }
        }
        if (total > 524288 || SiteFingerprint.Of(assets["html"], assets["css"], assets["js"]) != expected.Fingerprint)
            throw new IOException("Source changed since comparison; compare again");
        var hello = await destination.Call(new { op = "hello" });
        if (hello.GetProperty("siteSync").GetString() != "account-v1") throw new IOException("Peer does not support safe sync");
        if (hello.TryGetProperty("siteTransfer", out var transferMode) && transferMode.GetString() == "chunk-v1")
        {
            var begin = await destination.Call(new { op = "sync_publish_begin", token, domain = change.Domain, expectedFingerprint = before?.Fingerprint ?? "missing" });
            var transfer = begin.GetProperty("transfer").GetString();
            try
            {
                int limit = begin.GetProperty("chunkBytes").GetInt32();
                if (limit < 4 || limit > 8192) throw new IOException("Invalid upload chunk size");
                foreach (var asset in assets)
                {
                    int index = 0;
                    foreach (var chunk in SiteFingerprint.Chunks(asset.Value, limit))
                        await destination.Call(new { op = "publish_chunk", token, transfer, asset = asset.Key, index = index++, data = Convert.ToHexString(chunk).ToLowerInvariant() });
                }
                await destination.Call(new { op = "publish_commit", token, transfer });
            }
            catch
            {
                try { await destination.Call(new { op = "publish_cancel", token, transfer }); } catch { }
                throw;
            }
        }
        else await destination.Call(new { op = "sync_publish", token, domain = change.Domain, expectedFingerprint = before?.Fingerprint ?? "missing", html = assets["html"], css = assets["css"], js = assets["js"] });
    }
}
public static class SyncConsole
{
    private static string Input(string prompt) { Console.Write(prompt); return Console.ReadLine() ?? throw new IOException("Input closed"); }
    private static string Password(string prompt)
    {
        Console.Write(prompt);
        if (Console.IsInputRedirected) return Console.ReadLine() ?? throw new IOException("Input closed");
        var text = new StringBuilder();
        while (true) { var key = Console.ReadKey(true); if (key.Key == ConsoleKey.Enter) break; if (key.Key == ConsoleKey.Backspace) { if (text.Length > 0) text.Length--; } else if (!char.IsControl(key.KeyChar)) text.Append(key.KeyChar); }
        Console.WriteLine(); return text.ToString();
    }
    public static async Task Run(Store store, string dataPath, string[] args, CancellationToken cancellation)
    {
        BluetoothClient? bluetooth = null; TcpClient? tcp = null; Stream? stream = null;
        try
        {
            if (args.Contains("--sync-tcp"))
            {
                int index = Array.IndexOf(args, "--sync-tcp"); int port = int.Parse(args[index + 1]);
                tcp = new TcpClient(); await tcp.ConnectAsync(IPAddress.Loopback, port, cancellation); stream = tcp.GetStream();
            }
            else
            {
                if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Bluetooth sync requires Windows; --sync-tcp PORT is loopback development mode");
                bluetooth = new BluetoothClient(); Console.WriteLine("Looking for nearby/paired Bluetooth hosts…");
                var devices = bluetooth.DiscoverDevices().ToArray();
                for (int i = 0; i < devices.Length; ++i) Console.WriteLine($"{i + 1}. {devices[i].DeviceName} · {devices[i].DeviceAddress} · {(devices[i].Authenticated ? "paired" : "pairing required")}");
                if (!int.TryParse(Input("Select device number: "), out int selected) || selected < 1 || selected > devices.Length) throw new IOException("No valid device selected");
                var device = devices[selected - 1];
                if (!device.Authenticated)
                {
                    Console.WriteLine("Pair this device in Windows Bluetooth settings. Compare the code and approve on the ESP32 using BOOT or its serial monitor.");
                    Process.Start(new ProcessStartInfo("ms-settings:bluetooth") { UseShellExecute = true });
                    Input("Press Enter after pairing: ");
                    if (!bluetooth.PairedDevices.Any(d => d.DeviceAddress.Equals(device.DeviceAddress))) throw new IOException("Device is not paired yet; pair and retry");
                }
                bluetooth.Authenticate = true; bluetooth.Encrypt = true;
                await bluetooth.ConnectAsync(device.DeviceAddress, Guid.Parse("00001101-0000-1000-8000-00805f9b34fb")).WaitAsync(TimeSpan.FromSeconds(30), cancellation);
                stream = bluetooth.GetStream();
            }
            ISyncPeer pc = new LocalSyncPeer(store), remote = new WireSyncPeer(stream, cancellation);
            var hello = await remote.Call(new { op = "hello" });
            if (hello.GetProperty("protocol").GetInt32() != 1 || !hello.TryGetProperty("siteSync", out var sync) || sync.GetString() != "account-v1")
                throw new IOException("Update this host's firmware to a version supporting account-v1 sync");
            Console.WriteLine("Sync websites for the same username on both hosts. Existing accounts are required. Passwords and sessions stay on their own hosts.");
            string username = Input("Username: ").Trim().ToLowerInvariant();
            var pcLogin = await pc.Call(new { op = "login", username, password = Password("PC account password: ") });
            string pcToken = pcLogin.GetProperty("token").GetString()!; string? remoteToken = null;
            try
            {
                Console.WriteLine("Signing in on the device; ESP32 password checking can take 10–20 seconds or longer…");
                remoteToken = (await remote.Call(new { op = "login", username, password = Password("Device account password: ") })).GetProperty("token").GetString()!;
                var engine = new SiteSync(pc, remote, pcToken, remoteToken); var differences = await engine.Compare();
                if (differences.Count == 0) { Console.WriteLine("Websites are already in sync."); return; }
                foreach (var d in differences) Console.WriteLine($"{d.Domain}: {(d.Blocked != null ? "blocked: " + d.Blocked : d.Pc == null ? "device only" : d.Device == null ? "PC only" : "different content")}");
                var selected = new List<(SyncDifference Change, bool Outbound)>();
                foreach (var d in differences)
                {
                    if (d.Blocked != null) continue;
                    string choice = Input($"{d.Domain}: {(d.Pc != null ? "[P] PC → device " : "")}{(d.Device != null ? "[D] device → PC " : "")}[Enter] skip: ").Trim().ToUpperInvariant();
                    if (choice == "P" && d.Pc != null) selected.Add((d, true));
                    else if (choice == "D" && d.Device != null) selected.Add((d, false));
                    else if (choice.Length != 0) throw new IOException("Invalid choice; no changes applied");
                }
                if (selected.Count == 0) { Console.WriteLine("No changes selected."); return; }
                Console.WriteLine("Selected changes:"); foreach (var s in selected) Console.WriteLine($"{s.Change.Domain}: {(s.Outbound ? "PC → device" : "device → PC")}");
                if (Input("Type APPLY to accept these changes: ") != "APPLY") { Console.WriteLine("Cancelled; no websites changed."); return; }
                if (selected.Any(s => !s.Outbound))
                {
                    string backup = dataPath + ".sync-backup-" + Guid.NewGuid().ToString("N"); File.Copy(dataPath, backup);
                    Console.WriteLine($"PC backup: {backup}");
                }
                int completed = 0;
                foreach (var s in selected)
                {
                    cancellation.ThrowIfCancellationRequested();
                    try { await engine.Copy(s.Change, s.Outbound); ++completed; Console.WriteLine($"Synced {s.Change.Domain}"); }
                    catch (Exception e) { throw new IOException($"Sync stopped after {completed} completed site(s): {e.Message}. Compare again before retrying.", e); }
                }
                Console.WriteLine("Selected websites synced. No websites were deleted.");
            }
            finally
            {
                try { await pc.Call(new { op = "logout", token = pcToken }); } catch { }
                if (remoteToken != null) try { await remote.Call(new { op = "logout", token = remoteToken }); } catch { }
            }
        }
        finally { stream?.Dispose(); bluetooth?.Dispose(); tcp?.Dispose(); }
    }
}
