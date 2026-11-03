package com.erdevirlabs.parcatakip;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Finds ERP servers on the local network, like the desktop client (backend/app/services/discovery.py):
 * a UDP broadcast that native servers answer, then a /24 probe of /api/health for Docker servers.
 */
final class Discovery {
    static final int PORT = 47811;
    static final byte[] MAGIC = "PARCA_TAKIP_ERP_DISCOVER".getBytes(StandardCharsets.US_ASCII);
    static final int[] HTTP_PORTS = {8000, 80, 8080};

    private Discovery() {}

    /** Blocking; returns a JSON array of {url, name, version}. */
    static JSONArray find() {
        Map<String, JSONObject> found = Collections.synchronizedMap(new LinkedHashMap<>());
        List<InterfaceAddress> nets = localNets();
        broadcast(nets, found);
        if (found.isEmpty()) probe(nets, found);
        JSONArray out = new JSONArray();
        for (JSONObject o : found.values()) out.put(o);
        return out;
    }

    private static List<InterfaceAddress> localNets() {
        List<InterfaceAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress a = ia.getAddress();
                    if (a instanceof Inet4Address && a.isSiteLocalAddress()) out.add(ia);
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    private static void broadcast(List<InterfaceAddress> nets, Map<String, JSONObject> found) {
        try (DatagramSocket s = new DatagramSocket()) {
            s.setBroadcast(true);
            s.setSoTimeout(400);
            List<InetAddress> targets = new ArrayList<>();
            targets.add(InetAddress.getByName("255.255.255.255"));
            for (InterfaceAddress ia : nets) if (ia.getBroadcast() != null) targets.add(ia.getBroadcast());
            for (InetAddress t : targets) {
                try {
                    s.send(new DatagramPacket(MAGIC, MAGIC.length, t, PORT));
                } catch (Exception ignored) {
                }
            }
            long end = System.currentTimeMillis() + 1500;
            byte[] buf = new byte[1024];
            while (System.currentTimeMillis() < end) {
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                try {
                    s.receive(p);
                } catch (SocketTimeoutException e) {
                    continue;
                }
                try {
                    JSONObject r = new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8));
                    int port = r.optInt("port", 8000);
                    String url = "http://" + p.getAddress().getHostAddress() + (port == 80 ? "" : ":" + port);
                    found.put(url, new JSONObject()
                            .put("url", url)
                            .put("name", r.optString("name", ""))
                            .put("version", r.optString("version", "")));
                } catch (Exception ignored) {
                }
            }
        } catch (Exception ignored) {
        }
    }

    private static void probe(List<InterfaceAddress> nets, Map<String, JSONObject> found) {
        ExecutorService pool = Executors.newFixedThreadPool(48);
        for (InterfaceAddress ia : nets) {
            byte[] b = ia.getAddress().getAddress();
            for (int host = 1; host < 255; host++) {
                final String ip = (b[0] & 255) + "." + (b[1] & 255) + "." + (b[2] & 255) + "." + host;
                for (int port : HTTP_PORTS) {
                    final String url = "http://" + ip + (port == 80 ? "" : ":" + port);
                    pool.execute(() -> {
                        JSONObject info = check(url, 350);
                        if (info != null) found.put(url, info);
                    });
                }
            }
        }
        pool.shutdown();
        try {
            pool.awaitTermination(20, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
        }
        pool.shutdownNow();
    }

    /** {url, name, version} when `base` is an ERP server, else null. */
    static JSONObject check(String base, int timeoutMs) {
        try {
            String health = get(base + "/api/health", timeoutMs);
            if (health == null || !health.contains("\"ok\"")) return null;
            JSONObject out = new JSONObject().put("url", base).put("name", new URL(base).getHost()).put("version", "");
            String v = get(base + "/api/version", Math.max(timeoutMs, 1500));
            if (v != null) out.put("version", new JSONObject(v).optString("version", ""));
            return out;
        } catch (Exception e) {
            return null;
        }
    }

    static String get(String url, int timeoutMs) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(Math.max(timeoutMs, 3000));
            c.setRequestProperty("Accept", "application/json");
            c.setRequestProperty("User-Agent", "ParcaTakipERP-Android");
            if (c.getResponseCode() != 200) return null;
            try (InputStream in = c.getInputStream()) {
                ByteArrayOutputStream bo = new ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0 && bo.size() < 1 << 20) bo.write(buf, 0, n);
                return bo.toString("UTF-8");
            }
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }
}
