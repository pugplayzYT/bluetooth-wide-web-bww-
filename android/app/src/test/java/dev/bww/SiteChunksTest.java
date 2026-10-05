package dev.bww;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.junit.Test;
import static org.junit.Assert.*;
public class SiteChunksTest {
    @Test public void roundTripsFull512KiBSiteWithUnicodeAtChunkBoundaries() throws Exception {
        StringBuilder text = new StringBuilder();
        for (int i=0; i<524288/8; ++i) text.append("abcd💚");
        byte[] bytes=text.toString().getBytes(StandardCharsets.UTF_8); assertEquals(524288,bytes.length);
        ByteArrayOutputStream assembled=new ByteArrayOutputStream(); int chunks=0;
        for (int start=0; start<bytes.length;) {
            int end=SiteChunks.end(bytes,start,8192); byte[] decoded=SiteChunks.unhex(SiteChunks.hex(bytes,start,end));
            assertTrue(decoded.length<=8192); SiteChunks.utf8(decoded); assembled.write(decoded); start=end; ++chunks;
        }
        assertEquals(64,chunks); assertEquals(text.toString(),SiteChunks.utf8(assembled.toByteArray()));
    }
    @Test public void backsOffBeforeASplitEmoji() throws Exception {
        byte[] bytes="abcdefg💚hello".getBytes(StandardCharsets.UTF_8);
        int end=SiteChunks.end(bytes,0,8); assertEquals(7,end); assertEquals("abcdefg",SiteChunks.utf8(SiteChunks.unhex(SiteChunks.hex(bytes,0,end))));
    }
    @Test public void rejectsMalformedOrOversizedHex() {
        for (String text:new String[]{"a","zz","00".repeat(8193)}) {
            try { SiteChunks.unhex(text); fail(); } catch (IOException expected) { }
        }
    }
    @Test public void rejectsMalformedUtf8() {
        try { SiteChunks.utf8(new byte[]{(byte)0xc0,(byte)0xaf}); fail(); } catch (IOException expected) { }
    }
}
