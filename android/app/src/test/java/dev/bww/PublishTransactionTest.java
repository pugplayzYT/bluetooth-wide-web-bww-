package dev.bww;
import org.junit.Test;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import static org.junit.Assert.*;

public class PublishTransactionTest {
    private static class Peer implements PublishTransaction.Peer {
        PublishTransaction.Snapshot snapshot; int writes; boolean safe = true, loseReply, failBeforeCommit;
        public PublishTransaction.Snapshot read() { return snapshot; }
        public boolean conditional() { return safe; }
        public void write(String baseline) throws Exception {
            ++writes;
            if (failBeforeCommit) { failBeforeCommit = false; throw new IOException("radio interrupted before commit"); }
            snapshot = new PublishTransaction.Snapshot("alice", "desired");
            if (loseReply) { loseReply = false; throw new IOException("commit reply lost"); }
        }
    }
    @Test public void lostCommitReplyDoesNotPublishTwice() throws Exception {
        Peer peer = new Peer(); peer.loseReply = true;
        try { PublishTransaction.attempt(peer, "alice", "missing", "desired", false); fail(); } catch (IOException expected) { }
        PublishTransaction.attempt(peer, "alice", "missing", "desired", true); assertEquals(1, peer.writes);
    }
    @Test public void interruptedStagingRetriesAgainstSameBaseline() throws Exception {
        Peer peer = new Peer(); peer.failBeforeCommit = true; peer.snapshot = new PublishTransaction.Snapshot("alice", "original");
        try { PublishTransaction.attempt(peer, "alice", "original", "desired", false); fail(); } catch (IOException expected) { }
        PublishTransaction.attempt(peer, "alice", "original", "desired", true); assertEquals(2, peer.writes);
    }
    @Test public void externalEditStopsRetry() throws Exception {
        Peer peer = new Peer(); peer.snapshot = new PublishTransaction.Snapshot("alice", "someone-elses-edit");
        try { PublishTransaction.attempt(peer, "alice", "original", "desired", true); fail(); } catch (PublishTransaction.ReviewRequired expected) { }
        assertEquals(0, peer.writes);
    }
    @Test public void anotherOwnersIdenticalContentIsNotSuccess() throws Exception {
        Peer peer = new Peer(); peer.snapshot = new PublishTransaction.Snapshot("bob", "desired");
        try { PublishTransaction.attempt(peer, "alice", "missing", "desired", true); fail(); } catch (PublishTransaction.ReviewRequired expected) { }
        assertEquals(0, peer.writes);
    }
    @Test public void legacyHostPausesAfterAmbiguousDisconnect() throws Exception {
        Peer peer = new Peer(); peer.safe = false;
        try { PublishTransaction.attempt(peer, "alice", "missing", "desired", true); fail(); } catch (PublishTransaction.ReviewRequired expected) { }
        assertEquals(0, peer.writes);
    }
    @Test public void legacyFirstPublishStillWorks() throws Exception {
        Peer peer = new Peer(); peer.safe = false; PublishTransaction.attempt(peer, "alice", "missing", "desired", false); assertEquals(1, peer.writes);
    }
    @Test public void fingerprintMatchesWireSpecificationAtUnicodeBoundary() throws Exception {
        String html = "a".repeat(8191) + "💚b";
        MessageDigest sha = MessageDigest.getInstance("SHA-256"); byte[] first = sha.digest("a".repeat(8191).getBytes(StandardCharsets.UTF_8)), last = sha.digest("💚b".getBytes(StandardCharsets.UTF_8));
        String manifest = "html:8191:" + SiteChunks.hex(first,0,32) + ",5:" + SiteChunks.hex(last,0,32) + ",;css:;js:;";
        byte[] expected = sha.digest(manifest.getBytes(StandardCharsets.US_ASCII));
        assertEquals(SiteChunks.hex(expected,0,32), SiteFingerprint.of(html,"",""));
    }
}
