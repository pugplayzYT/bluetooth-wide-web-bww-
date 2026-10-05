package dev.bww;

import android.Manifest;
import android.app.*;
import android.bluetooth.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.text.*;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class MainActivity extends Activity {
    private final BwwConnection connection = new BwwConnection();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Map<String, JSONObject> pages = new ConcurrentHashMap<>();
    private SharedPreferences prefs;
    private String server = "", serverName = "", token = "", username = "";
    private TextView status, account;
    private EditText address;
    private WebView web;
    private LinearLayout root, chrome;
    private FrameLayout website;
    private GestureDetector fullScreenGesture;
    private Toast fullScreenHint;
    private boolean consumeExitTouch;
    private float touchDownX, touchDownY;
    private boolean trackingTopGesture;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private boolean fullScreen, customWasFullScreen;
    private int topInset, bottomInset;
    private boolean busy;
    private ProgressBar operationProgress, publishProgress;
    private TextView publishMessage;
    private AlertDialog publishingDialog;
    private String publishJobId;
    private Runnable restorePublishControls;
    private final BroadcastReceiver uploadReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { refreshUpload(); }
    };

    interface Job { void run() throws Exception; }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        fullScreenGesture = new GestureDetector(this, new GestureDetector.SimpleOnGestureListener() {
            @Override public boolean onDown(MotionEvent event) { return true; }
            @Override public boolean onDoubleTap(MotionEvent event) {
                int topBoundary = Math.max(dp(48), topInset);
                if (event.getY() <= topBoundary) {
                    consumeExitTouch = true; exitFullScreen(); return true;
                }
                return false;
            }
        });
        prefs = getSharedPreferences("bww", MODE_PRIVATE);
        connection.progress = message -> ui(() -> status.setText(message));
        androidx.core.content.ContextCompat.registerReceiver(this, uploadReceiver,
            new IntentFilter(PublishService.CHANGED), androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(10), dp(16), 0); root.setBackgroundColor(Color.rgb(244,247,245));
        chrome = new LinearLayout(this); chrome.setOrientation(LinearLayout.VERTICAL);
        chrome.setId(R.id.browser_controls); root.addView(chrome);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            topInset = insets.getSystemWindowInsetTop(); bottomInset = insets.getSystemWindowInsetBottom();
            updateBrowserPadding();
            return insets;
        });
        TextView title = text("Bluetooth-wide Web", 24); title.setTypeface(null, android.graphics.Typeface.BOLD); chrome.addView(title);
        chrome.addView(text("A little web, right around you.", 14));
        status = text("Pair your computer in Bluetooth settings, then connect.", 13); chrome.addView(status);
        operationProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        operationProgress.setIndeterminate(true); operationProgress.setVisibility(View.GONE); chrome.addView(operationProgress);
        LinearLayout toolbar = row();
        toolbar.addView(button("Connect", v -> chooseServer()));
        toolbar.addView(button("Sites", v -> listSites(false)));
        toolbar.addView(button("Account", v -> accountDialog())); chrome.addView(toolbar);
        toolbar.addView(button("Uploads", v -> uploadsDialog()));
        account = text("Browsing as a guest", 13); chrome.addView(account);
        LinearLayout url = row(); address = new EditText(this); address.setSingleLine(true);
        address.setHint("bww://my-site.bww"); address.setInputType(17);
        url.addView(address, new LinearLayout.LayoutParams(0, -2, 1));
        url.addView(button("Go", v -> browse(address.getText().toString()))); chrome.addView(url);
        address.setOnEditorActionListener((v, action, event) -> { browse(address.getText().toString()); return true; });
        LinearLayout author = row(); author.addView(button("Create Site", v -> editor(null)));
        author.addView(button("My Sites", v -> listSites(true)));
        Button expand = button(getString(R.string.full_screen), v -> setFullScreen(true));
        expand.setId(R.id.full_screen); author.addView(expand); chrome.addView(author);
        web = new WebView(this); web.setId(R.id.site_webview);
        WebSettings settings = web.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (request.isForMainFrame() && ("https".equals(uri.getScheme()) || "bww".equals(uri.getScheme())) && uri.getHost() != null && uri.getHost().endsWith(".bww")) {
                    if (uri.getPath() != null && !uri.getPath().isEmpty() && !SiteContent.pagePath(uri.getPath())) { notice("Only index.html, style.css, and script.js are supported"); return true; }
                    // Let in-page anchors keep the current document and JavaScript state.
                    Uri current = web.getUrl() == null ? null : Uri.parse(web.getUrl());
                    if (uri.getFragment() != null && current != null && "https".equals(uri.getScheme()) && uri.getUserInfo() == null && uri.getPort() == current.getPort() && uri.getHost().equals(current.getHost()) && Objects.equals(uri.getPath(), current.getPath())) return false;
                    browse(uri.toString());
                } else if (request.isForMainFrame()) notice("Only Bluetooth-wide Web sites can open here");
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return resource(request.getUrl());
            }
            @Override public void onReceivedSslError(WebView view, android.webkit.SslErrorHandler handler, android.net.http.SslError error) { handler.cancel(); }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onShowCustomView(View view, CustomViewCallback callback) {
                if (customView != null) { callback.onCustomViewHidden(); return; }
                customWasFullScreen = fullScreen; customView = view; customViewCallback = callback;
                website.addView(view, new FrameLayout.LayoutParams(-1, -1)); web.setVisibility(View.GONE);
                setFullScreen(true);
            }
            @Override public void onHideCustomView() { hideCustomView(); }
        });
        website = new FrameLayout(this); website.addView(web, new FrameLayout.LayoutParams(-1, -1));
        root.addView(website, new LinearLayout.LayoutParams(-1, 0, 1));
        FrameLayout screen = new FrameLayout(this); screen.addView(root, new FrameLayout.LayoutParams(-1, -1));
        setContentView(screen);
        if (Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        web.loadDataWithBaseURL("https://welcome.bww/", "<html><meta name='viewport' content='width=device-width'><body style='font-family:sans-serif;padding:24px;color:#173e35'><h1>Welcome to your nearby web.</h1><p>1. Start BWW on your Windows computer.</p><p>2. Pair your phone with the computer.</p><p>3. Tap Connect and choose it.</p><p>Browse sites, or sign in to publish your own HTML, CSS, and JavaScript.</p></body></html>", "text/html", "UTF-8", null);
        try { if (!PublishQueue.pending(this).isEmpty() && (Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED)) PublishService.start(this); }
        catch (Exception e) { notice("Could not resume uploads: " + e.getMessage()); }
    }
    private int dp(int n) { return (int)(getResources().getDisplayMetrics().density * n); }
    private TextView text(String value, int size) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(Color.rgb(23,62,53)); t.setPadding(0, dp(4), 0, dp(4)); return t; }
    private LinearLayout row() { LinearLayout r = new LinearLayout(this); r.setOrientation(LinearLayout.HORIZONTAL); return r; }
    private Button button(String value, View.OnClickListener action) { Button b = new Button(this); b.setText(value); b.setTextSize(12); b.setOnClickListener(action); return b; }
    private void notice(String value) { runOnUiThread(() -> Toast.makeText(this, value, Toast.LENGTH_LONG).show()); }
    private void ui(Runnable action) { runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) action.run(); }); }
    private void task(String label, Job job) {
        task(label, job, () -> {});
    }
    private void task(String label, Job job, Runnable finished) {
        if (busy) { notice("Please wait for the current operation"); return; }
        busy = true; status.setText(getString(R.string.progress, label)); operationProgress.setVisibility(View.VISIBLE);
        worker.execute(() -> {
            try { job.run(); ui(() -> status.setText(connection.connected() ? "Connected · " + server : "Disconnected · tap Connect")); }
            catch (Exception e) {
                if (e instanceof BwwConnection.ApiException && "unauthorized".equals(((BwwConnection.ApiException)e).code)) {
                    token = ""; username = ""; prefs.edit().remove("token:" + server).remove("user:" + server).apply(); ui(this::updateAccount);
                }
                ui(() -> { status.setText(connection.connected() ? "Connected · " + server : "Disconnected · tap Connect"); notice(e.getMessage() == null ? "Operation failed" : e.getMessage()); });
            } finally { ui(() -> { busy = false; operationProgress.setVisibility(View.GONE); finished.run(); }); }
        });
    }
    private JSONObject request(String op) throws JSONException { return new JSONObject().put("op", op); }
    private JSONObject authenticated(String op) throws JSONException {
        if (token.isEmpty()) throw new JSONException("Sign in to publish and manage sites");
        return request(op).put("token", token);
    }
    private void updateAccount() { account.setText(username.isEmpty() ? "Browsing as a guest" : "Signed in as " + username); }
    private void chooseServer() {
        if (Build.VERSION.SDK_INT >= 31 && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT}, 1); return;
        }
        BluetoothManager manager = (BluetoothManager)getSystemService(BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null) { notice("This device has no Bluetooth adapter"); return; }
        if (!adapter.isEnabled()) { startActivity(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)); return; }
        List<BluetoothDevice> devices = new ArrayList<>(adapter.getBondedDevices());
        if (devices.isEmpty()) {
            new AlertDialog.Builder(this).setTitle("Pair your computer first").setMessage("Open Android Bluetooth settings and pair with the computer running BWW.")
                .setPositiveButton("Settings", (d,w) -> startActivity(new Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS))).setNegativeButton("Cancel", null).show(); return;
        }
        String[] labels = devices.stream().map(d -> (d.getName() == null ? "Bluetooth device" : d.getName()) + "\n" + d.getAddress()).toArray(String[]::new);
        new AlertDialog.Builder(this).setTitle("Choose a paired BWW computer").setItems(labels, (d,i) -> {
            BluetoothDevice device = devices.get(i);
            task("Connecting", () -> {
                connection.disconnect(); connection.connect(device);
                server = device.getAddress(); serverName = device.getName(); pages.clear();
                token = prefs.getString("token:" + server, ""); username = prefs.getString("user:" + server, "");
                if (!token.isEmpty()) {
                    try { username = connection.request(authenticated("me")).getString("username"); }
                    catch (BwwConnection.ApiException e) {
                        if (!"unauthorized".equals(e.code)) throw e;
                        token = ""; username = ""; prefs.edit().remove("token:" + server).remove("user:" + server).apply();
                    }
                }
                ui(() -> {
                    exitFullScreen();
                    updateAccount(); web.loadUrl("about:blank"); web.clearHistory();
                    notice("Connected. Tap Sites to explore.");
                });
            });
        }).setNegativeButton("Cancel", null).show();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(code, permissions, grants);
        if (code == 2) return; // Uploads also run when notification permission is declined.
        if (code == 1 && grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) chooseServer();
        else notice("Bluetooth permission is needed to connect");
    }
    private void accountDialog() {
        if (!connection.connected()) { notice("Connect to a server first"); return; }
        if (!token.isEmpty()) {
            new AlertDialog.Builder(this).setTitle("Signed in as " + username).setMessage("Your session is saved on this server until it expires or you sign out.")
                .setPositiveButton("Sign out", (d,w) -> task("Signing out", () -> {
                    connection.request(authenticated("logout")); token = ""; username = "";
                    prefs.edit().remove("token:" + server).remove("user:" + server).apply(); ui(this::updateAccount);
                })).setNegativeButton("Close", null).show(); return;
        }
        LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(dp(20), dp(8), dp(20), 0);
        EditText user = new EditText(this); user.setHint("Username (3–32 letters/numbers/_)"); user.setSingleLine(true); user.setInputType(1 | 524288);
        EditText password = new EditText(this); password.setHint("Password (at least 10 characters)"); password.setInputType(129);
        form.addView(user); form.addView(password);
        LinearLayout loading = row(); loading.setGravity(Gravity.CENTER_VERTICAL);
        loading.setVisibility(View.GONE);
        ProgressBar spinner = new ProgressBar(this); spinner.setIndeterminate(true);
        spinner.setId(R.id.authentication_progress);
        loading.addView(spinner, new LinearLayout.LayoutParams(dp(36), dp(36)));
        TextView explanation = text("", 14); explanation.setPadding(dp(12), dp(8), 0, dp(8));
        explanation.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        loading.addView(explanation, new LinearLayout.LayoutParams(0, -2, 1)); form.addView(loading);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Your account on this server").setView(form)
            .setPositiveButton("Sign in", null).setNeutralButton("Register", null).setNegativeButton("Cancel", null).create();
        dialog.setOnShowListener(d -> {
            View.OnClickListener login = v -> {
                if (busy) { notice("Please wait for the current operation"); return; }
                String name = user.getText().toString(), pass = password.getText().toString();
                String op = v == dialog.getButton(AlertDialog.BUTTON_NEUTRAL) ? "register" : "login";
                String label = getString("register".equals(op) ? R.string.creating_account : R.string.signing_in);
                boolean esp32 = serverName != null && serverName.startsWith("BWW-ESP32");
                explanation.setText(getString(R.string.authentication_progress, label, getString(esp32 ? R.string.esp32_auth_wait : R.string.auth_wait)));
                spinner.setContentDescription(label); loading.setVisibility(View.VISIBLE);
                android.view.inputmethod.InputMethodManager keyboard = (android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
                if (keyboard != null) keyboard.hideSoftInputFromWindow(password.getWindowToken(), 0);
                user.setEnabled(false); password.setEnabled(false);
                for (int which : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEUTRAL, AlertDialog.BUTTON_NEGATIVE}) dialog.getButton(which).setEnabled(false);
                dialog.setCancelable(false); dialog.setCanceledOnTouchOutside(false);
                task(label, () -> {
                    JSONObject result = connection.request(request(op).put("username", name).put("password", pass));
                    token = result.getString("token"); username = result.getString("username");
                    prefs.edit().putString("token:" + server, token).putString("user:" + server, username).apply();
                    ui(() -> { password.setText(""); dialog.dismiss(); updateAccount(); });
                }, () -> {
                    loading.setVisibility(View.GONE); user.setEnabled(true); password.setEnabled(true);
                    for (int which : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEUTRAL, AlertDialog.BUTTON_NEGATIVE}) dialog.getButton(which).setEnabled(true);
                    dialog.setCancelable(true); dialog.setCanceledOnTouchOutside(true);
                });
            };
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(login);
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(login);
        }); dialog.show();
    }
    private void browse(String value) {
        final String name;
        try { name = SiteOrigin.navigationDomain(server, value); } catch (Exception e) { notice(e.getMessage()); return; }
        task("Loading " + name, () -> {
            JSONObject site = connection.request(request("get").put("domain", name));
            pages.clear(); pages.put(name, site);
            ui(() -> { address.setText(getString(R.string.bww_address, name)); web.loadUrl(SiteOrigin.pageUrl(server, name)); });
        });
    }
    private WebResourceResponse resource(Uri uri) {
        String mime = "text/plain", content = "Resource unavailable"; int code = 404;
        String domain = "https".equals(uri.getScheme()) && uri.getPort() == -1 && uri.getUserInfo() == null ? SiteOrigin.resourceDomain(server, uri.getHost()) : null;
        JSONObject site = domain == null ? null : pages.get(domain);
        if (site != null) {
            String path = uri.getPath();
            if (SiteContent.pagePath(path)) {
                mime = "text/html";
                content = SiteContent.html(site.optString("html")); code = 200;
            } else if ("/style.css".equals(path)) { mime = "text/css"; content = site.optString("css"); code = 200; }
            else if ("/script.js".equals(path)) { mime = "application/javascript"; content = site.optString("js"); code = 200; }
        }
        Map<String,String> headers = new HashMap<>();
        headers.put("Content-Security-Policy", SiteContent.CSP);
        headers.put("X-Content-Type-Options", "nosniff"); headers.put("Cache-Control", "no-store");
        return new WebResourceResponse(mime, "UTF-8", code, code == 200 ? "OK" : "Not Found", headers,
            new ByteArrayInputStream(content.getBytes(StandardCharsets.UTF_8)));
    }
    private void listSites(boolean mine) {
        task(mine ? "Loading your sites" : "Discovering sites", () -> {
            JSONArray sites = connection.envelope(mine ? authenticated("mine") : request("list")).getJSONArray("data");
            String[] names = new String[sites.length()]; for (int i=0;i<names.length;i++) names[i] = sites.getJSONObject(i).getString("domain");
            ui(() -> {
                if (names.length == 0) { notice(mine ? "No sites yet. Tap Create Site." : "No published sites on this server yet."); return; }
                new AlertDialog.Builder(this).setTitle(mine ? "Your sites · choose to edit" : "Sites on this computer").setItems(names, (d,i) -> {
                    if (!mine) browse(names[i]);
                    else task("Loading editor", () -> { JSONObject site = connection.request(request("get").put("domain", names[i])); ui(() -> editor(site)); });
                }).setNegativeButton("Close", null).show();
            });
        });
    }
    private void editor(JSONObject existing) {
        if (token.isEmpty()) { notice("Sign in before creating a site"); accountDialog(); return; }
        final String key = "draft:" + server + ":" + username + ":" + (existing == null ? "new" : existing.optString("domain"));
        JSONObject draft = existing;
        try { if (prefs.contains(key)) draft = new JSONObject(prefs.getString(key, "{}")); } catch (JSONException ignored) { }
        ScrollView scroll = new ScrollView(this); LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(dp(16), 0, dp(16), 0); scroll.addView(form);
        EditText domain = new EditText(this); domain.setHint("my-site.bww"); domain.setSingleLine(true); form.addView(domain);
        EditText html = codeField(form, "HTML", 9), css = codeField(form, "CSS", 5), js = codeField(form, "JavaScript", 5);
        domain.setText(draft == null ? "" : draft.optString("domain")); domain.setEnabled(existing == null);
        html.setText(draft == null ? "<!doctype html>\n<html><head><title>My nearby site</title></head>\n<body><h1>Hello, nearby world!</h1>\n<button onclick=\"document.getElementById('message').textContent='It works!'\">Try me</button>\n<p id=\"message\"></p></body></html>" : draft.optString("html"));
        css.setText(draft == null ? "body { font-family: sans-serif; padding: 24px; background: #f4f7f5; color: #173e35; }\nbutton { padding: 12px; }" : draft.optString("css"));
        js.setText(draft == null ? "console.log('Welcome to BWW');" : draft.optString("js"));
        TextWatcher save = new TextWatcher() {
            public void beforeTextChanged(CharSequence s,int a,int c,int f) { }
            public void onTextChanged(CharSequence s,int a,int b,int c) {
                try { prefs.edit().putString(key, new JSONObject().put("domain",domain.getText().toString()).put("html",html.getText().toString()).put("css",css.getText().toString()).put("js",js.getText().toString()).toString()).apply(); } catch (JSONException ignored) { }
            }
            public void afterTextChanged(Editable e) { }
        };
        for (EditText field : new EditText[]{domain,html,css,js}) field.addTextChangedListener(save);
        form.addView(button("Check domain", v -> {
            String chosenDomain = domain.getText().toString();
            task("Checking domain", () -> {
                JSONObject result = connection.request(request("available").put("domain", chosenDomain));
                notice(result.getBoolean("available") ? "Domain is available. Publish to claim it." : "Domain is already published; only its owner can update it.");
            });
        }));
        form.addView(text(getString(R.string.editor_limits, connection.maxSiteBytes() / 1024), 12));
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        ProgressBar uploadProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); uploadProgress.setIndeterminate(true); uploadProgress.setVisibility(View.GONE);
        TextView uploadMessage = text("", 14); uploadMessage.setVisibility(View.GONE); uploadMessage.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        panel.addView(uploadProgress); panel.addView(uploadMessage); panel.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(existing == null ? "Create Site" : "Edit " + existing.optString("domain"))
            .setView(panel).setPositiveButton("Publish", null).setNegativeButton("Close", null)
            .setNeutralButton(existing == null ? "Discard draft" : "Delete site", null).create();
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                try {
                    if (busy) { notice("Please wait for the current operation"); return; }
                    String markup = html.getText().toString(), styles = css.getText().toString(), script = js.getText().toString();
                    long size = (long)markup.getBytes(StandardCharsets.UTF_8).length + styles.getBytes(StandardCharsets.UTF_8).length + script.getBytes(StandardCharsets.UTF_8).length;
                    if (size > connection.maxSiteBytes()) { notice(getString(R.string.site_too_large, connection.maxSiteBytes() / 1024)); return; }
                    String chosenDomain = SiteContent.domain(domain.getText().toString());
                    JSONObject payload = new JSONObject().put("domain", chosenDomain).put("html",markup).put("css",styles).put("js",script);
                    prefs.edit().putString(key, payload.toString()).apply();
                    String baseline = existing == null ? "missing" : SiteFingerprint.of(existing.optString("html"), existing.optString("css"), existing.optString("js"));
                    publishJobId = PublishQueue.enqueue(this, server, username, key, payload, baseline);
                    publishingDialog = dialog; publishProgress = uploadProgress; publishMessage = uploadMessage;
                    for (EditText field : new EditText[]{domain, html, css, js}) field.setEnabled(false);
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false); dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setEnabled(false);
                    restorePublishControls = () -> {
                        domain.setEnabled(existing == null); html.setEnabled(true); css.setEnabled(true); js.setEnabled(true);
                        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true); dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setEnabled(true);
                    };
                    connection.disconnect(); // Release this UI socket before the uploader connects.
                    if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                        requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
                    PublishService.start(this); refreshUpload();
                } catch (Exception e) { notice(e.getMessage()); }
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> new AlertDialog.Builder(this).setTitle(existing == null ? "Discard this draft?" : "Delete this published site?")
                .setPositiveButton("Delete", (a,w) -> {
                    if (existing == null) { prefs.edit().remove(key).apply(); dialog.dismiss(); }
                    else task("Deleting", () -> { connection.request(authenticated("delete").put("domain",existing.optString("domain"))); prefs.edit().remove(key).apply(); ui(dialog::dismiss); });
                }).setNegativeButton("Cancel", null).show());
        }); dialog.show(); dialog.getWindow().setLayout(-1, (int)(getResources().getDisplayMetrics().heightPixels * 0.85));
    }
    private void refreshUpload() {
        if (publishJobId == null) return;
        try {
            JSONObject job = PublishQueue.get(this, publishJobId); if (job == null) return;
            String state = job.optString("state"), message = job.optString("message"); status.setText(message);
            boolean active = "queued".equals(state); publishProgress.setVisibility(active ? View.VISIBLE : View.GONE);
            publishMessage.setText(message); publishMessage.setVisibility(View.VISIBLE);
            if (!active) {
                restorePublishControls.run();
                if ("done".equals(state)) { publishingDialog.dismiss(); notice(message); }
                publishJobId = null;
            }
        } catch (Exception e) { notice("Could not read upload status: " + e.getMessage()); }
    }
    private void uploadsDialog() {
        try {
            List<JSONObject> jobs = PublishQueue.pending(this);
            if (jobs.isEmpty()) { notice("No pending uploads"); return; }
            String[] labels = new String[jobs.size()];
            for (int i = 0; i < labels.length; ++i) { JSONObject job = jobs.get(i); labels[i] = job.getString("domain") + " · " + job.getString("address") + "\n" + job.optString("message"); }
            new AlertDialog.Builder(this).setTitle("Pending uploads · tap to cancel").setItems(labels, (dialog, index) -> {
                JSONObject job = jobs.get(index);
                new AlertDialog.Builder(this).setTitle("Cancel this upload?").setMessage("Your saved draft will remain. Cancelling cannot undo a publish already accepted by the host.")
                    .setPositiveButton("Cancel upload", (d,w) -> {
                        try { startService(new Intent(this, PublishService.class).setAction(PublishService.CANCEL).putExtra("id",job.getString("id"))); }
                        catch (Exception e) { notice(e.getMessage()); }
                    }).setNegativeButton("Keep upload", null).show();
            }).setNegativeButton("Close", null).show();
        } catch (Exception e) { notice(e.getMessage()); }
    }
    private EditText codeField(LinearLayout form, String label, int lines) {
        form.addView(text(label, 14)); EditText field = new EditText(this); field.setTypeface(android.graphics.Typeface.MONOSPACE); field.setTextSize(13);
        field.setInputType(1 | 131072 | 524288); field.setGravity(Gravity.TOP); field.setMinLines(lines); form.addView(field); return field;
    }
    @Override public void onBackPressed() { handleBack(); }
    private void handleBack() {
        if (fullScreen || customView != null) { exitFullScreen(); return; }
        if (!web.canGoBack()) { super.onBackPressed(); return; }
        WebBackForwardList history = web.copyBackForwardList();
        String url = history.getItemAtIndex(history.getCurrentIndex() - 1).getUrl();
        Uri uri = Uri.parse(url);
        if (uri.getHost() == null || "welcome.bww".equals(uri.getHost())) { web.goBack(); return; }
        final String name;
        try { name = SiteOrigin.navigationDomain(server, url); } catch (IllegalArgumentException e) { notice(e.getMessage()); return; }
        task("Loading previous site", () -> {
            JSONObject site = connection.request(request("get").put("domain", name));
            pages.clear(); pages.put(name, site);
            ui(() -> { address.setText(getString(R.string.bww_address, name)); web.goBack(); });
        });
    }
    private void updateBrowserPadding() {
        root.setPadding(fullScreen ? 0 : dp(16), fullScreen ? 0 : dp(10) + topInset, fullScreen ? 0 : dp(16), fullScreen ? 0 : bottomInset);
    }
    private void setFullScreen(boolean enabled) {
        boolean entering = enabled && !fullScreen;
        fullScreen = enabled;
        chrome.setVisibility(enabled ? View.GONE : View.VISIBLE);
        if (entering) {
            MotionEvent reset = MotionEvent.obtain(SystemClock.uptimeMillis(), SystemClock.uptimeMillis(), MotionEvent.ACTION_CANCEL, 0, 0, 0);
            fullScreenGesture.onTouchEvent(reset); reset.recycle();
            trackingTopGesture = false; consumeExitTouch = false;
            if (fullScreenHint != null) fullScreenHint.cancel();
            fullScreenHint = Toast.makeText(this, R.string.full_screen_hint, Toast.LENGTH_LONG); fullScreenHint.show();
        } else if (!enabled && fullScreenHint != null) fullScreenHint.cancel();
        updateBrowserPadding(); applySystemBars();
        root.requestApplyInsets();
    }
    private void applySystemBars() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                if (fullScreen) controller.hide(WindowInsets.Type.systemBars());
                else controller.show(WindowInsets.Type.systemBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(fullScreen
                ? View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                : View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }
    private void hideCustomView() {
        if (customView == null) return;
        website.removeView(customView); web.setVisibility(View.VISIBLE);
        WebChromeClient.CustomViewCallback callback = customViewCallback;
        customView = null; customViewCallback = null;
        setFullScreen(customWasFullScreen);
        callback.onCustomViewHidden();
    }
    private void exitFullScreen() { hideCustomView(); setFullScreen(false); }
    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) consumeExitTouch = false;
        // Observe top-edge gestures without consuming normal page taps, game taps, or scrolling.
        if (fullScreen) {
            int topBoundary = Math.max(dp(48), topInset);
            if (action == MotionEvent.ACTION_DOWN) {
                touchDownX = event.getX();
                touchDownY = event.getY();
                trackingTopGesture = touchDownY <= topBoundary;
            } else if (action == MotionEvent.ACTION_MOVE && trackingTopGesture) {
                float dy = event.getY() - touchDownY;
                float dx = Math.abs(event.getX() - touchDownX);
                if (dy >= dp(50) && dy > dx) {
                    trackingTopGesture = false;
                    consumeExitTouch = true;
                    MotionEvent cancel = MotionEvent.obtain(event.getDownTime(), event.getEventTime(), MotionEvent.ACTION_CANCEL, event.getX(), event.getY(), 0);
                    super.dispatchTouchEvent(cancel);
                    cancel.recycle();
                    exitFullScreen();
                    return true;
                }
            } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                trackingTopGesture = false;
            }
            fullScreenGesture.onTouchEvent(event);
        }
        if (consumeExitTouch) {
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) consumeExitTouch = false;
            return true;
        }
        return super.dispatchTouchEvent(event);
    }
    @Override public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_ESCAPE && (fullScreen || customView != null)) {
            exitFullScreen(); return true;
        }
        return super.onKeyUp(keyCode, event);
    }
    @Override public void onWindowFocusChanged(boolean focused) { super.onWindowFocusChanged(focused); if (focused && fullScreen) applySystemBars(); }
    @Override public void onDestroy() { unregisterReceiver(uploadReceiver); hideCustomView(); if (fullScreenHint != null) fullScreenHint.cancel(); connection.close(); worker.shutdownNow(); web.destroy(); super.onDestroy(); }
}
