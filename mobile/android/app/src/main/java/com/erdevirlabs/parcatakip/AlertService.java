package com.erdevirlabs.parcatakip;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;
import android.webkit.CookieManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * System notifications without Google services: the app is sideloaded and the server sits on a LAN, so nothing can
 * push to the phone and the phone asks instead. The alarm in Poller wakes the device for a short request to
 * /api/notifications/feed; this foreground service is what keeps that alarm on time and the network open while
 * the phone sleeps. Doze can still stretch the interval to about ten minutes with the screen off.
 */
public class AlertService extends Service {
    private static final String CH_RUN = "run";
    private static final String CH_MESSAGES = "messages";
    private static final String CH_ITEMS = "items";
    private static final int ID_RUN = 1;
    private static final int ID_ITEMS_SUMMARY = 2;
    private static final int ID_ROOM = 1000;
    private static final int ID_ITEM = 100000;
    private static final int MAX_ITEMS = 3; // more than this in one poll becomes a single summary
    private static final int MAX_LINES = 6;
    private static final long INTERVAL_MS = 30_000;
    private static final int TIMEOUT_MS = 6000;

    /** Runs the service when there is a server to watch and notifications are allowed; stops it otherwise. */
    static void sync(Context c) {
        SharedPreferences prefs = c.getSharedPreferences("erp", MODE_PRIVATE);
        Intent service = new Intent(c, AlertService.class);
        boolean allowed = c.getSystemService(NotificationManager.class).areNotificationsEnabled();
        if (prefs.getString("server", "").isEmpty() || !allowed) {
            c.stopService(service);
            return;
        }
        c.startForegroundService(service);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CH_RUN, getString(R.string.notif_ch_run), NotificationManager.IMPORTANCE_MIN));
        nm.createNotificationChannel(new NotificationChannel(CH_MESSAGES, getString(R.string.notif_ch_messages), NotificationManager.IMPORTANCE_HIGH));
        nm.createNotificationChannel(new NotificationChannel(CH_ITEMS, getString(R.string.notif_ch_items), NotificationManager.IMPORTANCE_DEFAULT));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification running = new Notification.Builder(this, CH_RUN)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.notif_watching))
                .setContentIntent(open(this, 0, null))
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(ID_RUN, running, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(ID_RUN, running);
        schedule(this, 2000);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        getSystemService(AlarmManager.class).cancel(alarm(this));
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private static PendingIntent alarm(Context c) {
        return PendingIntent.getBroadcast(c, 0, new Intent(c, Poller.class).setAction(Poller.ACTION),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private static void schedule(Context c, long delayMs) {
        c.getSystemService(AlarmManager.class).setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + delayMs, alarm(c));
    }

    private static PendingIntent open(Context c, int code, String link) {
        Intent i = new Intent(c, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (link != null) i.putExtra(MainActivity.EXTRA_LINK, link);
        return PendingIntent.getActivity(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    private static void show(Context c, int id, String channel, String title, String text, String link) {
        Notification n = new Notification.Builder(c, channel)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(open(c, id, link))
                .setAutoCancel(true)
                .build();
        c.getSystemService(NotificationManager.class).notify(id, n);
    }

    private static JSONObject fetch(Context c, SharedPreferences prefs, String url, String cookie) throws Exception {
        HttpURLConnection http = MainActivity.open(c, prefs, url);
        try {
            http.setConnectTimeout(TIMEOUT_MS);
            http.setReadTimeout(TIMEOUT_MS);
            http.setRequestProperty("Cookie", cookie);
            http.setRequestProperty("X-Requested-With", "LabERP");
            if (http.getResponseCode() != 200) return null; // signed out or the server is being updated
            ByteArrayOutputStream body = new ByteArrayOutputStream();
            try (InputStream in = http.getInputStream()) {
                byte[] buf = new byte[8192];
                for (int n; (n = in.read(buf)) > 0; ) body.write(buf, 0, n);
            }
            return new JSONObject(new String(body.toByteArray(), StandardCharsets.UTF_8));
        } finally {
            http.disconnect();
        }
    }

    /** Asks the server what is new. A device remembers per server what it has announced; the first look stays silent. */
    private static void poll(Context c) throws Exception {
        SharedPreferences prefs = c.getSharedPreferences("erp", MODE_PRIVATE);
        String server = prefs.getString("server", "");
        if (server.isEmpty()) return;
        String url = server + "/api/notifications/feed";
        String cookie = CookieManager.getInstance().getCookie(url); // the session cookie's path is /api
        if (cookie == null) return;
        String afterKey = "feed_after:" + server;
        String seenKey = "feed_seen:" + server;
        JSONObject feed = fetch(c, prefs, url + "?after=" + prefs.getInt(afterKey, 0), cookie);
        if (feed == null) return;

        Set<String> seen = prefs.getStringSet(seenKey, null);
        JSONArray items = feed.getJSONArray("items");
        Set<String> keys = new HashSet<>();
        List<JSONObject> fresh = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject item = items.getJSONObject(i);
            keys.add(item.getString("key"));
            if (seen != null && !seen.contains(item.getString("key"))) fresh.add(item);
        }
        prefs.edit().putInt(afterKey, feed.getInt("last_id")).putStringSet(seenKey, keys).apply();
        if (MainActivity.onScreen) return; // the open app shows these itself

        Map<Integer, List<JSONObject>> rooms = new LinkedHashMap<>();
        JSONArray messages = feed.getJSONArray("messages");
        for (int i = 0; i < messages.length(); i++) {
            JSONObject m = messages.getJSONObject(i);
            List<JSONObject> room = rooms.get(m.getInt("room_id"));
            if (room == null) rooms.put(m.getInt("room_id"), room = new ArrayList<>());
            room.add(m);
        }
        for (Map.Entry<Integer, List<JSONObject>> room : rooms.entrySet()) {
            List<JSONObject> rows = room.getValue();
            StringBuilder text = new StringBuilder();
            for (JSONObject m : rows.subList(Math.max(0, rows.size() - MAX_LINES), rows.size())) {
                if (text.length() > 0) text.append('\n');
                text.append(m.getString("text"));
            }
            JSONObject last = rows.get(rows.size() - 1);
            show(c, ID_ROOM + room.getKey(), CH_MESSAGES, last.getString("title"), text.toString(), last.getString("link"));
        }
        if (fresh.size() > MAX_ITEMS) {
            show(c, ID_ITEMS_SUMMARY, CH_ITEMS, c.getString(R.string.app_name), c.getString(R.string.notif_items_summary, fresh.size()), "/");
            return;
        }
        for (JSONObject item : fresh) {
            int id = ID_ITEM + (item.getString("key").hashCode() & 0xffff);
            show(c, id, CH_ITEMS, item.getString("title"), item.getString("detail"), item.getString("link"));
        }
    }

    /** The alarm that drives the polling, and the restart after a reboot or an app update. */
    public static class Poller extends BroadcastReceiver {
        static final String ACTION = "com.erdevirlabs.parcatakip.POLL";

        @Override
        public void onReceive(Context context, Intent intent) {
            Context c = context.getApplicationContext();
            if (!ACTION.equals(intent.getAction())) {
                sync(c);
                return;
            }
            PendingResult pending = goAsync(); // AlarmManager holds the device awake until finish()
            new Thread(() -> {
                try {
                    poll(c);
                } catch (Exception e) { // no network or server away: the next round tries again
                    android.util.Log.d("AlertService", "poll failed", e);
                } finally {
                    schedule(c, INTERVAL_MS);
                    pending.finish();
                }
            }, "alert-poll").start();
        }
    }
}
