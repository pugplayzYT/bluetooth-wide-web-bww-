using System.Security.Cryptography;
using System.Text;
namespace Bww;

public static class SiteFingerprint
{
    public static IEnumerable<byte[]> Chunks(string text, int limit = 8192)
    {
        var bytes = Encoding.UTF8.GetBytes(text);
        for (int start = 0; start < bytes.Length;)
        {
            int end = Math.Min(start + limit, bytes.Length);
            while (end < bytes.Length && (bytes[end] & 0xc0) == 0x80) --end;
            if (end == start) throw new IOException("Invalid chunk size");
            yield return bytes[start..end]; start = end;
        }
    }
    public static string Of(string html, string css, string js)
    {
        var manifest = new StringBuilder();
        foreach (var asset in new[] { ("html", html), ("css", css), ("js", js) })
        {
            manifest.Append(asset.Item1).Append(':');
            foreach (var chunk in Chunks(asset.Item2))
                manifest.Append(chunk.Length).Append(':').Append(Convert.ToHexString(SHA256.HashData(chunk)).ToLowerInvariant()).Append(',');
            manifest.Append(';');
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.ASCII.GetBytes(manifest.ToString()))).ToLowerInvariant();
    }
}
