package com.erdevirlabs.parcatakip;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.print.PrintManager;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import androidx.core.content.FileProvider;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Android shell for LAB ERP: a WebView that opens the LAN server picked on the setup page
 * (assets/setup.html) and bridges what a plain WebView cannot do (downloads, LAN discovery, updates).
 */
public class MainActivity extends Activity {
    private static final String SETUP = "file:///android_asset/setup.html";
    private static final String RELEASES = "https://api.github.com/repos/serdevir91/parca-takip-erp/releases/latest";
    private static final int REQ_FILES = 1;
    private static final int REQ_CAMERA = 2;
    private static final int REQ_CHOOSER_CAMERA = 3;
    private static final int REQ_NOTIFY = 4;
    static final String EXTRA_LINK = "link";
    /** Read by AlertService: while the app is on screen it shows new things itself. */
    static volatile boolean onScreen;

    private WebView web;
    private FrameLayout root;
    private SharedPreferences prefs;
    private final Handler ui = new Handler(Looper.getMainLooper());
    /** Origin of the page now shown; the bridge only serves the setup page and the saved server. */
    private volatile String pageOrigin = "";
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;
    private PermissionRequest cameraRequest;
    private WebChromeClient.FileChooserParams chooserParams;
    private boolean cameraAsked;

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
        else if (!server().isEmpty()) web.loadUrl(server() + linkOf(getIntent(), "/"));
        else web.loadUrl(SETUP);
        ui.postDelayed(() -> checkUpdate(false), 4000);
    }

    /** A tapped notification reaches the running app here. */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String link = linkOf(intent, null);
        if (link != null && !server().isEmpty()) web.loadUrl(server() + link);
    }

    private static String linkOf(Intent intent, String fallback) {
        String link = intent.getStringExtra(EXTRA_LINK);
        return link != null && link.startsWith("/") ? link : fallback;
    }

    @Override
    protected void onResume() {
        super.onResume();
        onScreen = true;
        getSystemService(NotificationManager.class).cancelAll();
        startAlerts();
    }

    /** Android 13+ asks the user once; AlertService stays off while notifications are not allowed. */
    private void startAlerts() {
        if (server().isEmpty()) return;
        if (Build.VERSION.SDK_INT >= 33 && !prefs.getBoolean("notify_asked", false)
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            prefs.edit().putBoolean("notify_asked", true).apply();
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFY);
            return;
        }
        AlertService.sync(this);
    }

    /** The session cookie lives in the WebView's store, which only reaches the disk on its own schedule. */
    @Override
    protected void onPause() {
        super.onPause();
        onScreen = false;
        CookieManager.getInstance().flush();
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
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                if (!downgrade(req.getUrl().toString())) return null;
                return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", null, new ByteArrayInputStream(new byte[0]));
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

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError err) {
                checkCertificate(handler, err);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                return openChooser(cb, params);
            }

            @Override
            public void onPermissionRequest(PermissionRequest req) {
                askCamera(req);
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

    // ---- server certificate (see Pin) ---------------------------------------------------------

    private void checkCertificate(SslErrorHandler handler, SslError err) {
        String origin = originOf(err.getUrl());
        String seen;
        try {
            seen = Pin.fingerprint(err.getCertificate());
        } catch (Exception e) {
            seen = "";
        }
        if (seen.isEmpty() || server().isEmpty() || !origin.equals(server())) {
            handler.cancel();
            return;
        }
        String pinned = prefs.getString("pin:" + origin, null);
        if (seen.equals(pinned)) {
            handler.proceed();
            return;
        }
        if (pinned != null) {
            handler.cancel();
            showSetup("cert=changed");
            return;
        }
        String fingerprint = seen;
        new AlertDialog.Builder(this)
                .setTitle(R.string.cert_dialog_title)
                .setMessage(getString(R.string.cert_dialog_msg, Pin.pretty(fingerprint)))
                .setCancelable(false)
                .setPositiveButton(R.string.cert_btn_trust, (d, w) -> {
                    prefs.edit().putString("pin:" + origin, fingerprint).apply();
                    handler.proceed();
                })
                .setNegativeButton(R.string.btn_cancel, (d, w) -> {
                    handler.cancel();
                    showSetup("");
                })
                .show();
    }

    /**
     * True for a plain http address of a server known to be on https. The manifest cannot switch cleartext off per
     * server: a LAN server starts on plain HTTP and its address is only known at run time, so the app refuses here.
     * Forgetting the server is the way back to http, for a server that really turned HTTPS off.
     */
    private boolean downgrade(String url) {
        return downgrade(prefs, url);
    }

    private static boolean downgrade(SharedPreferences prefs, String url) {
        Uri u = Uri.parse(url);
        String host = u.getHost();
        if (!"http".equalsIgnoreCase(u.getScheme()) || host == null) return false;
        Uri saved = Uri.parse(prefs.getString("server", ""));
        if ("https".equalsIgnoreCase(saved.getScheme()) && host.equalsIgnoreCase(saved.getHost())) return true;
        String pin = "pin:https://" + host;
        for (String key : prefs.getAll().keySet()) {
            if (key.equals(pin) || key.startsWith(pin + ":")) return true;
        }
        return false;
    }

    /** A remembered server keeps its pin; everything else goes by the system's trust store. */
    private HttpURLConnection open(String url) throws Exception {
        return open(this, prefs, url);
    }

    static HttpURLConnection open(android.content.Context context, SharedPreferences prefs, String url) throws Exception {
        if (downgrade(prefs, url)) throw new IOException(context.getString(R.string.err_server_downgrade));
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        String pin = prefs.getString("pin:" + originOf(url), null);
        if (pin != null) Pin.apply(context, c, pin);
        return c;
    }

    static HttpURLConnection open(SharedPreferences prefs, String url) throws Exception {
        return open(null, prefs, url);
    }

    // ---- camera -------------------------------------------------------------------------------

    private boolean hasCamera() {
        return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    private void askCamera(PermissionRequest req) {
        boolean camera = Arrays.asList(req.getResources()).contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE);
        if (!camera || server().isEmpty() || !originOf(req.getOrigin().toString()).equals(server())) {
            req.deny();
        } else if (hasCamera()) {
            req.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        } else {
            if (cameraRequest != null) cameraRequest.deny();
            cameraRequest = req;
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
        }
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(req, permissions, results);
        if (req == REQ_CAMERA && cameraRequest != null) {
            if (hasCamera()) cameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            else cameraRequest.deny();
            cameraRequest = null;
        } else if (req == REQ_CHOOSER_CAMERA && chooserParams != null) {
            WebChromeClient.FileChooserParams params = chooserParams;
            ValueCallback<Uri[]> cb = fileCallback;
            chooserParams = null;
            if (!showChooser(params) && cb != null) cb.onReceiveValue(null);
        }
    }

    // ---- file chooser -------------------------------------------------------------------------

    private boolean openChooser(ValueCallback<Uri[]> cb, WebChromeClient.FileChooserParams params) {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        fileCallback = cb;
        cameraUri = null;
        cameraAsked = false;
        return showChooser(params);
    }

    private boolean showChooser(WebChromeClient.FileChooserParams params) {
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

        Intent chooser = Intent.createChooser(pick, getString(R.string.choose_file));
        if ((images || params.isCaptureEnabled()) && !hasCamera() && !cameraAsked) {
            // With CAMERA in the manifest, the camera app refuses to start until the user has allowed it.
            cameraAsked = true;
            chooserParams = params;
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CHOOSER_CAMERA);
            return true;
        }
        if ((images || params.isCaptureEnabled()) && hasCamera()) {
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
            toast(getString(R.string.err_no_file_chooser));
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
        toast(getString(R.string.toast_downloading));
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                c = open(url);
                c.setConnectTimeout(8000);
                c.setReadTimeout(60000);
                if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
                int code = c.getResponseCode();
                if (code != 200) throw new Exception(getString(R.string.err_server_response, code));
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
                        .setTitle(R.string.downloaded_title)
                        .setMessage(getString(R.string.downloaded_msg, name))
                        .setPositiveButton(R.string.btn_open, (d, w) -> openFile(saved, m))
                        .setNegativeButton(R.string.btn_close, null)
                        .show());
            } catch (Exception e) {
                ui.post(() -> toast(getString(R.string.err_download_failed, e.getMessage())));
            } finally {
                if (c != null) c.disconnect();
            }
        }).start();
    }

    /** Share a server file (export, list) through the Android share sheet: Gmail, WhatsApp, Drive… */
    private void shareFile(String url, String fallbackName, String token) {
        toast(getString(R.string.toast_preparing));
        new Thread(() -> {
            HttpURLConnection c = null;
            try {
                c = open(url);
                c.setConnectTimeout(8000);
                c.setReadTimeout(60000);
                if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
                int code = c.getResponseCode();
                if (code != 200) throw new Exception(getString(R.string.err_server_response, code));
                String name = nameFrom(c.getHeaderField("Content-Disposition"), fallbackName);
                String mime = c.getContentType();
                if (mime != null) mime = mime.split(";")[0].trim();
                File f;
                try (InputStream in = c.getInputStream()) {
                    f = shareCache(name);
                    try (OutputStream out = new FileOutputStream(f)) {
                        copy(in, out);
                    }
                }
                final String m = mime;
                ui.post(() -> startShare(f, m, name));
            } catch (Exception e) {
                ui.post(() -> toast(getString(R.string.err_share_failed, e.getMessage())));
            } finally {
                if (c != null) c.disconnect();
            }
        }).start();
    }

    /** Share data the page built itself (a list as CSV), passed as base64. */
    private void shareData(String base64, String name, String mime) {
        try {
            File f = shareCache(name);
            try (OutputStream out = new FileOutputStream(f)) {
                out.write(android.util.Base64.decode(base64, android.util.Base64.DEFAULT));
            }
            startShare(f, mime, name);
        } catch (Exception e) {
            toast(getString(R.string.err_share_failed, e.getMessage()));
        }
    }

    private File shareCache(String name) {
        File dir = new File(getCacheDir(), "share");
        dir.mkdirs();
        File[] old = dir.listFiles();
        if (old != null) for (File o : old) o.delete();  // only the latest shared file is kept
        return new File(dir, name.replaceAll("[\\\\/:*?\"<>|]", "_"));
    }

    private void startShare(File f, String mime, String name) {
        if (mime == null || mime.isEmpty() || mime.equals("application/octet-stream")) {
            String ext = MimeTypeMap.getFileExtensionFromUrl(name.replace(' ', '_'));
            String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.toLowerCase(Locale.ROOT));
            mime = m != null ? m : "application/octet-stream";
        }
        Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".files", f);
        Intent send = new Intent(Intent.ACTION_SEND)
                .setType(mime)
                .putExtra(Intent.EXTRA_STREAM, uri)
                .putExtra(Intent.EXTRA_SUBJECT, name)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(Intent.createChooser(send, getString(R.string.share_title, name)));
        } catch (ActivityNotFoundException e) {
            toast(getString(R.string.err_no_share_app));
        }
    }

    private Uri write(InputStream in, String name, String mime) throws Exception {
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.MIME_TYPE, mime);
            v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/LAB ERP");
            v.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri == null) throw new Exception(getString(R.string.err_file_create));
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
            toast(getString(R.string.err_no_app_for_file));
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
        if (manual) toast(getString(R.string.toast_checking_update));
        new Thread(() -> {
            try {
                String body = Discovery.get(RELEASES, 6000);
                if (body == null) throw new Exception(getString(R.string.err_server_unreachable));
                JSONObject rel = new JSONObject(body);
                String latest = rel.optString("tag_name", "").replaceFirst("^v", "");
                String apk = pickApk(rel.optJSONArray("assets"));
                String page = apk != null ? apk : rel.optString("html_url", "");
                if (newer(latest, BuildConfig.VERSION_NAME) && !page.isEmpty()) {
                    ui.post(() -> new AlertDialog.Builder(this)
                            .setTitle(R.string.update_dialog_title)
                            .setMessage(getString(R.string.update_dialog_msg, latest, BuildConfig.VERSION_NAME))
                            .setPositiveButton(R.string.btn_download, (d, w) -> openExternal(page))
                            .setNegativeButton(R.string.btn_later, null)
                            .show());
                } else if (manual) {
                    ui.post(() -> toast(getString(R.string.toast_app_up_to_date, BuildConfig.VERSION_NAME)));
                }
            } catch (Exception e) {
                if (manual) ui.post(() -> toast(getString(R.string.toast_update_check_failed)));
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
            toast(getString(R.string.err_open_link_failed));
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
                boolean bare = !url.trim().matches("(?i)^https?://.*");
                JSONObject r = null;
                // The server listens on 8000, while an address without a port means 80
                if (!base.isEmpty() && Uri.parse(base).getPort() < 0) {
                    r = Discovery.check(base + ":8000", 3000);
                    if (r == null && bare) r = Discovery.check("https" + base.substring(4) + ":8000", 3000);
                }
                if (r == null && !base.isEmpty()) r = Discovery.check(base, 3000);
                if (r == null && !base.isEmpty() && bare) r = Discovery.check("https" + base.substring(4), 3000);
                JSONObject found = r;
                callback(cb, found == null ? "null" : found.toString());
            }).start();
        }

        @JavascriptInterface
        public void connect(String url) {
            if (!setupPage()) return;
            String base = normalize(url);
            if (base.isEmpty()) return;
            if (downgrade(base)) {
                ui.post(() -> showSetup("error=" + enc(getString(R.string.setup_error_https_required))));
                return;
            }
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
                startAlerts();
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
                android.content.SharedPreferences.Editor edit = prefs.edit().putString("recent", recent.toString()).remove("pin:" + url);
                if (url.equals(server())) edit.remove("server");
                edit.apply();
                ui.post(() -> {
                    web.clearSslPreferences();
                    CookieManager.getInstance().removeAllCookies(null);   // the session of that server goes with it
                });
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
        public void share(String url, String filename, String token) {
            if (server().isEmpty() || !pageOrigin.equals(server()) || !originOf(url).equals(server())) return;
            ui.post(() -> shareFile(url, filename, token));
        }

        @JavascriptInterface
        public void shareData(String base64, String filename, String mime) {
            if (!trusted()) return;
            ui.post(() -> MainActivity.this.shareData(base64, filename, mime));
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
        public void print() {
            if (!trusted()) return;
            ui.post(() -> {
                PrintManager pm = (PrintManager) getSystemService(PRINT_SERVICE);
                pm.print("LAB ERP", web.createPrintDocumentAdapter("LAB ERP"), null);
            });
        }

        @JavascriptInterface
        public void setTheme(String bg, boolean dark) {
            if (!trusted()) return;
            ui.post(() -> applyTheme(bg, dark));
        }
    }
}
