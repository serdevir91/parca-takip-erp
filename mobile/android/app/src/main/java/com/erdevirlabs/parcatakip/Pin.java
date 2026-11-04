package com.erdevirlabs.parcatakip;

import android.net.http.SslCertificate;
import android.os.Build;
import android.os.Bundle;

import java.net.HttpURLConnection;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * A LAB ERP server on a LAN uses a certificate it made itself, which no authority vouches for. The app remembers
 * that certificate's fingerprint on first contact (the user compares it with the one in Yönetim > HTTPS) and
 * trusts only that one for this server from then on.
 */
final class Pin {
    private Pin() {
    }

    static String fingerprint(byte[] der) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(der)) out.append(String.format("%02x", b));
        return out.toString();
    }

    static String fingerprint(SslCertificate cert) throws Exception {
        if (Build.VERSION.SDK_INT >= 29) return fingerprint(cert.getX509Certificate().getEncoded());
        Bundle state = SslCertificate.saveState(cert);
        return fingerprint(state.getByteArray("x509-certificate"));
    }

    static String pretty(String fingerprint) {
        return fingerprint.replaceAll("(.{4})(?!$)", "$1 ");
    }

    /** expected null accepts any certificate: only for "is a server there", never with a token. */
    static void apply(HttpURLConnection c, String expected) throws Exception {
        if (!(c instanceof HttpsURLConnection)) return;
        X509TrustManager tm = new X509TrustManager() {
            @Override
            public void checkClientTrusted(X509Certificate[] chain, String authType) {
            }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                if (expected == null) return;
                try {
                    if (expected.equals(fingerprint(chain[0].getEncoded()))) return;
                } catch (Exception e) {
                    throw new CertificateException(e);
                }
                throw new CertificateException("Sunucu sertifikası değişmiş");
            }

            @Override
            public X509Certificate[] getAcceptedIssuers() {
                return new X509Certificate[0];
            }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[]{tm}, null);
        HttpsURLConnection https = (HttpsURLConnection) c;
        https.setSSLSocketFactory(ctx.getSocketFactory());
        https.setHostnameVerifier((host, session) -> true);   // the address may change, the certificate may not
    }
}
