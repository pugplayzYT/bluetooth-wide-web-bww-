package dev.bww;

import org.junit.Test;
import static org.junit.Assert.*;

public class SiteContentTest {
    @Test public void addressNormalizationMatchesServerNamespace() {
        assertEquals("garden.bww", SiteContent.domain(" Garden "));
        assertEquals("garden.bww", SiteContent.domain("bww://GARDEN.bww"));
        assertEquals("garden.bww", SiteContent.domain("https://garden.bww/index.html"));
        assertEquals("a-b.bww", SiteContent.domain("a-b.bww/"));
    }
    @Test public void rejectsNonBwwSchemesCredentialsPortsAndPaths() {
        for (String address : new String[]{"file:///secret", "javascript://garden.bww", "https://user:pass@garden.bww", "bww://garden.bww:8080", "bww://garden.bww/admin", "../secret", "-garden", "garden-", "a.b", "💥", "a".repeat(64)}) {
            try { SiteContent.domain(address); fail("Accepted " + address); }
            catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void injectsSeparateAssetsInsideCaseInsensitiveHead() {
        String rendered = SiteContent.html("<!doctype html><HTML><HEAD><title>Site</title></HEAD><BODY>Hello</BODY></HTML>");
        assertTrue(rendered.indexOf("href='/style.css'") < rendered.indexOf("</HEAD>"));
        assertTrue(rendered.contains("defer src='/script.js'"));
        assertTrue(rendered.contains("<BODY>Hello</BODY>"));
    }
    @Test public void supportsHtmlFragmentsWithoutChangingTheirMarkup() {
        String fragment = "<h1>Hello</h1><button onclick=\"this.textContent='Works'\">Try</button>";
        assertTrue(SiteContent.html(fragment).endsWith(fragment));
        assertTrue(SiteContent.html(fragment).contains("name='viewport'"));
    }
    @Test public void navigationOnlyTreatsKnownHtmlPathsAsPages() {
        assertTrue(SiteContent.pagePath("/")); assertTrue(SiteContent.pagePath("/index.html"));
        for (String path : new String[]{"/style.css", "/script.js", "/secret", "/../index.html", "/index.html/"}) assertFalse(SiteContent.pagePath(path));
        assertTrue(SiteContent.CSP.contains("connect-src 'none'"));
        assertTrue(SiteContent.CSP.contains("frame-src 'none'"));
        assertTrue(SiteContent.CSP.contains("base-uri 'none'"));
    }
}
