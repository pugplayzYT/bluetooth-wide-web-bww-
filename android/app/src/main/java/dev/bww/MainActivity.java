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
    private String server = "", token = "", username = "";
    private TextView status, account;
    private EditText address;
    private WebView web;
    private LinearLayout root;
    private boolean busy;

    interface Job { void run() throws Exception; }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("bww", MODE_PRIVATE);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(10), dp(16), 0); root.setBackgroundColor(Color.rgb(244,247,245));
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(dp(16), dp(10) + insets.getSystemWindowInsetTop(), dp(16), insets.getSystemWindowInsetBottom());
            return insets;
        });
        TextView title = text("Bluetooth-wide Web", 24); title.setTypeface(null, android.graphics.Typeface.BOLD); root.addView(title);
        root.addView(text("A little web, right around you.", 14));
        status = text("Pair your computer in Bluetooth settings, then connect.", 13); root.addView(status);
        LinearLayout toolbar = row();
        toolbar.addView(button("Connect", v -> chooseServer()));
        toolbar.addView(button("Sites", v -> listSites(false)));
        toolbar.addView(button("Account", v -> accountDialog())); root.addView(toolbar);
        account = text("Browsing as a guest", 13); root.addView(account);
        LinearLayout url = row(); address = new EditText(this); address.setSingleLine(true);
        address.setHint("bww://my-site.bww"); address.setInputType(17);
        url.addView(address, new LinearLayout.LayoutParams(0, -2, 1));
        url.addView(button("Go", v -> browse(address.getText().toString()))); root.addView(url);
        address.setOnEditorActionListener((v, action, event) -> { browse(address.getText().toString()); return true; });
        LinearLayout author = row(); author.addView(button("Create Site", v -> editor(null)));
        author.addView(button("My Sites", v -> listSites(true))); root.addView(author);
        web = new WebView(this);
        WebSettings settings = web.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (request.isForMainFrame() && "https".equals(uri.getScheme()) && uri.getHost() != null && uri.getHost().endsWith(".bww")) {
                    if (!"/".equals(uri.getPath()) && !"/index.html".equals(uri.getPath())) { notice("Only index.html, style.css, and script.js are supported"); return true; }
                    browse(uri.toString());
                } else if (request.isForMainFrame()) notice("Only Bluetooth-wide Web sites can open here");
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return resource(request.getUrl());
            }
            @Override public void onReceivedSslError(WebView view, android.webkit.SslErrorHandler handler, android.net.http.SslError error) { handler.cancel(); }
        });
        web.setWebChromeClient(new WebChromeClient());
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1)); setContentView(root);
        web.loadDataWithBaseURL("https://welcome.bww/", "<html><meta name='viewport' content='width=device-width'><body style='font-family:sans-serif;padding:24px;color:#173e35'><h1>Welcome to your nearby web.</h1><p>1. Start BWW on your Windows computer.</p><p>2. Pair your phone with the computer.</p><p>3. Tap Connect and choose it.</p><p>Browse sites, or sign in to publish your own HTML, CSS, and JavaScript.</p></body></html>", "text/html", "UTF-8", null);
    }
    private int dp(int n) { return (int)(getResources().getDisplayMetrics().density * n); }
    private TextView text(String value, int size) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(Color.rgb(23,62,53)); t.setPadding(0, dp(4), 0, dp(4)); return t; }
    private LinearLayout row() { LinearLayout r = new LinearLayout(this); r.setOrientation(LinearLayout.HORIZONTAL); return r; }
    private Button button(String value, View.OnClickListener action) { Button b = new Button(this); b.setText(value); b.setTextSize(12); b.setOnClickListener(action); return b; }
    private void notice(String value) { runOnUiThread(() -> Toast.makeText(this, value, Toast.LENGTH_LONG).show()); }
    private void ui(Runnable action) { runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) action.run(); }); }
    private void task(String label, Job job) {
        if (busy) { notice("Please wait for the current operation"); return; }
        busy = true; status.setText(getString(R.string.progress, label));
        worker.execute(() -> {
            try { job.run(); ui(() -> status.setText(connection.connected() ? "Connected · " + server : "Disconnected · tap Connect")); }
            catch (Exception e) {
                if (e instanceof BwwConnection.ApiException && "unauthorized".equals(((BwwConnection.ApiException)e).code)) {
                    token = ""; username = ""; prefs.edit().remove("token:" + server).remove("user:" + server).apply(); ui(this::updateAccount);
                }
                ui(() -> { status.setText(connection.connected() ? "Connected · " + server : "Disconnected · tap Connect"); notice(e.getMessage() == null ? "Operation failed" : e.getMessage()); });
            } finally { ui(() -> busy = false); }
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
                boolean changedServer = !device.getAddress().equals(server);
                server = device.getAddress(); pages.clear();
                token = prefs.getString("token:" + server, ""); username = prefs.getString("user:" + server, "");
                if (!token.isEmpty()) {
                    try { username = connection.request(authenticated("me")).getString("username"); }
                    catch (BwwConnection.ApiException e) {
                        if (!"unauthorized".equals(e.code)) throw e;
                        token = ""; username = ""; prefs.edit().remove("token:" + server).remove("user:" + server).apply();
                    }
                }
                ui(() -> {
                    if (changedServer) WebStorage.getInstance().deleteAllData();
                    updateAccount(); web.loadUrl("about:blank"); web.clearHistory();
                    notice("Connected. Tap Sites to explore.");
                });
            });
        }).setNegativeButton("Cancel", null).show();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(code, permissions, grants);
        if (code == 1 && grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) chooseServer();
        else notice("Bluetooth permission is needed to connect");
    }
    private void accountDialog() {
        if (!connection.connected()) { notice("Connect to a server first"); return; }
        if (!token.isEmpty()) {
            new AlertDialog.Builder(this).setTitle("Signed in as " + username).setMessage("Your session is saved for this computer for up to 30 days.")
                .setPositiveButton("Sign out", (d,w) -> task("Signing out", () -> {
                    connection.request(authenticated("logout")); token = ""; username = "";
                    prefs.edit().remove("token:" + server).remove("user:" + server).apply(); ui(this::updateAccount);
                })).setNegativeButton("Close", null).show(); return;
        }
        LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(dp(20), dp(8), dp(20), 0);
        EditText user = new EditText(this); user.setHint("Username (3–32 letters/numbers/_)"); user.setSingleLine(true); user.setInputType(1 | 524288);
        EditText password = new EditText(this); password.setHint("Password (at least 10 characters)"); password.setInputType(129);
        form.addView(user); form.addView(password);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Your account on this server").setView(form)
            .setPositiveButton("Sign in", null).setNeutralButton("Register", null).setNegativeButton("Cancel", null).create();
        dialog.setOnShowListener(d -> {
            View.OnClickListener login = v -> {
                String name = user.getText().toString(), pass = password.getText().toString();
                String op = v == dialog.getButton(AlertDialog.BUTTON_NEUTRAL) ? "register" : "login";
                task("Signing in", () -> {
                    JSONObject result = connection.request(request(op).put("username", name).put("password", pass));
                    token = result.getString("token"); username = result.getString("username");
                    prefs.edit().putString("token:" + server, token).putString("user:" + server, username).apply();
                    ui(() -> { password.setText(""); dialog.dismiss(); updateAccount(); });
                });
            };
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(login);
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(login);
        }); dialog.show();
    }
    private void browse(String value) {
        final String name;
        try { name = SiteContent.domain(value); } catch (Exception e) { notice(e.getMessage()); return; }
        task("Loading " + name, () -> {
            JSONObject site = connection.request(request("get").put("domain", name));
            pages.clear(); pages.put(name, site);
            ui(() -> { address.setText(getString(R.string.bww_address, name)); web.loadUrl("https://" + name + "/index.html"); });
        });
    }
    private WebResourceResponse resource(Uri uri) {
        String mime = "text/plain", content = "Resource unavailable"; int code = 404;
        JSONObject site = "https".equals(uri.getScheme()) ? pages.get(uri.getHost()) : null;
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
        form.addView(text("Drafts save on this phone. Published sites save on the computer. Limit: 512 KiB total. Only index.html, style.css and script.js; no external network resources.", 12));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(existing == null ? "Create Site" : "Edit " + existing.optString("domain"))
            .setView(scroll).setPositiveButton("Publish", null).setNegativeButton("Close", null)
            .setNeutralButton(existing == null ? "Discard draft" : "Delete site", null).create();
        dialog.setOnShowListener(d -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                try {
                    JSONObject payload = authenticated("publish").put("domain",domain.getText().toString()).put("html",html.getText().toString()).put("css",css.getText().toString()).put("js",js.getText().toString());
                    task("Publishing", () -> { JSONObject result = connection.request(payload); prefs.edit().remove(key).apply(); ui(() -> { dialog.dismiss(); notice("Published · bww://" + result.optString("domain")); }); });
                } catch (Exception e) { notice(e.getMessage()); }
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> new AlertDialog.Builder(this).setTitle(existing == null ? "Discard this draft?" : "Delete this published site?")
                .setPositiveButton("Delete", (a,w) -> {
                    if (existing == null) { prefs.edit().remove(key).apply(); dialog.dismiss(); }
                    else task("Deleting", () -> { connection.request(authenticated("delete").put("domain",existing.optString("domain"))); prefs.edit().remove(key).apply(); ui(dialog::dismiss); });
                }).setNegativeButton("Cancel", null).show());
        }); dialog.show();
    }
    private EditText codeField(LinearLayout form, String label, int lines) {
        form.addView(text(label, 14)); EditText field = new EditText(this); field.setTypeface(android.graphics.Typeface.MONOSPACE); field.setTextSize(13);
        field.setInputType(1 | 131072 | 524288); field.setGravity(Gravity.TOP); field.setMinLines(lines); form.addView(field); return field;
    }
    @Override public void onBackPressed() {
        if (!web.canGoBack()) { super.onBackPressed(); return; }
        WebBackForwardList history = web.copyBackForwardList();
        String url = history.getItemAtIndex(history.getCurrentIndex() - 1).getUrl();
        Uri uri = Uri.parse(url);
        if (uri.getHost() == null || "welcome.bww".equals(uri.getHost())) { web.goBack(); return; }
        task("Loading previous site", () -> {
            JSONObject site = connection.request(request("get").put("domain", uri.getHost()));
            pages.clear(); pages.put(uri.getHost(), site);
            ui(() -> { address.setText(getString(R.string.bww_address, uri.getHost())); web.goBack(); });
        });
    }
    @Override public void onDestroy() { connection.close(); worker.shutdownNow(); web.destroy(); super.onDestroy(); }
}
