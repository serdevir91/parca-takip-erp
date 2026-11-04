import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, download } from "../api/client";
import { useAuth } from "../api/auth";
import { statusStyle } from "../theme/theme";
import Photos from "./Photos";
import { errText, useToast } from "./Toast";
import Thumb from "./viewer/Thumb";
import Viewer, { type ViewItem } from "./viewer/Viewer";

/** One row of GET /projects/{pid}/parts (flat or tree) or an archived tracking row. */
export type PartRow = {
  id: number | null;
  part_no: string;
  seq?: number; level?: string; depth?: number; parent_level?: string | null;
  file_name?: string; ext?: string; is_assembly?: boolean;
  qty?: number; multiplier?: number; total_qty?: number;
  material?: string; weight?: number | null; rev?: string;
  procurement_csv?: string; procurement?: string; procurement_override: string | null;
  coating?: string; parent_part_no?: string | null; main_group?: string; row_type?: string;
  in_purchased?: boolean; is_purchased_assembly?: boolean; nonstandard?: boolean; alias?: string | null;
  counted?: boolean; fastener?: boolean; fastener_desc?: string | null;
  progress: string; status?: string; status_color?: string; status_kind?: string | null;
  note: string; t35_note: string; manufacturer: string; material_status: string; is_new: boolean; hidden?: boolean; fastener_key?: string | null;
  updated_at: string | null; updated_by: string;
  has_drawing?: boolean; drawing_ids?: number[]; drawing_rev?: string; drawing_rev_mismatch?: boolean;
  levels?: string[]; main_groups?: string[]; row_ids?: number[]; rows?: number;
  archived?: boolean;
};

/** GET /projects/{pid}/parts/choices */
export type PartChoices = {
  row_types: string[]; temin_choices: string[]; progress_choices: string[]; manufacturers: string[]; suppliers: string[];
  material_status_choices: string[]; statuses: { status: string; color: string }[];
  colors: Record<string, string>;
};

/** Editable tracking fields (backend TrackingPatch) with Turkish labels. */
export const FIELD_LABELS: Record<string, string> = {
  procurement_override: "Temin Şekli", progress: "İlerleme", note: "Not", t35_note: "Durum Notu",
  manufacturer: "Üretici", material_status: "Malzeme Durumu", is_new: "Yeni etiketi",
  qty: "Adet", reason: "Neden", part_no: "Parça No",
};

type Drawing = { id: number; filename: string; ext: string; rev: string | null; match_via: string | null; current_version: number; updated_at: string | null };
type History = { id: number; ts: string | null; username: string; entity: string; entity_id: string; field: string | null; old: unknown; new: unknown; action: string };
type Missing = { id: number; part_no: string; qty: number; reason: string; progress: string; note: string; status: string; status_color: string; created_by: string; created_at: string | null };
type Occurrence = { id: number; level: string; parent_part_no: string | null; qty: number; multiplier: number; total_qty: number; main_group: string; in_purchased: boolean };
type Detail = {
  part: PartRow; tracking: PartRow | null; aliases: string[]; occurrences: Occurrence[]; used_in: string[];
  drawings: Drawing[]; drawing_info: { has_drawing: boolean; drawing_rev: string; drawing_rev_mismatch: boolean };
  missing: Missing[]; history: History[];
};

const INLINE = new Set(["pdf", "png", "jpg", "jpeg"]);
const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleString("tr-TR") : "");
const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? "" : n.toLocaleString("tr-TR"));
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "Evet" : "Hayır") : String(v));
const ACTIONS: Record<string, string> = { create: "Oluşturuldu", delete: "Silindi", update: "Değişti", import: "İçe aktarıldı" };

export const drawingItem = (d: { id: number; filename: string; ext: string; rev?: string | null }): ViewItem => ({
  key: d.id, name: d.filename, path: `/drawings/${d.id}/file`, thumb: `/drawings/${d.id}/thumb`,
  kind: (d.ext || "").toLowerCase() === "pdf" ? "pdf" : "image", caption: d.rev ? `Rev ${d.rev}` : undefined,
});

export default function PartDetail({ pid, partNo, onClose }: { pid: number; partNo: string; onClose: () => void }) {
  const canPhoto = useAuth().can("parts", "edit");
  const [viewing, setViewing] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["parts", pid, "detail", partNo],
    queryFn: () => api.get<Detail>(`/projects/${pid}/parts/${encodeURIComponent(partNo)}`),
  });

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && viewing === null && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, viewing]);

  const d = q.data;
  const viewable = (d?.drawings ?? []).filter((x) => INLINE.has((x.ext || "").toLowerCase()));
  const p = d?.part;
  return (
    <div className="drawer part-detail" role="dialog" aria-label={`Parça detayı ${partNo}`}>
      <div className="row" style={{ alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, wordBreak: "break-all" }}>{partNo}</h3>
        {p?.is_new && <span className="badge new">Yeni</span>}
        {p?.archived && <span className="badge warn">Arşivde</span>}
        <button className="btn small" style={{ marginLeft: "auto" }} onClick={onClose}>Kapat</button>
      </div>
      {q.isLoading && <div className="muted">Yükleniyor…</div>}
      {q.isError && <div className="error">{errText(q.error)}</div>}
      {d && p && (
        <>
          {p.status && <div style={{ ...statusStyle(p.status_color), padding: "6px 10px", borderRadius: 6, marginBottom: 10 }}>
            <b>{p.status}</b>{p.progress ? ` · ${p.progress}` : ""}</div>}

          <section>
            <h4>Bilgiler</h4>
            <table className="simple">
              <tbody>
                {([
                  ["Dosya adı", p.file_name], ["Tip", p.row_type], ["Seviye", p.levels?.join(", ") || p.level],
                  ["Ana grup", p.main_groups?.join(", ") || p.main_group], ["Üst montaj", p.parent_part_no],
                  ["Adet", fmtNum(p.qty)], ["Toplam adet", fmtNum(p.total_qty)], ["Malzeme", p.material],
                  ["Ağırlık", fmtNum(p.weight)], ["Kaplama", p.coating], ["Rev", p.rev],
                  ["Temin şekli", p.procurement ?? p.procurement_override],
                  ["Temin (BOM)", p.procurement_csv], ["İlerleme", p.progress], ["Üretici", p.manufacturer],
                  ["Malzeme durumu", p.material_status], ["Durum notu", p.t35_note], ["Not", p.note],
                  ["Diğer adlar (alias)", d.aliases.join(", ")],
                  ["Son güncelleme", p.updated_at ? `${fmtDate(p.updated_at)} · ${p.updated_by || ""}` : ""],
                ] as [string, unknown][]).map(([k, v]) => (
                  <tr key={k}><th style={{ width: 150 }}>{k}</th><td style={{ whiteSpace: "pre-wrap" }}>{show(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h4>Teknik resimler</h4>
            {d.drawing_info.drawing_rev_mismatch && (
              <div className="badge warn" style={{ marginBottom: 6 }}>Resim revizyonu ({d.drawing_info.drawing_rev}) BOM revizyonundan ({p.rev}) farklı</div>
            )}
            {d.drawings.length === 0 ? <div className="muted">Teknik resim yok.</div> : (
              <div className="part-drawings">
                {d.drawings.map((dr) => (
                  <DrawingCard key={dr.id} d={dr} onOpen={() => setViewing(viewable.findIndex((x) => x.id === dr.id))} />
                ))}
              </div>
            )}
          </section>

          <section>
            <h4>Fotoğraflar</h4>
            <Photos entity="part" entityKey={partNo} canEdit={canPhoto} />
          </section>

          <section>
            <h4>Kullanıldığı montajlar</h4>
            {d.occurrences.length === 0 ? <div className="muted">Mevcut BOM sürümünde yok.</div> : (
              <table className="simple">
                <thead><tr><th>Seviye</th><th>Üst montaj</th><th>Ana grup</th><th>Adet</th><th>Çarpan</th><th>Toplam</th></tr></thead>
                <tbody>
                  {d.occurrences.map((o) => (
                    <tr key={o.id} className={o.in_purchased ? "muted" : ""}>
                      <td>{o.level}</td><td>{show(o.parent_part_no)}{o.in_purchased ? " (satın alınan montaj içi)" : ""}</td>
                      <td>{show(o.main_group)}</td><td>{fmtNum(o.qty)}</td><td>{fmtNum(o.multiplier)}</td><td>{fmtNum(o.total_qty)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h4>Eksik satırları</h4>
            {d.missing.length === 0 ? <div className="muted">Eksik satırı yok.</div> : (
              <table className="simple">
                <thead><tr><th>Adet</th><th>Neden</th><th>Durum</th><th>Not</th><th>Açan</th></tr></thead>
                <tbody>
                  {d.missing.map((m) => (
                    <tr key={m.id}>
                      <td>{fmtNum(m.qty)}</td><td>{show(m.reason)}</td>
                      <td style={statusStyle(m.status_color)}>{m.status}</td><td>{show(m.note)}</td>
                      <td>{m.created_by} <span className="muted">{fmtDate(m.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h4>Durum geçmişi</h4>
            {d.history.length === 0 ? <div className="muted">Kayıt yok.</div> : (
              <ul className="part-history">
                {d.history.map((h) => (
                  <li key={h.id}>
                    <div className="muted">{fmtDate(h.ts)} · {h.username || "sistem"}{h.entity === "missing" ? " · eksik satırı" : ""}</div>
                    <div>
                      <b>{h.field ? FIELD_LABELS[h.field] ?? h.field : ACTIONS[h.action] ?? h.action}</b>
                      {h.field ? <>: {show(h.old)} <span className="muted">›</span> {show(h.new)}</> : null}
                      {h.field && h.action && h.action !== "update" ? <span className="muted"> ({ACTIONS[h.action] ?? h.action})</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
      {viewing !== null && viewing >= 0 && (
        <Viewer items={viewable.map(drawingItem)} start={viewing} onClose={() => setViewing(null)} />
      )}
    </div>
  );
}

function DrawingCard({ d, onOpen }: { d: Drawing; onOpen: () => void }) {
  const toast = useToast();
  const ext = (d.ext || "").toLowerCase();
  const inline = INLINE.has(ext);
  const open = () => {
    if (inline) onOpen();
    else void download(`/drawings/${d.id}/file`, d.filename).catch((e) => toast(errText(e), true));
  };
  return (
    <div className="card part-drawing">
      <div className="part-drawing-img" onClick={open} title={inline ? "Büyütmek için tıklayın" : "İndir"}>
        <Thumb path={inline ? `/drawings/${d.id}/thumb` : null} label={d.filename} />
      </div>
      <div style={{ wordBreak: "break-all" }}><b>{d.filename}</b></div>
      <div className="muted">Rev {d.rev || "—"} · sürüm {d.current_version}{d.match_via ? ` · ${d.match_via === "manual" ? "elle eşleşti" : "otomatik"}` : ""}</div>
      <button className="btn small" onClick={open}>{inline ? "İncele" : "İndir"}</button>
    </div>
  );
}
