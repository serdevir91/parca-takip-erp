import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { desktopShell } from "../../api/desktop";
import { errText, useToast } from "../../components/Toast";
import { Loading } from "./shared";
import { tx } from "../../api/i18n";

type HttpsStatus = { enabled: boolean; active: boolean; fingerprint: string | null; supervised: boolean };
const QK = ["admin", "https"];

/** Same grouping as the Android and desktop dialogs, so the two can be compared at a glance. */
const pretty = (f: string) => f.replace(/(.{4})(?!$)/g, "$1 ");

export default function HttpsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [restarting, setRestarting] = useState(false);
  const st = useQuery({ queryKey: QK, queryFn: () => api.get<HttpsStatus>("/admin/https") });
  const set = useMutation({
    mutationFn: (enabled: boolean) => api.put<HttpsStatus>("/admin/https", { enabled }),
    onSuccess: (d) => qc.setQueryData(QK, d),
    onError: (e) => toast(errText(e), true),
  });

  const d = st.data;
  // The desktop app can only restart the server it runs itself, not one it connects to.
  const shell = desktopShell();
  const host = useQuery({ queryKey: ["desktop", "info"], queryFn: () => shell?.app_info() ?? null, enabled: !!shell });
  const ownServer = host.data?.mode === "server";
  const pending = !!d && d.enabled !== d.active;
  const behindProxy = !!d && d.active && !d.enabled;
  const canRestart = !!d && (d.supervised || ownServer);

  // The address changes with the scheme, so the page moves there once the server answers again.
  const target = () => {
    const u = new URL(window.location.href);
    u.protocol = d?.enabled ? "https:" : "http:";
    return u.href;
  };
  const restart = async () => {
    setRestarting(true);
    try {
      if (shell && ownServer) {
        const r = await shell.app_action("restart");
        if (!r.ok) throw new Error(r.error || tx("Sunucu yeniden başlatılamadı"));
        return;
      }
      await api.post("/admin/server/restart");
      toast(tx("Sunucu yeniden başlatılıyor…"));
      setTimeout(() => window.location.assign(target()), 6000);
    } catch (e) {
      setRestarting(false);
      toast(errText(e), true);
    }
  };

  return (
    <div className="card">
      <Loading error={st.error} loading={st.isLoading} />
      {d && (
        <>
          <div className="adm-stats">
            <div><span className="muted">{tx("Bu bağlantı")}</span><b>{d.active ? tx("Şifreli (HTTPS)") : tx("Şifresiz (HTTP)")}</b></div>
            <div><span className="muted">{tx("Sunucu ayarı")}</span><b>{d.enabled ? tx("HTTPS açık") : tx("HTTPS kapalı")}</b></div>
          </div>
          {behindProxy ? (
            <p className="muted">
              {tx("Bu bağlantı önündeki sunucu (ör. nginx) tarafından şifreleniyor. Sertifika orada yönetilir; bu ekrandan değiştirmeniz gerekmez.")}
            </p>
          ) : (
            <>
              <p className="muted">
                {tx("HTTPS açıkken veriler ve parolalar ağda şifreli gider. Sunucu kendi sertifikasını üretir; uygulamalar ilk bağlantıda bu parmak izini sorar ve sonra yalnızca ona güvenir.")}
              </p>
              <div className="row" style={{ marginBottom: 10 }}>
                <button className={d.enabled ? "btn" : "btn primary"} disabled={set.isPending || restarting} onClick={() => set.mutate(!d.enabled)}>
                  {d.enabled ? tx("HTTPS'i kapat") : tx("HTTPS'i aç")}
                </button>
                {d.fingerprint && <a className="btn" href="/api/tls/cert" download="lab-erp.crt">{tx("Sertifikayı indir")}</a>}
              </div>
            </>
          )}
          {d.fingerprint && !behindProxy && (
            <p>
              <span className="muted">{tx("Parmak izi (SHA-256)")}</span><br />
              <code style={{ wordBreak: "break-all" }}>{pretty(d.fingerprint)}</code>
            </p>
          )}
          {pending && !behindProxy && (
            <div className="row" style={{ marginTop: 10 }}>
              <span>{tx("Ayar sunucu yeniden başlayınca geçerli olur.")}</span>
              {canRestart && (
                <button className="btn primary" disabled={restarting} onClick={() => void restart()}>
                  {restarting ? tx("Yeniden başlatılıyor…") : tx("Sunucuyu yeniden başlat")}
                </button>
              )}
            </div>
          )}
          {pending && !behindProxy && !canRestart && (
            <p className="muted">{tx("Sunucu programını elle kapatıp açın. Docker kurulumunda HTTPS bu ekrandan değil, nginx ayarından yapılır.")}</p>
          )}
          {pending && !behindProxy && (
            <p className="muted">{tx("Sonra tüm cihazlar adresi")}{" "}{d.enabled ? "https://" : "http://"}{" "}{tx("ile kullanır. Tarayıcılar kendi üretilmiş sertifika için bir kez uyarı gösterir.")}</p>
          )}
        </>
      )}
    </div>
  );
}
