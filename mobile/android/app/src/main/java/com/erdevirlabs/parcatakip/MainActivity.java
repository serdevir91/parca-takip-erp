package com.erdevirlabs.parcatakip;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Android shell for Parça Takip ERP: a WebView that opens the LAN server picked on the setup page
 * (assets/setup.html) and bridges what a plain WebView cannot do (downloads, LAN discovery, updates).
 */
public class MainActivity extends Activity {
    private static final String SETUP = "file:///android_asset/setup.html";
    private static final String RELEASES = "https://api.github.com/repos/serdevir91/parca-takip-erp/releases/latest";
    private static final int REQ_FILES = 1;

    private WebView web;
    private FrameLayout root;
    private SharedPreferences prefs;
    private final Handler ui = new Handler(Looper.getMainLooper());
    /** Origin of the page now shown; the bridge only serves the setup page and the saved server. */
    private volatile String pageOrigin = "";
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("erp", MODE_PRIVATE);
        root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        setupInsets();
        setupWebView();
        setupBack();

        if (state != null) web.restoreState(state);
        else if (!server().isEmpty()) web.loadUrl(server() + "/");
        else web.loadUrl(SETUP);
        ui.postDelayed(() -> checkUpdate(false), 4000);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    // ---- window -------------------------------------------------------------------------------

    private void setupInsets() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((v, insets) -> {
                android.graphics.Insets i = insets.getInsets(WindowInsets.Type.systemBars()
                        | WindowInsets.Type.ime() | WindowInsets.Type.displayCutout());
                v.setPadding(i.left, i.top, i.right, i.bottom);
                return WindowInsets.CONSUMED;
            });
        }
    }

    /** Status/navigation bar colours follow the web app theme (called from the page). */
    private void applyTheme(String bg, boolean dark) {
        int color;
        try {
            color = Color.parseColor(bg);
        } catch (Exception e) {
            return;
        }
        root.setBackgroundColor(color);
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            int light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            WindowInsetsController c = w.getInsetsController();
            if (c != null) c.setSystemBarsAppearance(dark ? 0 : light, light);
        } else {
            w.setStatusBarColor(color);
            w.setNavigationBarColor(color);
            View d = w.getDecorView();
            int f = d.getSystemUiVisibility();
            f = dark ? f & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR : f | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            d.setSystemUiVisibility(f);
        }
    }

    private void setupBack() {
        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::goBack);
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        goBack();
    }

    /** The page may close its own menu or dialog first (window.__erpBack), then history, then exit. */
    private void goBack() {
        web.evaluateJavascript("(window.__erpBack && window.__erpBack()) ? 1 : 0", v -> {
            if ("1".equals(v)) return;
            if (web.canGoBack()) web.goBack();
            else finish();
        });
    }

    // ---- web view -----------------------------------------------------------------------------

    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setSupportMultipleWindows(false);
        s.setUserAgentString(s.getUserAgentString() + " ParcaTakipERP-Android/" + BuildConfig.VERSION_NAME);
        web.addJavascriptInterface(new Bridge(), "ParcaTakipApp");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                String url = req.getUrl().toString();
                if (url.startsWith(SETUP) || (!server().isEmpty() && originOf(url).equals(server()))) return false;
                openExternal(url);
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageOrigin = url.startsWith(SETUP) ? "setup" : originOf(url);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (!req.isForMainFrame() || req.getUrl().toString().startsWith("file:")) return;
                showSetup("error=" + enc(String.valueOf(err.getDescription())));
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                return openChooser(cb, params);
            }
        });

        // Plain links with a real URL (not blob:); the web app routes protected files through Bridge.download.
        web.setDownloadListener((url, ua, cd, mime, len) -> {
            if (url.startsWith("http")) saveFile(url, URLUtil.guessFileName(url, cd, mime), null);
        });
    }

    private void showSetup(String query) {
        web.loadUrl(SETUP + (query.isEmpty() ? "" : "?" + query));
    }

    // ---- file chooser -------------------------------------------------------------------------

    private boolean openChooser(ValueCallback<Uri[]> cb, WebChromeClient.FileChooserParams params) {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        fileCallback = cb;
        cameraUri = null;

        List<String> types = new ArrayList<>();
        boolean images = false;
        for (String t : params.getAcceptTypes()) {
            for (String one : t.split(",")) {
                one = one.trim().toLowerCase(Locale.ROOT);
                if (one.isEmpty()) continue;
                if (one.startsWith(".")) {
                    String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(one.substring(1));
                    if (m == null) continue;
                    one = m;
                }
                types.add(one);
                if (one.startsWith("image/")) images = true;
            }
        }
        Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
        pick.addCategory(Intent.CATEGORY_OPENABLE);
        pick.setType(types.size() == 1 ? types.get(0) : "*/*");
        if (types.size() > 1) pick.putExtra(Intent.EXTRA_MIME_TYPES, types.toArray(new String[0]));
        if (params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);

        Intent chooser = Intent.createChooser(pick, "Dosya seç");
        if (images || params.isCaptureEnabled()) {
            try {
                File dir = new File(getCacheDir(), "camera");
                dir.mkdirs();
                File f = File.createTempFile("foto_", ".jpg", dir);
                cameraUri = FileProvider.getUriForFile(this, getPackageName() + ".files", f);
                Intent cam = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                cam.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
                cam.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cam});
            } catch (Exception ignored) {
                cameraUri = null;
            }
        }
        try {
            startActivityForResult(chooser, REQ_FILES);
            return true;
        } catch (ActivityNotFoundException e) {
            fileCallback = null;
            toast("Dosya seçici bulunamadı");
            return false;
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req != REQ_FILES || fileCallback == null) return;
        Uri[] out = null;
        if (result == RESULT_OK) {
            if (data != null && data.getClipData() != null) {
                out = new Uri[data.getClipData().getItemCount()];
                for (int i = 0; i < out.length; i++) out[i] = data.getClipData().getItemAt(i).getUri();
            } else if (data != null && data.getData() != null) {
                out = new Uri[]{data.getData()};
            } else if (cameraUri != null) {
                out = new Uri[]{cameraUri};
            }
        }
        fileCallback.onReceiveValue(out);
        fileCallback = null;
    }

    // ---- downloads ----------------------------------------------------------------------------

    /** Fetch `url` (with the JWT when given) into Downloads, then offer to open it. */
    private void saveFile(String url, String fallbackName, String token) {
        toast("İndiriliyor…");
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(60000);
                if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
                int code = c.getResponseCode();
                if (code != 200) throw new Exception("Sunucu yanıtı " + code);
                String name = nameFrom(c.getHeaderField("Content-Disposition"), fallbackName);
                String mime = c.getContentType();
                if (mime != null) mime = mime.split(";")[0].trim();
                if (mime == null || mime.isEmpty() || mime.equals("application/octet-stream")) {
                    String ext = MimeTypeMap.getFileExtensionFromUrl(name.replace(' ', '_'));
                    String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.toLowerCase(Locale.ROOT));
                    mime = m != null ? m : "application/octet-stream";
                }
                Uri saved;
                try (InputStream in = c.getInputStream()) {
                    saved = write(in, name, mime);
                }
                final String m = mime;
                ui.post(() -> new AlertDialog.Builder(this)
                        .setTitle("İndirildi")
                        .setMessage(name + "\nİndirilenler klasörüne kaydedildi.")
                        .setPositiveButton("Aç", (d, w) -> openFile(saved, m))
                        .setNegativeButton("Kapat", null)
                        .show());
            } catch (Exception e) {
                ui.post(() -> toast("İndirme başarısız: " + e.getMessage()));
            } finally {
                if (c != null) c.disconnect();
            }
        }).start();
    }

    private Uri write(InputStream in, String name, String mime) throws Exception {
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.MIME_TYPE, mime);
            v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/ParcaTakip");
            v.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri == null) throw new Exception("Dosya oluşturulamadı");
            try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                copy(in, out);
            }
            v.clear();
            v.put(MediaStore.Downloads.IS_PENDING, 0);
            getContentResolver().update(uri, v, null, null);
            return uri;
        }
        File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (dir == null) dir = new File(getFilesDir(), "Download");
        dir.mkdirs();
        File f = new File(dir, name);
        try (OutputStream out = new FileOutputStream(f)) {
            copy(in, out);
        }
        return FileProvider.getUriForFile(this, getPackageName() + ".files", f);
    }

    private static void copy(InputStream in, OutputStream out) throws Exception {
        byte[] buf = new byte[64 * 1024];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
    }

    private static String nameFrom(String cd, String fallback) {
        String name = null;
        if (cd != null) {
            Matcher m = Pattern.compile("filename\\*=UTF-8''([^;]+)", Pattern.CASE_INSENSITIVE).matcher(cd);
            if (m.find()) {
                try {
                    name = URLDecoder.decode(m.group(1), "UTF-8");
                } catch (Exception ignored) {
                }
            }
            if (name == null) {
                m = Pattern.compile("filename=\"?([^\";]+)\"?", Pattern.CASE_INSENSITIVE).matcher(cd);
                if (m.find()) name = m.group(1);
            }
        }
        if (name == null || name.trim().isEmpty()) name = fallback == null || fallback.isEmpty() ? "dosya" : fallback;
        return name.replaceAll("[\\\\/:*?\"<>|\\x00-\\x1f]", "_").trim();
    }

    private void openFile(Uri uri, String mime) {
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(uri, mime);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(i);
        } catch (ActivityNotFoundException e) {
            toast("Bu dosyayı açacak uygulama yok");
        }
    }

    // ---- app update ---------------------------------------------------------------------------

    static final String[] ABIS = {"arm64-v8a", "armeabi-v7a", "x86_64", "x86"};

    /** Release APK for this phone: the split matching its preferred ABI, else the universal one, else any APK. */
    private static String pickApk(JSONArray assets) throws Exception {
        String universal = null, any = null;
        for (String abi : Build.SUPPORTED_ABIS) {
            for (int i = 0; assets != null && i < assets.length(); i++) {
                String u = assets.getJSONObject(i).optString("browser_download_url", "");
                if (u.endsWith("-" + abi + ".apk")) return u;
            }
        }
        for (int i = 0; assets != null && i < assets.length(); i++) {
            String u = assets.getJSONObject(i).optString("browser_download_url", "");
            if (!u.endsWith(".apk")) continue;
            any = u;
            boolean split = false;
            for (String abi : ABIS) split |= u.endsWith("-" + abi + ".apk");
            if (!split) universal = u;
        }
        return universal != null ? universal : any;
    }

    /** Latest GitHub release vs this build; silent at startup, with feedback when `manual`. */
    private void checkUpdate(boolean manual) {
        if (manual) toast("Güncelleme kontrol ediliyor…");
        new Thread(() -> {
            try {
                String body = Discovery.get(RELEASES, 6000);
                if (body == null) throw new Exception("Sunucuya ulaşılamadı");
                JSONObject rel = new JSONObject(body);
                String latest = rel.optString("tag_name", "").replaceFirst("^v", "");
                String apk = pickApk(rel.optJSONArray("assets"));
                String page = apk != null ? apk : rel.optString("html_url", "");
                if (newer(latest, BuildConfig.VERSION_NAME) && !page.isEmpty()) {
                    ui.post(() -> new AlertDialog.Builder(this)
                            .setTitle("Güncelleme var")
                            .setMessage("Parça Takip ERP " + latest + " yayınlandı (yüklü: " + BuildConfig.VERSION_NAME + ").\n"
                                    + "APK indirilecek; kurulum için dosyayı açın.")
                            .setPositiveButton("İndir", (d, w) -> openExternal(page))
                            .setNegativeButton("Sonra", null)
                            .show());
                } else if (manual) {
                    ui.post(() -> toast("Uygulama güncel (" + BuildConfig.VERSION_NAME + ")"));
                }
            } catch (Exception e) {
                if (manual) ui.post(() -> toast("Güncelleme kontrol edilemedi"));
            }
        }).start();
    }

    static boolean newer(String a, String b) {
        String[] x = a.split("\\."), y = b.split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? num(x[i]) : 0, q = i < y.length ? num(y[i]) : 0;
            if (p != q) return p > q;
        }
        return false;
    }

    private static int num(String s) {
        try {
            return Integer.parseInt(s.replaceAll("\\D.*", ""));
        } catch (Exception e) {
            return 0;
        }
    }

    // ---- helpers ------------------------------------------------------------------------------

    private String server() {
        return prefs.getString("server", "");
    }

    static String originOf(String url) {
        try {
            Uri u = Uri.parse(url);
            if (u.getScheme() == null || u.getHost() == null) return "";
            return u.getScheme() + "://" + u.getHost() + (u.getPort() > 0 ? ":" + u.getPort() : "");
        } catch (Exception e) {
            return "";
        }
    }

    /** "192.168.1.5", "192.168.1.5:8000/" or "http://host" -> "http://host[:port]"; "" when invalid. */
    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return "";
        if (!s.matches("(?i)^https?://.*")) s = "http://" + s;
        String o = originOf(s);
        return o.toLowerCase(Locale.ROOT).startsWith("http") ? o : "";
    }

    private void openExternal(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (ActivityNotFoundException e) {
            toast("Bağlantı açılamadı");
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    private void callback(String id, String json) {
        String js = "window.__erpCb && window.__erpCb(" + JSONObject.quote(id) + "," + json + ")";
        ui.post(() -> web.evaluateJavascript(js, null));
    }

    // ---- JS bridge (window.ParcaTakipApp) -----------------------------------------------------

    private final class Bridge {
        private boolean setupPage() {
            return "setup".equals(pageOrigin);
        }

        private boolean trusted() {
            return setupPage() || (!server().isEmpty() && pageOrigin.equals(server()));
        }

        @JavascriptInterface
        public String appVersion() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public String getConfig() {
            if (!trusted()) return "{}";
            try {
                return new JSONObject()
                        .put("server", server())
                        .put("recent", new JSONArray(prefs.getString("recent", "[]")))
                        .put("version", BuildConfig.VERSION_NAME)
                        .toString();
            } catch (Exception e) {
                return "{}";
            }
        }

        @JavascriptInterface
        public void discover(String cb) {
            if (!setupPage()) return;
            new Thread(() -> callback(cb, Discovery.find().toString())).start();
        }

        @JavascriptInterface
        public void check(String url, String cb) {
            if (!setupPage()) return;
            String base = normalize(url);
            new Thread(() -> {
                JSONObject r = base.isEmpty() ? null : Discovery.check(base, 4000);
                callback(cb, r == null ? "null" : r.toString());
            }).start();
        }

        @JavascriptInterface
        public void connect(String url) {
            if (!setupPage()) return;
            String base = normalize(url);
            if (base.isEmpty()) return;
            try {
                JSONArray old = new JSONArray(prefs.getString("recent", "[]"));
                JSONArray recent = new JSONArray().put(base);
                for (int i = 0; i < old.length() && recent.length() < 6; i++) {
                    if (!base.equals(old.optString(i))) recent.put(old.optString(i));
                }
                prefs.edit().putString("server", base).putString("recent", recent.toString()).apply();
            } catch (Exception e) {
                prefs.edit().putString("server", base).apply();
            }
            ui.post(() -> {
                web.clearHistory();
                web.loadUrl(base + "/");
            });
        }

        @JavascriptInterface
        public void forget(String url) {
            if (!setupPage()) return;
            try {
                JSONArray old = new JSONArray(prefs.getString("recent", "[]"));
                JSONArray recent = new JSONArray();
                for (int i = 0; i < old.length(); i++) if (!old.optString(i).equals(url)) recent.put(old.optString(i));
                prefs.edit().putString("recent", recent.toString()).apply();
            } catch (Exception ignored) {
            }
        }

        @JavascriptInterface
        public void changeServer() {
            if (!trusted()) return;
            ui.post(() -> showSetup("change=1"));
        }

        @JavascriptInterface
        public void download(String url, String filename, String token) {
            // The JWT only goes back to the server it came from.
            if (server().isEmpty() || !pageOrigin.equals(server()) || !originOf(url).equals(server())) return;
            ui.post(() -> saveFile(url, filename, token));
        }

        @JavascriptInterface
        public void checkUpdate(boolean manual) {
            if (!trusted()) return;
            ui.post(() -> MainActivity.this.checkUpdate(manual));
        }

        @JavascriptInterface
        public void openExternal(String url) {
            if (!trusted() || !url.matches("(?i)^https?://.*")) return;
            ui.post(() -> MainActivity.this.openExternal(url));
        }

        @JavascriptInterface
        public void setTheme(String bg, boolean dark) {
            if (!trusted()) return;
            ui.post(() -> applyTheme(bg, dark));
        }
    }
}
