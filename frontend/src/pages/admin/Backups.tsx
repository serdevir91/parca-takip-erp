import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Loading, fmtBytes, fmtDate, fmtNum } from "./shared";

type Backup = { name: string; size: number; created_at: string };
type BackupStatus = {
  backup_dir: string; keep_days: number; count: number; total_size: number; free_bytes: number | null;
  last: Backup | null; running: boolean; items: Backup[];
};
const QK = ["admin", "backups"];

export default function BackupsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const st = useQuery({
    queryKey: QK,
    queryFn: () => api.get<BackupStatus>("/admin/backups"),
    // Poll while a backup runs (e.g. the nightly one) so the list fills in by itself.
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  });
  const now = useMutation({
    mutationFn: () => api.post<Backup>("/admin/backups"),
    onSuccess: (b) => toast(`Yedek alındı: ${b.name} (${fmtBytes(b.size)})`),
    onError: (e) => toast(errText(e), true),
    onSettled: () => void qc.invalidateQueries({ queryKey: QK }),
  });
  const get = async (name: string) => {
    setBusy(name);
    try {
      await download(`/admin/backups/${encodeURIComponent(name)}`, name);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setBusy(null);
    }
  };

  const d = st.data;
  const running = now.isPending || !!d?.running;
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="btn primary" disabled={running} onClick={() => now.mutate()}>
          {running ? "Yedek alınıyor…" : "Şimdi yedekle"}
        </button>
        <button className="btn" disabled={st.isFetching} onClick={() => void st.refetch()}>Yenile</button>
      </div>
      <Loading error={st.error} loading={st.isLoading} />
      {d && (
        <>
          <div className="adm-stats">
            <div><span className="muted">Son yedek</span><b>{d.last ? fmtDate(d.last.created_at) : "Henüz yok"}</b></div>
            <div><span className="muted">Yedek sayısı</span><b>{fmtNum(d.count)}</b></div>
            <div><span className="muted">Toplam boyut</span><b>{fmtBytes(d.total_size)}</b></div>
            <div><span className="muted">Boş disk alanı</span><b>{d.free_bytes != null ? fmtBytes(d.free_bytes) : "—"}</b></div>
            <div><span className="muted">Saklama süresi</span><b>{fmtNum(d.keep_days)} gün</b></div>
          </div>
          <p className="muted">Yedek klasörü: <code>{d.backup_dir}</code></p>
          <div className="adm-scroll">
            <table className="simple">
              <thead><tr><th>Dosya</th><th>Tarih</th><th style={{ textAlign: "right" }}>Boyut</th><th></th></tr></thead>
              <tbody>
                {d.items.map((b) => (
                  <tr key={b.name}>
                    <td style={{ fontFamily: "ui-monospace, Consolas, monospace" }}>{b.name}</td>
                    <td>{fmtDate(b.created_at)}</td>
                    <td style={{ textAlign: "right" }}>{fmtBytes(b.size)}</td>
                    <td>
                      <button className="btn small" disabled={busy === b.name} onClick={() => void get(b.name)}>
                        {busy === b.name ? "İndiriliyor…" : "İndir"}
                      </button>
                    </td>
                  </tr>
                ))}
                {!d.items.length && <tr><td colSpan={4} className="muted">Yedek yok.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ marginTop: 10 }}>
            Her yedek veritabanını ve yüklenen dosyaları (BOM, teknik resimler) içerir. {fmtNum(d.keep_days)} günden eski yedekler otomatik silinir; en yeni yedek her zaman korunur.
          </p>
        </>
      )}
    </div>
  );
}
