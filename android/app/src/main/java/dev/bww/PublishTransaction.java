package dev.bww;
import java.io.IOException;

/** A reconnect must distinguish a lost commit reply from an uncommitted upload. */
final class PublishTransaction {
    static final class Snapshot {
        final String owner, fingerprint;
        Snapshot(String owner, String fingerprint) { this.owner = owner; this.fingerprint = fingerprint; }
    }
    interface Peer {
        Snapshot read() throws Exception;
        boolean conditional();
        void write(String expectedFingerprint) throws Exception;
    }
    static final class ReviewRequired extends IOException { ReviewRequired(String message) { super(message); } }
    static void attempt(Peer peer, String owner, String baseline, String desired, boolean interrupted) throws Exception {
        Snapshot current = peer.read();
        if (current != null && !owner.equals(current.owner)) throw new ReviewRequired("This domain belongs to another account. Your draft is saved.");
        String fingerprint = current == null ? "missing" : current.fingerprint;
        if (desired.equals(fingerprint)) return; // Commit succeeded but its reply was lost.
        if (!baseline.equals(fingerprint)) throw new ReviewRequired("The published site changed. Open it again and review your saved draft before publishing.");
        if (!peer.conditional() && interrupted) throw new ReviewRequired("This host cannot safely retry an interrupted publish. Your draft is saved; reconnect and review it.");
        peer.write(baseline);
    }
}
