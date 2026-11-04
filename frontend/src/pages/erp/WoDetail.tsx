import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../api/auth";
import LabelsModal from "../../components/Labels";
import { errText, useToast } from "../../components/Toast";
import { statusStyle } from "../../theme/theme";
import { Loading, Modal, fmtDate } from "../admin/shared";
import { OP_COLORS, WO_COLORS, fmtDay, fmtQty, numOrNull, type StockItem, type WoMaterial, type WoOp, type WorkOrder } from "./common";

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
    <Modal wide title={`İş emri ${wo.no}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={() => setLabels(true)}>QR etiket</button>
        <button className="btn" onClick={onClose}>Kapat</button>
      </>}>
      <div className="erp-head">
        <div><span className="muted">Parça</span><b className="mono">{wo.part_no}</b></div>
        <div><span className="muted">Açıklama</span>{wo.description || "-"}</div>
        <div><span className="muted">Proje</span>{wo.project_name ?? "Stok için"}</div>
        <div><span className="muted">Durum</span><span className="badge" style={statusStyle(WO_COLORS[wo.status])}>{wo.status_label}</span></div>
        <div><span className="muted">Üretilen</span>{fmtQty(wo.done_qty)} / {fmtQty(wo.qty)}</div>
        <div><span className="muted">Termin</span>{fmtDay(wo.due_date) || "-"}</div>
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
    mutationFn: () => api.put(`/work-orders/${wo.id}/materials`, {
      rows: (draft ?? []).map((r) => ({ id: r.id ?? null, code: r.code, description: r.description, unit: r.unit, planned_qty: numOrNull(r.planned_qty) ?? 0 })),
    }),
    onSuccess: () => { toast("Malzeme listesi kaydedildi"); setDraft(null); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const act = useMutation({
    mutationFn: ({ m, verb }: { m: WoMaterial; verb: "issue" | "return" }) =>
      api.post(`/work-orders/${wo.id}/materials/${m.id}/${verb}`, { qty: numOrNull(qty[m.id] ?? "") ?? 0 }),
    onSuccess: (_, { m, verb }) => { toast(`${m.code}: ${verb === "issue" ? "çıkış" : "iade"} işlendi`); setQty((s) => ({ ...s, [m.id]: "" })); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const rows = q.data ?? [];
  const edit = (i: number, patch: Partial<MatDraft>) => setDraft((d) => (d ?? []).map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <section className="wo-section">
      <div className="row">
        <h4>Malzemeler</h4>
        {writable && !draft && (
          <button className="btn small" onClick={() => setDraft(rows.map((m) => ({ ...m, planned_qty: String(m.planned_qty) })))}>Listeyi düzenle</button>
        )}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {draft ? (
        <>
          <MaterialCodes />
          <div className="adm-scroll">
            <table className="simple erp-table erp-lines">
              <thead><tr><th>Kod</th><th>Açıklama</th><th>Birim</th><th className="num">Planlanan</th><th></th></tr></thead>
              <tbody>
                {draft.map((r, i) => (
                  <tr key={r.id ?? `new-${i}`}>
                    <td><input list="wo-material-codes" value={r.code} disabled={r.issued_qty > 0} aria-label="Malzeme kodu" onChange={(e) => edit(i, { code: e.target.value })} /></td>
                    <td><input value={r.description} aria-label="Açıklama" onChange={(e) => edit(i, { description: e.target.value })} /></td>
                    <td><input value={r.unit} style={{ width: 60 }} aria-label="Birim" onChange={(e) => edit(i, { unit: e.target.value })} /></td>
                    <td><input className="wo-qty" inputMode="decimal" value={r.planned_qty} aria-label="Planlanan miktar" onChange={(e) => edit(i, { planned_qty: e.target.value })} /></td>
                    <td><button className="btn small" disabled={r.issued_qty > 0} title={r.issued_qty > 0 ? "Önce iade edin" : undefined}
                      onClick={() => setDraft((d) => (d ?? []).filter((_, j) => j !== i))}>Sil</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn small" onClick={() => setDraft((d) => [...(d ?? []), { code: "", description: "", unit: "", planned_qty: "1", issued_qty: 0 }])}>+ Satır</button>
            <span style={{ flex: 1 }} />
            <button className="btn small" onClick={() => setDraft(null)}>Vazgeç</button>
            <button className="btn small primary" disabled={save.isPending || draft.some((r) => !r.code.trim() || !numOrNull(r.planned_qty))} onClick={() => save.mutate()}>Kaydet</button>
          </div>
        </>
      ) : q.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead>
              <tr><th>Kod</th><th>Açıklama</th><th className="num">Planlanan</th><th className="num">Çıkılan</th><th className="num">Stok</th>{writable && <th></th>}</tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const n = numOrNull(qty[m.id] ?? "");
                return (
                  <tr key={m.id}>
                    <td className="mono">{m.code}</td>
                    <td>{m.description}{!m.has_card && <span className="badge warn" style={{ marginLeft: 4 }}>stok kartı yok</span>}</td>
                    <td className="num">{fmtQty(m.planned_qty)} {m.unit}</td>
                    <td className="num">{fmtQty(m.issued_qty)}</td>
                    <td className="num">{fmtQty(m.stock_qty)}</td>
                    {writable && (
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                          <input className="wo-qty" inputMode="decimal" placeholder={fmtQty(m.remaining)} aria-label={`${m.code} miktar`} value={qty[m.id] ?? ""}
                            onChange={(e) => setQty((s) => ({ ...s, [m.id]: e.target.value }))} />
                          <button className="btn small primary" disabled={act.isPending || !n} onClick={() => act.mutate({ m, verb: "issue" })}>Çıkış</button>
                          <button className="btn small" disabled={act.isPending || !n || !m.issued_qty} onClick={() => act.mutate({ m, verb: "return" })}>İade</button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan={6} className="muted">Malzeme eklenmemiş.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ margin: "6px 0 0" }}>Üretim girişinde kalan malzeme üretilen miktar oranında stoktan kendiliğinden çıkılır.</p>
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
    mutationFn: () => api.put(`/work-orders/${wo.id}/ops`, {
      rows: (draft ?? []).map((r) => ({ id: r.id ?? null, name: r.name, planned_hours: numOrNull(r.planned_hours), note: r.note })),
    }),
    onSuccess: () => { toast("Operasyonlar kaydedildi"); setDraft(null); refresh(); },
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
        <h4>Operasyonlar{rows.length ? ` (${rows.filter((o) => o.status === "done").length}/${rows.length})` : ""}</h4>
        {writable && !draft && (
          <button className="btn small" onClick={() => setDraft(rows.map((o) => ({ ...o, planned_hours: o.planned_hours == null ? "" : String(o.planned_hours) })))}>Rotayı düzenle</button>
        )}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {draft ? (
        <>
          <div className="adm-scroll">
            <table className="simple erp-table erp-lines">
              <thead><tr><th>#</th><th>Operasyon</th><th className="num">Saat</th><th>Not</th><th></th></tr></thead>
              <tbody>
                {draft.map((r, i) => (
                  <tr key={r.id ?? `new-${i}`}>
                    <td>{i + 1}</td>
                    <td><input value={r.name} aria-label="Operasyon adı" onChange={(e) => edit(i, { name: e.target.value })} /></td>
                    <td><input className="wo-qty" inputMode="decimal" value={r.planned_hours} aria-label="Planlanan saat" onChange={(e) => edit(i, { planned_hours: e.target.value })} /></td>
                    <td><input value={r.note} aria-label="Not" onChange={(e) => edit(i, { note: e.target.value })} /></td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <button className="btn small" disabled={i === 0} aria-label="Yukarı" onClick={() => swap(i, i - 1)}>↑</button>
                        <button className="btn small" disabled={i === draft.length - 1} aria-label="Aşağı" onClick={() => swap(i, i + 1)}>↓</button>
                        <button className="btn small" disabled={r.status !== "pending"} title={r.status !== "pending" ? "Başlamış operasyon silinemez" : undefined}
                          onClick={() => setDraft((d) => (d ?? []).filter((_, j) => j !== i))}>Sil</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn small" onClick={() => setDraft((d) => [...(d ?? []), { name: "", planned_hours: "", note: "", status: "pending" }])}>+ Satır</button>
            <span style={{ flex: 1 }} />
            <button className="btn small" onClick={() => setDraft(null)}>Vazgeç</button>
            <button className="btn small primary" disabled={save.isPending || draft.some((r) => !r.name.trim())} onClick={() => save.mutate()}>Kaydet</button>
          </div>
        </>
      ) : q.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>#</th><th>Operasyon</th><th className="num">Saat</th><th>Durum</th><th>Tamamlayan</th>{writable && <th></th>}</tr></thead>
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
                        {o.status === "pending" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "in_progress" })}>Başlat</button>}
                        {o.status !== "done" && <button className="btn small primary" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "done" })}>Bitir</button>}
                        {o.status !== "pending" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ o, s: "pending" })}>Geri al</button>}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={6} className="muted">Operasyon eklenmemiş.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
