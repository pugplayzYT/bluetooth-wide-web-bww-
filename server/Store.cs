using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Bww;

public sealed record User(string Name, string Salt, string Hash);
public sealed record Session(string User, DateTimeOffset Expires);
public sealed record Site(string Domain, string Owner, string Html, string Css, string Js, DateTimeOffset Updated);
public sealed class State
{
    public Dictionary<string, User> Users { get; set; } = new();
    public Dictionary<string, Session> Sessions { get; set; } = new();
    public Dictionary<string, Site> Sites { get; set; } = new();
}
public sealed class ApiError(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}
public sealed class Store
{
    private State state;
    private readonly string path;
    private readonly object gate = new();
    public Store(string path)
    {
        this.path = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(this.path)!);
        state = File.Exists(this.path)
            ? JsonSerializer.Deserialize<State>(File.ReadAllText(this.path)) ?? throw new IOException("Invalid store")
            : new State();
    }
    private static string Field(JsonElement r, string name, int max = 1024)
    {
        if (!r.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.String)
            throw new ApiError("invalid_request", $"Missing string: {name}");
        var s = v.GetString()!;
        if (Encoding.UTF8.GetByteCount(s) > max) throw new ApiError("too_large", $"{name} is too large");
        return s;
    }
    public static string Domain(string input)
    {
        var name = input.Trim().ToLowerInvariant();
        if (name.EndsWith(".bww")) name = name[..^4];
        if (!Regex.IsMatch(name, @"\A[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\z"))
            throw new ApiError("invalid_domain", "Use 1–63 letters, numbers, or internal hyphens");
        return name + ".bww";
    }
    private static string HashPassword(string password, byte[] salt) => Convert.ToBase64String(
        Rfc2898DeriveBytes.Pbkdf2(password, salt, 210_000, HashAlgorithmName.SHA256, 32));
    private static string TokenKey(string token) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
    private string Identity(JsonElement r)
    {
        var token = Field(r, "token", 128);
        if (!state.Sessions.TryGetValue(TokenKey(token), out var session) || session.Expires <= DateTimeOffset.UtcNow)
            throw new ApiError("unauthorized", "Sign in again; your session is missing or expired");
        return session.User;
    }
    private void Save()
    {
        // Serialize and replace atomically. A failed write never leaves the process with unsaved changes.
        var temp = path + ".tmp";
        try
        {
            using (var f = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temp, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                JsonSerializer.Serialize(f, state);
                f.Flush(true);
            }
            File.Move(temp, path, true);
        }
        catch
        {
            state = File.Exists(path) ? JsonSerializer.Deserialize<State>(File.ReadAllText(path))! : new State();
            throw;
        }
    }
    public object Execute(JsonElement r)
    {
        lock (gate)
        {
            var op = Field(r, "op", 32);
            switch (op)
            {
                case "hello": return new { protocol = 1, name = "Bluetooth-wide Web", maxSiteBytes = 524288 };
                case "register":
                case "login":
                {
                    var name = Field(r, "username", 32).Trim().ToLowerInvariant();
                    var password = Field(r, "password", 256);
                    if (!Regex.IsMatch(name, @"\A[a-z0-9_]{3,32}\z")) throw new ApiError("invalid_username", "Use 3–32 letters, numbers, or underscores");
                    if (op == "register")
                    {
                        if (password.Length < 10) throw new ApiError("weak_password", "Use at least 10 characters");
                        if (state.Users.Count >= 10000) throw new ApiError("capacity", "Server account limit reached");
                        if (state.Users.ContainsKey(name)) throw new ApiError("username_taken", "Username is already registered");
                        var salt = RandomNumberGenerator.GetBytes(16);
                        state.Users[name] = new User(name, Convert.ToBase64String(salt), HashPassword(password, salt));
                    }
                    else
                    {
                        // Perform a password derivation even for unknown users.
                        state.Users.TryGetValue(name, out var user);
                        var hash = HashPassword(password, user == null ? new byte[16] : Convert.FromBase64String(user.Salt));
                        if (user == null || !CryptographicOperations.FixedTimeEquals(Convert.FromBase64String(hash), Convert.FromBase64String(user.Hash)))
                            throw new ApiError("invalid_credentials", "Username or password is incorrect");
                    }
                    foreach (var key in state.Sessions.Where(x => x.Value.Expires <= DateTimeOffset.UtcNow).Select(x => x.Key).ToList()) state.Sessions.Remove(key);
                    // Keep a bounded number of devices signed in per account.
                    var sessions = state.Sessions.Where(x => x.Value.User == name).OrderBy(x => x.Value.Expires).ToList();
                    foreach (var old in sessions.Take(Math.Max(0, sessions.Count - 9))) state.Sessions.Remove(old.Key);
                    var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
                    var expires = DateTimeOffset.UtcNow.AddDays(30);
                    state.Sessions[TokenKey(token)] = new Session(name, expires);
                    Save();
                    return new { token, username = name, expires };
                }
                case "me": return new { username = Identity(r) };
                case "logout":
                    Identity(r); state.Sessions.Remove(TokenKey(Field(r, "token"))); Save(); return new { signedOut = true };
                case "available":
                {
                    var domain = Domain(Field(r, "domain", 128));
                    return new { domain, available = !state.Sites.ContainsKey(domain) };
                }
                case "list": return state.Sites.Values.OrderBy(x => x.Domain).Select(x => new { domain = x.Domain, owner = x.Owner, updated = x.Updated }).ToArray();
                case "mine":
                {
                    var user = Identity(r);
                    return state.Sites.Values.Where(x => x.Owner == user).OrderBy(x => x.Domain).Select(x => new { domain = x.Domain, updated = x.Updated }).ToArray();
                }
                case "get":
                {
                    var domain = Domain(Field(r, "domain", 128));
                    if (!state.Sites.TryGetValue(domain, out var site)) throw new ApiError("not_found", "Site not found on this server");
                    return new { domain = site.Domain, owner = site.Owner, html = site.Html, css = site.Css, js = site.Js, updated = site.Updated };
                }
                case "publish":
                {
                    var user = Identity(r);
                    var domain = Domain(Field(r, "domain", 128));
                    var html = Field(r, "html", 524288); var css = Field(r, "css", 524288); var js = Field(r, "js", 524288);
                    if (Encoding.UTF8.GetByteCount(html + css + js) > 524288) throw new ApiError("too_large", "Site exceeds 512 KiB");
                    if (string.IsNullOrWhiteSpace(html)) throw new ApiError("empty_site", "HTML is required");
                    if (state.Sites.TryGetValue(domain, out var old) && old.Owner != user) throw new ApiError("domain_taken", "This domain belongs to another account");
                    if (old == null && state.Sites.Values.Count(x => x.Owner == user) >= 50) throw new ApiError("capacity", "Each account may publish up to 50 sites");
                    state.Sites[domain] = new Site(domain, user, html, css, js, DateTimeOffset.UtcNow);
                    Save(); return new { domain, published = true };
                }
                case "delete":
                {
                    var user = Identity(r); var domain = Domain(Field(r, "domain", 128));
                    if (!state.Sites.TryGetValue(domain, out var site)) throw new ApiError("not_found", "Site not found");
                    if (site.Owner != user) throw new ApiError("forbidden", "Only the owner may delete this site");
                    state.Sites.Remove(domain); Save(); return new { deleted = true };
                }
                default: throw new ApiError("unknown_operation", "Unknown operation");
            }
        }
    }
}
