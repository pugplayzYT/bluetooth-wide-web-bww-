package dev.bww;

import java.net.URI;
import java.util.Locale;

/** Pure rendering/routing rules shared by the URL bar and WebView resource adapter. */
final class SiteContent {
    static final String CSP = "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
    static String domain(String value) {
        String s = value.trim().toLowerCase(Locale.ROOT);
        if (s.contains("://")) {
            URI uri;
            try { uri = URI.create(s); } catch (IllegalArgumentException e) { throw new IllegalArgumentException("Enter a BWW domain"); }
            if (!"bww".equals(uri.getScheme()) && !"https".equals(uri.getScheme()))
                throw new IllegalArgumentException("Use bww:// followed by a site domain");
            if (uri.getRawUserInfo() != null || uri.getPort() != -1)
                throw new IllegalArgumentException("BWW addresses do not use credentials or ports");
            String path = uri.getPath();
            if (path != null && !path.isEmpty() && !"/".equals(path) && !"/index.html".equals(path))
                throw new IllegalArgumentException("Sites have one page: index.html");
            s = uri.getHost();
        }
        if (s == null) throw new IllegalArgumentException("Enter a BWW domain");
        if (s.endsWith("/")) s = s.substring(0,s.length()-1);
        if (s.endsWith(".bww")) s = s.substring(0,s.length()-4);
        if (!s.matches("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"))
            throw new IllegalArgumentException("Use a domain such as my-site.bww");
        return s + ".bww";
    }
    static String html(String html) {
        // Fetch the separate assets under the current origin. Never interpolate CSS/JS into markup.
        String assets = "<meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/style.css'><script defer src='/script.js'></script>";
        int head = html.toLowerCase(Locale.ROOT).indexOf("</head>");
        return head >= 0 ? html.substring(0,head) + assets + html.substring(head) : assets + html;
    }
    static boolean pagePath(String path) { return "/".equals(path) || "/index.html".equals(path); }
}
