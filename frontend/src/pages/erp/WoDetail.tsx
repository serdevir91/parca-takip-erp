import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { saveRev } from "../../api/conflict";
import { useAuth } from "../../api/auth";
import LabelsModal from "../../components/Labels";
import { errText, useToast } from "../../components/Toast";
import { statusStyle } from "../../theme/theme";
import { Loading, Modal, fmtDate } from "../admin/shared";
import { OP_COLORS, WO_COLORS, fmtDay, fmtQty, numOrNull, type StockItem, type WoMaterial, type WoOp, type WorkOrder } from "./common";
import { tx } from "../../api/i18n";

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["work-orders", "requirements", "costs", "stock", "stock-moves", "parts"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** İş emri detayı: malzemeler and operasyonlar. Changes are open only while the order is open; the server enforces it. */
export default function WoDetail({ wo, onClose }: { wo: WorkOrder; onClose: () => void }) {
  const canEdit = useAuth().can("workorders", "edit");
  const [labels, setLabels] = useState(false);
  const writable = canEdit && (wo.status === "planned" || wo.status === "in_progress");
  if (labels) {
    return <LabelsModal labels={[{ payload: `WO:${wo.no}`, title: wo.no, sub: [wo.part_no, wo.description].filter(Boolean).join(" · ") }]} onClose={() => setLabels(false)} />;
  }
  return (
    <Modal wide title={tx("İş emri {0}", wo.no)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={() => setLabels(true)}>{tx("QR etiket")}</button>
        <button className="btn" onClick={onClose}>{tx("Kapat")}</button>
      </>}>
      <div className="erp-head">
        <div><span className="muted">{tx("Parça")}</span><b className="mono">{wo.part_no}</b></div>
        <div><span className="muted">{tx("Açıklama")}</span>{wo.description || "-"}</div>
        <div><span className="muted">{tx("Proje")}</span>{wo.project_name ?? tx("Stok için")}</div>
        <div><span className="muted">{tx("Durum")}</span><span className="badge" style={statusStyle(WO_COLORS[wo.status])}>{wo.status_label}</span></div>
        <div><span className="muted">{tx("Üretilen")}</span>{fmtQty(wo.done_qty)} / {fmtQty(wo.qty)}</div>
        <div><span className="muted">{tx("Termin")}</span>{fmtDay(wo.due_date) || "-"}</div>
      </div>
      <Materials wo={wo} writable={writable} />
      <Ops wo={wo} writable={writable} />
    </Modal>
  );
}

type MatDraft = { id?: number; code: string; description: string; unit: string; planned_qty: string; issued_qty: number };

function Materials({ wo, writable }: { wo: WorkOrder; writable: boolean }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [draft, setDraft] = useState<MatDraft[] | null>(null);
  const [qty, setQty] = useState<Record<number, string>>({});
  const q = useQuery({ queryKey: ["work-orders", "materials", wo.id], queryFn: () => api.get<WoMaterial[]>(`/work-orders/${wo.id}/materials`) });
  const save = useMutation({
    mutationFn: () => saveRev(wo.rev, (rev) => api.put(`/work-orders/${wo.id}/materials`, {
      rev,
      rows: (draft ?? []).map((r) => ({ id: r.id ?? null, code: r.code, description: r.description, unit: r.unit, planned_qty: numOrNull(r.planned_qty) ?? 0 })),
    })),
    onSuccess: () => { toast(tx("Malzeme listesi kaydedildi")); setDraft(null); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const act = useMutation({
    mutationFn: ({ m, verb }: { m: WoMaterial; verb: "issue" | "return" }) =>
      api.post(`/work-orders/${wo.id}/materials/${m.id}/${verb}`, { qty: numOrNull(qty[m.id] ?? "") ?? 0 }),
    onSuccess: (_, { m, verb }) => { toast(tx("{0}: {1} işlendi", m.code, verb === "issue" ? tx("çıkış") : "iade")); setQty((s) => ({ ...s, [m.id]: "" })); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const rows = q.data ?? [];
  const edit = (i: number, patch: Partial<MatDraft>) => setDraft((d) => (d ?? []).map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <section className="wo-section">
      <div className="row">
        <h4>{tx("Malzemeler")}</h4>
        {writable && !draft && (
          <button className="btn small" onClick={() => setDraft(rows.map((m) => ({ ...m, planned_qty: String(m.planned_qty) })))}>{tx("Listeyi düzenle")}</button>
        )}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {draft ? (
        <>
          <MaterialCodes />
          <div className="adm-scroll">
            <table className="simple erp-table erp-lines">
              <thead><tr><th>{tx("Kod")}</th><th>{tx("Açıklama")}</th><th>{tx("Birim")}</th><th className="num">{tx("Planlanan")}</th><th></th></tr></thead>
              <tbody>
                {draft.map((r, i) => (
                  <tr key={r.id ?? `new-${i}`}>
                    <td><input list="wo-material-codes" value={r.code} disabled={r.issued_qty > 0} aria-label={tx("Malzeme kodu")} onChange={(e) => edit(i, { code: e.target.value })} /></td>
                    <td><input value={r.description} aria-label={tx("Açıklama")} onChange={(e) => edit(i, { description: e.target.value })} /></td>
                    <td><input value={r.unit} style={{ width: 60 }} aria-label={tx("Birim")} onChange={(e) => edit(i, { unit: e.target.value })} /></td>
                    <td><input className="wo-qty" inputMode="decimal" value={r.planned_qty} aria-label={tx("Planlanan miktar")} onChange={(e) => edit(i, { planned_qty: e.target.value })} /></td>
                    <td><button className="btn small" disabled={r.issued_qty > 0} title={r.issued_qty > 0 ? tx("Önce iade edin") : undefined}
                      onClick={() => setDraft((d) => (d ?? []).filter((_, j) => j !== i))}>{tx("Sil")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn small" onClick={() => setDraft((d) => [...(d ?? []), { code: "", description: "", unit: "", planned_qty: "1", issued_qty: 0 }])}>{tx("+ Satır")}</button>
            <span style={{ flex: 1 }} />
            <button className="btn small" onClick={() => setDraft(null)}>{tx("Vazgeç")}</button>
            <button className="btn small primary" disabled={save.isPending || draft.some((r) => !r.code.trim() || !numOrNull(r.planned_qty))} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
          </div>
        </>
      ) : q.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead>
              <tr><th>{tx("Kod")}</th><th>{tx("Açıklama")}</th><th className="num">{tx("Planlanan")}</th><th className="num">{tx("Çıkılan")}</th><th className="num">{tx("Stok")}</th>{writable && <th></th>}</tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const n = numOrNull(qty[m.id] ?? "");
                return (
                  <tr key={m.id}>
                    <td className="mono">{m.code}</td>
                    <td>{m.description}{!m.has_card && <span className="badge warn" style={{ marginLeft: 4 }}>{tx("stok kartı yok")}</span>}</td>
                    <td className="num">{fmtQty(m.planned_qty)} {tx(m.unit)}</td>
                    <td className="num">{fmtQty(m.issued_qty)}</td>
                    <td className="num">{fmtQty(m.stock_qty)}</td>
                    {writable && (
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                          <input className="wo-qty" inputMode="decimal" placeholder={fmtQty(m.remaining)} aria-label={`${m.code} miktar`} value={qty[m.id] ?? ""}
                            onChange={(e) => setQty((s) => ({ ...s, [m.id]: e.target.value }))} />
                          <button className="btn small primary" disabled={act.isPending || !n} onClick={() => act.mutate({ m, verb: "issue" })}>{tx("Çıkış")}</button>
                          <button className="btn small" disabled={act.isPending || !n || !m.issued_qty} onClick={() => act.mutate({ m, verb: "return" })}>{tx("İade")}</button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan={6} className="muted">{tx("Malzeme eklenmemiş.")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ margin: "6px 0 0" }}>{tx("Üretim girişinde kalan malzeme üretilen miktar oranında stoktan kendiliğinden çıkılır.")}</p>
    </section>
  );
}

/** Code suggestions for users who may see stock; anyone else types the code. */
function MaterialCodes() {
  const { can } = useAuth();
  const q = useQuery({
    queryKey: ["stock", "picker"], enabled: can("stock"), staleTime: 60_000,
    queryFn: () => api.get<{ rows: StockItem[] }>("/stock"),
  });
  return <datalist id="wo-material-codes">{(q.data?.rows ?? []).map((i) => <option key={i.id} value={i.code}>{i.name}</option>)}</datalist>;
}

type OpDraft = { id?: number; name: string; planned_hours: string; note: string; status: string };

function Ops({ wo, writable }: { wo: WorkOrder; writable: boolean }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [draft, setDraft] = useState<OpDraft[] | null>(null);
  const q = useQuery({ queryKey: ["work-orders", "ops", wo.id], queryFn: () => api.get<WoOp[]>(`/work-orders/${wo.id}/ops`) });
  const save = useMutation({
    mutationFn: () => saveRev(wo.rev, (rev) => api.put(`/work-orders/${wo.id}/ops`, {
      rev,
      rows: (draft ?? []).map((r) => ({ id: r.id ?? null, name: r.name, planned_hours: numOrNull(r.planned_hours), note: r.note })),
    })),
    onSuccess: () => { toast(tx("Operasyonlar kaydedildi")); setDraft(null); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const setSt = useMutation({
    mutationFn: ({ o, s }: { o: WoOp; s: string }) => api.post(`/work-orders/${wo.id}/ops/${o.id}/status`, { status: s }),
    onSuccess: refresh,
    onError: (e) => toast(errText(e), true),
  });
  const rows = q.data ?? [];
  const edit = (i: number, patch: Partial<OpDraft>) => setDraft((d) => (d ?? []).map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const swap = (i: number, j: number) => setDraft((d) => {
    const n = [...(d ?? [])];
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });
  return (
    <section className="wo-section">
      <div className="row">
        <h4>{tx("Operasyonlar")}{rows.length ? ` (${rows.filter((o) => o.status === "done").length}/${rows.length})` : ""}</h4>
        {writable && !draft && (
          <button className="btn small" onClick={() => setDraft(rows.map((o) => ({ ...o, planned_hours: o.planned_hours == null ? "" : String(o.planned_hours) })))}>{tx("Rotayı düzenle")}</button>
        )}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {draft ? (
        <>
          <div className="adm-scroll">
            <table className="simple erp-table erp-lines">
              <thead><tr><th>#</th><th>{tx("Operasyon")}</th><th className="num">{tx("Saat")}</th><th>{tx("Not")}</th><th></th></tr></thead>
              <tbody>
                {draft.map((r, i) => (
                  <tr key={r.id ?? `new-${i}`}>
                    <td>{i + 1}</td>
                    <td><input value={r.name} aria-label={tx("Operasyon adı")} onChange={(e) => edit(i, { name: e.target.value })} /></td>
                    <td><input className="wo-qty" inputMode="decimal" value={r.planned_hours} aria-label={tx("Planlanan saat")} onChange={(e) => edit(i, { planned_hours: e.target.value })} /></td>
                    <td><input value={r.note} aria-label={tx("Not")} onChange={(e) => edit(i, { note: e.target.value })} /></td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <button className="btn small" disabled={i === 0} aria-label={tx("Yukarı")} onClick={() => swap(i, i - 1)}>↑</button>
                        <button className="btn small" disabled={i === draft.length - 1} aria-label={tx("Aşağı")} onClick={() => swap(i, i + 1)}>↓</button>
                        <button className="btn small" disabled={r.status !== "pending"} title={r.status !== "pending" ? tx("Başlamış operasyon silinemez") : undefined}
                          onClick={() => setDraft((d) => (d ?? []).filter((_, j) => j !== i))}>{tx("Sil")}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn small" onClick={() => setDraft((d) => [...(d ?? []), { name: "", planned_hours: "", note: "", status: "pending" }])}>{tx("+ Satır")}</button>
            <span style={{ flex: 1 }} />
            <button className="btn small" onClick={() => setDraft(null)}>{tx("Vazgeç")}</button>
            <button className="btn small primary" disabled={save.isPending || draft.some((r) => !r.name.trim())} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
          </div>
        </>
      ) : q.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>#</th><th>{tx("Operasyon")}</th><th className="num">{tx("Saat")}</th><th>{tx("Durum")}</th><th>{tx("Tamamlayan")}</th>{writable && <th></th>}</tr></thead>
            <tbody>
              {rows.map((o, i) => (
                <tr key={o.id}>
                  <td>{i + 1}</td>
                  <td>{o.name}{o.note && <div className="muted">{o.note}</div>}</td>
                  <td className="num">{fmtQty(o.planned_hours)}</td>
                  <td><span className="badge" style={statusStyle(OP_COLORS[o.status])}>{o.status_label}</span></td>
                  <td>{o.done_by}{o.done_at && <span className="muted"> · {fmtDate(o.done_at)}</span>}</td>
                  {writable && (
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        {o.status === "pending" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "in_progress" })}>{tx("Başlat")}</button>}
                        {o.status !== "done" && <button className="btn small primary" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "done" })}>{tx("Bitir")}</button>}
                        {o.status !== "pending" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "pending" })}>{tx("Geri al")}</button>}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={6} className="muted">{tx("Operasyon eklenmemiş.")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
