package dev.bww;

import java.net.URI;
import org.junit.Test;
import static org.junit.Assert.*;

public class SiteOriginTest {
    private static final String COMPUTER = "AA:BB:CC:DD:EE:01";
    @Test public void originIsStableAcrossReconnectionAndAppRecreation() {
        assertEquals(SiteOrigin.pageUrl(COMPUTER, "garden"), SiteOrigin.pageUrl(COMPUTER.toLowerCase(), "GARDEN.bww"));
        String origin = SiteOrigin.pageUrl(COMPUTER, "garden");
        assertEquals(origin, SiteOrigin.pageUrl(new String(COMPUTER), "garden"));
    }
    @Test public void sameDomainOnDifferentComputersHasDifferentStorage() {
        assertNotEquals(SiteOrigin.host(COMPUTER, "garden"), SiteOrigin.host("AA:BB:CC:DD:EE:02", "garden"));
    }
    @Test public void differentSitesHaveDifferentStorage() {
        assertNotEquals(SiteOrigin.host(COMPUTER, "garden"), SiteOrigin.host(COMPUTER, "game"));
    }
    @Test public void scopedOriginKeepsLongDomainsAndServerIdentityValid() {
        String host = SiteOrigin.host(COMPUTER, "a".repeat(63));
        for (String label : host.split("\\.")) assertTrue(label.length() <= 63);
        assertEquals(host, URI.create("https://" + host).getHost());
        assertFalse(host.contains(COMPUTER));
    }
    @Test public void resourcesCannotReadOtherComputersOrLogicalOrigins() {
        assertEquals("garden.bww", SiteOrigin.resourceDomain(COMPUTER, SiteOrigin.host(COMPUTER, "garden")));
        assertNull(SiteOrigin.resourceDomain("AA:BB:CC:DD:EE:02", SiteOrigin.host(COMPUTER, "garden")));
        assertNull(SiteOrigin.resourceDomain(COMPUTER, "garden.bww"));
        assertNull(SiteOrigin.resourceDomain("", SiteOrigin.host(COMPUTER, "garden")));
    }
    @Test public void publicAndScopedLinksResolveToTheLogicalSite() {
        assertEquals("game.bww", SiteOrigin.navigationDomain(COMPUTER, "bww://game.bww"));
        assertEquals("game.bww", SiteOrigin.navigationDomain(COMPUTER, "https://game.bww/index.html"));
        assertEquals("game.bww", SiteOrigin.navigationDomain(COMPUTER, SiteOrigin.pageUrl(COMPUTER, "game") + "#score"));
        assertEquals("game.bww", SiteOrigin.navigationDomain(COMPUTER, "https://" + SiteOrigin.host(COMPUTER, "game")));
    }
    @Test public void rejectsOtherServersAndInvalidInternalNavigation() {
        for (String url : new String[]{SiteOrigin.pageUrl("another computer", "game"), SiteOrigin.pageUrl(COMPUTER, "game").replace("index.html", "admin"), SiteOrigin.pageUrl(COMPUTER, "game").replace("https:", "http:"), SiteOrigin.pageUrl(COMPUTER, "game").replace("/index.html", ":8080/index.html")}) {
            try { SiteOrigin.navigationDomain(COMPUTER, url); fail("Accepted " + url); }
            catch (IllegalArgumentException expected) { }
        }
    }
}
