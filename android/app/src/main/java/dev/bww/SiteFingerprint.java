package dev.bww;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class SiteFingerprint {
    static String of(String html, String css, String js) throws Exception {
        MessageDigest sha = MessageDigest.getInstance("SHA-256"); StringBuilder manifest = new StringBuilder();
        String[] names = {"html", "css", "js"}, values = {html, css, js};
        for (int asset = 0; asset < 3; ++asset) {
            manifest.append(names[asset]).append(':'); byte[] bytes = values[asset].getBytes(StandardCharsets.UTF_8);
            for (int start = 0; start < bytes.length;) {
                int end = SiteChunks.end(bytes, start, 8192); sha.update(bytes, start, end - start);
                byte[] digest = sha.digest(); manifest.append(end - start).append(':').append(SiteChunks.hex(digest, 0, digest.length)).append(','); start = end;
            }
            manifest.append(';');
        }
        byte[] digest = sha.digest(manifest.toString().getBytes(StandardCharsets.US_ASCII)); return SiteChunks.hex(digest, 0, digest.length);
    }
}
