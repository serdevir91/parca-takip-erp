import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { copyText } from "../api/clipboard";
import { tx } from "../api/i18n";
import { errText, useToast } from "./Toast";

type Connection = { ips: string[]; hostname: string };

/** The address another computer or phone types to reach this server. */
export default function ServerAddress() {
  const toast = useToast();
  const q = useQuery({ queryKey: ["connection"], queryFn: () => api.get<Connection>("/connection") });
  const { protocol, hostname, port, origin } = window.location;
  const url = (host: string) => `${protocol}//${host}${port ? `:${port}` : ""}`;
  const opened = /^(localhost$|127\.|\[::1\])/.test(hostname) ? [] : [origin];
  const list = [...new Set([...opened, ...(q.data?.ips ?? []).map(url), ...(q.data?.hostname ? [url(q.data.hostname)] : [])])];
  const copy = (text: string) => copyText(text).then(() => toast(tx("Adres kopyalandı"))).catch((e) => toast(errText(e), true));

  return (
    <div className="server-address">
      <h3>{tx("Sunucu adresi")}</h3>
      <p className="muted">{tx("Diğer bilgisayar ve telefonlarda sunucu adresi sorulunca bunu yazın. Cihazlar aynı ağda olmalı. Birden çok adres varsa önce ilkini deneyin.")}</p>
      {list.map((a) => (
        <div className="row" key={a}>
          <code>{a}</code>
          <button type="button" className="btn small" onClick={() => copy(a)}>{tx("Kopyala")}</button>
        </div>
      ))}
      {!list.length && !q.isLoading && <p className="muted">{tx("Adres bulunamadı. Sunucu bilgisayarının ağ bağlantısını kontrol edin.")}</p>}
    </div>
  );
}
