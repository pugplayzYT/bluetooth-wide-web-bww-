package dev.bww;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;

/** Persistent WebView origins partition browser data by computer and site. */
final class SiteOrigin {
    private static String suffix(String server) {
        if (server == null || server.trim().isEmpty()) throw new IllegalArgumentException("Connect to a server first");
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(server.trim().toLowerCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8));
            StringBuilder key = new StringBuilder();
            for (int i = 0; i < 16; i++) key.append(String.format(Locale.ROOT, "%02x", digest[i] & 0xff));
            return ".s-" + key + ".bww";
        } catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    static String host(String server, String site) {
        String domain = SiteContent.domain(site);
        return domain.substring(0, domain.length() - 4) + suffix(server);
    }
    static String pageUrl(String server, String site) { return "https://" + host(server, site) + "/index.html"; }
    static String resourceDomain(String server, String host) {
        if (server == null || server.isEmpty() || host == null) return null;
        String normalized = host.toLowerCase(Locale.ROOT), ending = suffix(server);
        if (!normalized.endsWith(ending)) return null;
        try { return SiteContent.domain(normalized.substring(0, normalized.length() - ending.length())); }
        catch (IllegalArgumentException e) { return null; }
    }
    static String navigationDomain(String server, String value) {
        // Accept logical BWW links as well as relative links resolved against this server's origin.
        URI uri = URI.create(value.trim());
        String internal = resourceDomain(server, uri.getHost());
        if (internal == null) return SiteContent.domain(value);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getRawUserInfo() != null || uri.getPort() != -1)
            throw new IllegalArgumentException("Invalid BWW address");
        String path = uri.getPath();
        if (path != null && !path.isEmpty() && !SiteContent.pagePath(path)) throw new IllegalArgumentException("Sites have one page: index.html");
        return internal;
    }
}
