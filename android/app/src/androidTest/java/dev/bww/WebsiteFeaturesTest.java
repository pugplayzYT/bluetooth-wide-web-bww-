package dev.bww;

import android.os.SystemClock;
import android.view.View;
import android.view.MotionEvent;
import android.webkit.WebView;
import android.widget.FrameLayout;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Runs on an Android device/emulator with its real WebView, without Bluetooth fixtures. */
@RunWith(AndroidJUnit4.class)
public class WebsiteFeaturesTest {
    private static final String COMPUTER = "instrumentation-computer-one";
    private static final String SCORE_KEY = "bww-instrumentation-score";

    private void loadSite(ActivityScenario<MainActivity> scenario, String server, String domain) throws Exception {
        AtomicReference<Exception> failure = new AtomicReference<>();
        scenario.onActivity(activity -> {
            try {
                Field serverField = MainActivity.class.getDeclaredField("server"); serverField.setAccessible(true); serverField.set(activity, server);
                Field pageField = MainActivity.class.getDeclaredField("pages"); pageField.setAccessible(true);
                @SuppressWarnings("unchecked") Map<String, JSONObject> pages = (Map<String, JSONObject>)pageField.get(activity);
                pages.clear(); pages.put(domain + ".bww", new JSONObject().put("html", "<!doctype html><html><head></head><body><h1 id='ready'>Score game</h1></body></html>").put("css", "body { background: #f4f7f5; }").put("js", ""));
                WebView web = activity.findViewById(R.id.site_webview);
                web.loadUrl(SiteOrigin.pageUrl(server, domain));
            } catch (Exception e) { failure.set(e); }
        });
        if (failure.get() != null) throw failure.get();
        for (int attempt = 0; attempt < 100; attempt++) {
            if ("true".equals(js(scenario, "location.href === " + JSONObject.quote(SiteOrigin.pageUrl(server, domain)) + " && document.readyState === 'complete' && !!document.getElementById('ready')"))) return;
            SystemClock.sleep(100);
        }
        fail("Website did not load through the app's real resource interceptor");
    }
    private String js(ActivityScenario<MainActivity> scenario, String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1); AtomicReference<String> result = new AtomicReference<>();
        scenario.onActivity(activity -> {
            WebView web = activity.findViewById(R.id.site_webview);
            web.evaluateJavascript(script, value -> { result.set(value); done.countDown(); });
        });
        assertTrue("WebView JavaScript timed out", done.await(10, TimeUnit.SECONDS));
        return result.get();
    }
    @Test public void scoresSurviveActivityRecreationAndComputerSwitching() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            loadSite(scenario, COMPUTER, "score");
            assertEquals("\"42\"", js(scenario, "localStorage.setItem('" + SCORE_KEY + "','42'); localStorage.getItem('" + SCORE_KEY + "')"));
            scenario.recreate(); loadSite(scenario, COMPUTER, "score");
            assertEquals("\"42\"", js(scenario, "localStorage.getItem('" + SCORE_KEY + "')"));
            loadSite(scenario, "instrumentation-computer-two", "score");
            js(scenario, "localStorage.removeItem('" + SCORE_KEY + "')");
            assertEquals("null", js(scenario, "localStorage.getItem('" + SCORE_KEY + "')"));
            js(scenario, "localStorage.setItem('" + SCORE_KEY + "','99')");
            loadSite(scenario, COMPUTER, "score");
            assertEquals("\"42\"", js(scenario, "localStorage.getItem('" + SCORE_KEY + "')"));
            loadSite(scenario, COMPUTER, "other-game");
            js(scenario, "localStorage.removeItem('" + SCORE_KEY + "')");
            assertEquals("null", js(scenario, "localStorage.getItem('" + SCORE_KEY + "')"));
        }
    }
    private void doubleTap(MainActivity activity) {
        long start = SystemClock.uptimeMillis();
        for (int tap = 0; tap < 2; ++tap) {
            for (int action : new int[]{MotionEvent.ACTION_DOWN, MotionEvent.ACTION_UP}) {
                MotionEvent event = MotionEvent.obtain(start + tap * 100, start + tap * 100 + (action == MotionEvent.ACTION_UP ? 40 : 0), action, 100, 100, 0);
                activity.dispatchTouchEvent(event); event.recycle();
            }
            if (tap == 0) assertEquals(View.GONE, activity.findViewById(R.id.browser_controls).getVisibility());
        }
    }
    @Test public void fullscreenKeepsThePageAndExitsWithDoubleTapOrBack() throws Exception {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            loadSite(scenario, COMPUTER, "fullscreen");
            js(scenario, "window.testMarker = 'still-playing'; localStorage.setItem('" + SCORE_KEY + "','7')");
            AtomicReference<WebView> original = new AtomicReference<>();
            scenario.onActivity(activity -> {
                original.set(activity.findViewById(R.id.site_webview));
                activity.findViewById(R.id.full_screen).performClick();
                assertEquals(View.GONE, activity.findViewById(R.id.browser_controls).getVisibility());
                doubleTap(activity);
                assertEquals(View.VISIBLE, activity.findViewById(R.id.browser_controls).getVisibility());
                assertSame(original.get(), activity.findViewById(R.id.site_webview));
                activity.findViewById(R.id.full_screen).performClick();
                activity.onBackPressed();
                assertEquals(View.VISIBLE, activity.findViewById(R.id.browser_controls).getVisibility());
            });
            assertEquals("\"still-playing\"", js(scenario, "window.testMarker"));
            assertEquals("\"7\"", js(scenario, "localStorage.getItem('" + SCORE_KEY + "')"));
        }
    }
    @Test public void htmlCustomFullscreenRestoresBrowserAndNotifiesThePage() {
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                WebView web = activity.findViewById(R.id.site_webview); AtomicInteger hidden = new AtomicInteger();
                web.getWebChromeClient().onShowCustomView(new FrameLayout(activity), hidden::incrementAndGet);
                assertEquals(View.GONE, web.getVisibility());
                doubleTap(activity);
                assertEquals(View.VISIBLE, web.getVisibility());
                assertEquals(View.VISIBLE, activity.findViewById(R.id.browser_controls).getVisibility());
                assertEquals(1, hidden.get());
            });
        }
    }
}
