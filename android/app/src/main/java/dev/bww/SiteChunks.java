package dev.bww;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
/** Bounded UTF-8 chunks for hosts which store whole sites on SD. */
final class SiteChunks {
    static final int MAX_CHUNK_BYTES = 8192;
    static int end(byte[] bytes, int start, int limit) {
        if (limit < 4 || limit > MAX_CHUNK_BYTES || start < 0 || start >= bytes.length) throw new IllegalArgumentException("Invalid chunk boundary");
        int end = Math.min(bytes.length, start + limit);
        if (end < bytes.length) while (end > start && (bytes[end] & 0xc0) == 0x80) --end;
        if (end == start) throw new IllegalArgumentException("Invalid UTF-8 chunk");
        return end;
    }
    static String hex(byte[] bytes, int start, int end) {
        char[] out = new char[(end - start) * 2]; String digits = "0123456789abcdef";
        for (int i = start; i < end; ++i) { int b = bytes[i] & 255; out[(i-start)*2] = digits.charAt(b >> 4); out[(i-start)*2+1] = digits.charAt(b & 15); }
        return new String(out);
    }
    static byte[] unhex(String encoded) throws IOException {
        if ((encoded.length() & 1) != 0 || encoded.length() > MAX_CHUNK_BYTES * 2) throw new IOException("Invalid site chunk size");
        byte[] out = new byte[encoded.length()/2];
        for (int i = 0; i < out.length; ++i) {
            int high = Character.digit(encoded.charAt(i*2),16), low = Character.digit(encoded.charAt(i*2+1),16);
            if (high < 0 || low < 0) throw new IOException("Invalid site chunk encoding");
            out[i] = (byte)((high << 4) | low);
        }
        return out;
    }
    static String utf8(byte[] bytes) throws IOException {
        try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch (CharacterCodingException e) { throw new IOException("Invalid UTF-8 site content", e); }
    }
}
