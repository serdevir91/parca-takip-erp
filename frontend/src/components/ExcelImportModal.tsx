import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { api, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { errText, useToast } from "./Toast";
import ColumnMapping, { type SheetLayout } from "./ColumnMapping";
import DataGrid, { type GridColumn } from "./DataGrid";
import { statusStyle } from "../theme/theme";
import { LOCALE, tx } from "../api/i18n";

// Backend: backend/app/api/excel.py (router prefix /excel)
const PREVIEW_PATH = (pid: number) => `/excel/${pid}/compare`;
const APPLY_PATH = (pid: number) => `/excel/${pid}/import/apply`;

type Val = string | number | boolean | null;

type Change = {
  id: string;
  kind: "tracking" | "missing" | "fastener" | string;
  key: string;
  label: string;
  field: string;
  field_label: string;
  old: Val;
  new: Val;
  sheet: string;
  row: number;
};

type NewTemin = { raw: string; name: string; kind: string; count: number };

type Preview = {
  mode: "any" | "export";
  sheets: string[];
  rows: number;
  matched: number;
  changes: Change[];
  unknown: { sheet: string; row: number; part_no: string }[];
  invalid: { sheet: string; row: number; key: string; field: string; value: string; message: string }[];
  not_in_file: { part_no: string; name: string; status: string; procurement: string }[];
  layouts: SheetLayout[];
  unresolved: { value: string; count: number }[];
  new_temins: NewTemin[];
  version_id: number;
};

type Values = { progress: Record<string, string>; temin: Record<string, string> };
type Config = { sheets: Record<string, { use: boolean; cols: Record<string, number> }>; values: Values };

type ApplyResp = { applied: number; skipped: { key: string; message: string }[] };

const KIND_LABEL: Record<string, string> = { tracking: tx("Parça"), missing: tx("Eksik satırı"), fastener: tx("Bağlantı elemanı") };

const fmt = (n: number) => n.toLocaleString(LOCALE);
const show = (v: Val): string =>
  v === null || v === undefined || v === "" ? tx("(Boş)") : typeof v === "number" ? v.toLocaleString(LOCALE) : typeof v === "boolean" ? (v ? tx("Evet") : tx("Hayır")) : String(v);

const NO_VALUES: Values = { progress: {}, temin: {} };
const PROGRESS = ["Bekliyor", "Devam ediyor", "Tamamlandı"];
const NEW_KINDS = ["İmalat", "Hazır Alım"];

const mapFields = (): [string, string][] => [
  ["part_no", tx("Parça No")], ["status", tx("Durum (üretim)")], ["order", tx("Sipariş Durumu")], ["temin", tx("Temin Şekli")],
  ["manufacturer", tx("Üretici")], ["material_status", tx("Malzeme Durumu")], ["t35_note", tx("Durum Notu")], ["note", tx("Not")],
];

type Tab = "changes" | "unknown" | "invalid" | "absent";
type Props = { pid: number; open: boolean; onClose: () => void };

export function ExcelImportModal(p: Props) {
  if (!p.open) return null;
  return <Inner {...p} />;
}
export default ExcelImportModal;

function Inner({ pid, onClose }: Props) {
  const canEdit = useAuth().can("parts", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pct, setPct] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [sel, setSel] = useState<RowSelectionState>({});
  const [tab, setTab] = useState<Tab>("changes");
  const [result, setResult] = useState<ApplyResp | null>(null);
  const [values, setValues] = useState<Values>(NO_VALUES);
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const choices = useQuery({
    queryKey: ["partChoices", pid],
    queryFn: () => api.get<{ temin_choices: string[] }>(`/projects/${pid}/parts/choices`),
  });

  const changes = preview?.changes ?? [];

  const pv = useMutation({
    mutationFn: ({ f, config }: { f: File; config?: Config }) => {
      const fd = new FormData();
      fd.append("file", f);
      if (config) fd.append("config", JSON.stringify(config));
      setPct(0);
      return upload<Preview>(PREVIEW_PATH(pid), fd, setPct);
    },
    onSuccess: (d) => {
      setPreview(d);
      setResult(null);
      const all: RowSelectionState = {};
      for (const c of d.changes) all[c.id] = true;
      setSel(all);
      setTab(d.changes.length || !(d.unknown.length || d.invalid.length) ? "changes" : d.invalid.length ? "invalid" : "unknown");
    },
    onError: (e) => toast(errText(e), true),
  });

  const ap = useMutation({
    mutationFn: (items: Change[]) => {
      const used = new Set(items.filter((c) => c.field === "procurement_override").map((c) => String(c.new)));
      const new_temins = (preview?.new_temins ?? []).filter((t) => used.has(t.name)).map((t) => ({ name: t.name, kind: kinds[t.raw] ?? t.kind }));
      return api.post<ApplyResp>(APPLY_PATH(pid), { new_temins, changes: items.map((c) => ({ kind: c.kind, key: c.key, field: c.field, new: c.new, old: c.old })) });
    },
    onSuccess: (r) => {
      setResult(r);
      toast(tx("{0} değişiklik uygulandı", fmt(r.applied)) + (r.skipped.length ? tx(" · {0} atlandı", fmt(r.skipped.length)) : ""), r.skipped.length > 0);
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
      qc.invalidateQueries({ queryKey: ["fasteners", pid] });
      qc.invalidateQueries({ queryKey: ["control", pid] });
      qc.invalidateQueries({ queryKey: ["partChoices", pid] });
      if (!r.skipped.length) onClose();
    },
    onError: (e) => toast(errText(e), true),
  });

  const selectedCount = useMemo(() => changes.reduce((n, c) => n + (sel[c.id] ? 1 : 0), 0), [changes, sel]);

  const selectAll = (on: boolean) => {
    if (!on) return setSel({});
    const all: RowSelectionState = {};
    for (const c of changes) all[c.id] = true;
    setSel(all);
  };

  const columns = useMemo<GridColumn<Change>[]>(() => [
    { id: "label", header: tx("Parça No / Kalem"), size: 210, accessorKey: "label" },
    { id: "kind", header: tx("Tür"), size: 110, accessorFn: (r) => KIND_LABEL[r.kind] ?? r.kind },
    { id: "field_label", header: tx("Alan"), size: 130, accessorKey: "field_label" },
    { id: "old", header: tx("Mevcut"), size: 170, accessorFn: (r) => show(r.old), cell: ({ getValue }) => <span className="muted" title={getValue()}>{getValue()}</span> },
    { id: "new", header: tx("Yeni"), size: 190, accessorFn: (r) => show(r.new), cellStyle: () => statusStyle("C6EFCE"), cell: ({ getValue }) => <b title={getValue()}>{getValue()}</b> },
    { id: "sheet", header: tx("Sayfa"), size: 130, accessorKey: "sheet" },
    { id: "row", header: tx("Satır"), size: 60, accessorKey: "row" },
  ], []);

  const busy = pv.isPending || ap.isPending;

  /** Read the same file again with the corrected columns and values. */
  const rerun = (layouts: SheetLayout[], next: Values) => {
    setValues(next);
    if (file) pv.mutate({ f: file, config: { values: next, sheets: Object.fromEntries(layouts.map((l) => [l.name, { use: l.use, cols: l.cols }])) } });
  };
  const layouts = preview?.layouts ?? [];
  const pickFile = (f: File) => {
    setFile(f);
    setValues(NO_VALUES);
    setKinds({});
    pv.mutate({ f });
  };

  return (
    <div className="modal-back" onClick={() => !busy && onClose()}>
      <div className="modal imp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>{tx("Excel ile karşılaştır ve güncelle")}</h3>
          <button className="btn small" onClick={onClose} disabled={busy} aria-label={tx("Kapat")}>✕</button>
        </div>
        {!canEdit ? (
          <div className="muted" style={{ marginTop: 12 }}>{tx("Bu işlem için düzenleme yetkisi gerekir.")}</div>
        ) : (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.xls,.csv" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) pickFile(f); e.target.value = ""; }} />
              <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>{tx("Excel dosyası seç")}</button>
              {file && <span className="muted">{file.name}</span>}
              {preview && file && <button className="btn small" disabled={busy} onClick={() => pickFile(file)}>{tx("Yeniden oku")}</button>}
            </div>
            {pv.isPending && (
              <div style={{ marginTop: 8 }}>
                <div className="progress"><div style={{ width: `${pct}%` }} /></div>
                <div className="muted">{pct < 100 ? tx("Yükleniyor… %{0}", pct) : tx("Dosya veritabanı ile karşılaştırılıyor…")}</div>
              </div>
            )}
            {!preview && !pv.isPending && (
              <p className="muted">{tx("Herhangi bir Excel veya CSV dosyası seçin. Parça numarası, durum ve temin sütunları otomatik bulunur, dosya mevcut parça listesiyle karşılaştırılır. Uygula demeden hiçbir şey kaydedilmez.")}</p>
            )}
            {preview && (
              <>
                <div className="row" style={{ marginTop: 10 }}>
                  <span className="badge">{tx("{0} satır okundu", fmt(preview.rows))}</span>
                  <span className="badge" title={preview.sheets.join(", ")}>{tx("{0} sayfa", fmt(preview.sheets.length))}</span>
                  {preview.mode === "any" && <span className="badge">{tx("{0} parça eşleşti", fmt(preview.matched))}</span>}
                  <span className="badge new">{tx("{0} değişiklik", fmt(changes.length))}</span>
                  {preview.unknown.length > 0 && <span className="badge warn">{tx("{0} bilinmeyen parça no", fmt(preview.unknown.length))}</span>}
                  {preview.invalid.length > 0 && <span className="badge err">{tx("{0} geçersiz değer", fmt(preview.invalid.length))}</span>}
                </div>
                {preview.mode === "any" && (
                  <ColumnMapping layouts={layouts} fields={mapFields()} busy={busy} open={preview.matched === 0} onChange={(l) => rerun(l, values)} />
                )}
                {(preview.unresolved.length > 0 || preview.new_temins.length > 0) && (
                  <div className="card imp-values" style={{ marginTop: 10, maxHeight: 200, overflow: "auto" }}>
                    {preview.unresolved.length > 0 && <b>{tx("Anlaşılamayan durum değerleri: ne anlama geliyor?")}</b>}
                    {preview.unresolved.map((u) => (
                      <div className="row" key={u.value}>
                        <span>{u.value} <span className="muted">({fmt(u.count)})</span></span>
                        <select value="?" disabled={busy} aria-label={u.value}
                          onChange={(e) => rerun(layouts, { ...values, progress: { ...values.progress, [u.value]: e.target.value } })}>
                          <option value="?">{tx("Seçin…")}</option>
                          {PROGRESS.map((p) => <option key={p} value={p}>{tx(p)}</option>)}
                          <option value="">{tx("Yoksay")}</option>
                        </select>
                      </div>
                    ))}
                    {preview.new_temins.length > 0 && <b>{tx("Listede olmayan temin şekilleri")}</b>}
                    {preview.new_temins.map((t) => (
                      <div className="row" key={t.raw}>
                        <span>{t.raw} <span className="muted">({fmt(t.count)})</span></span>
                        <select value={`new:${kinds[t.raw] ?? t.kind}`} disabled={busy} aria-label={t.raw}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v.startsWith("new:")) setKinds((k) => ({ ...k, [t.raw]: v.slice(4) }));
                            else rerun(layouts, { ...values, temin: { ...values.temin, [t.raw]: v.slice(4) } });
                          }}>
                          {NEW_KINDS.map((k) => <option key={k} value={`new:${k}`}>{tx("Yeni tür ekle: {0}", tx(k))}</option>)}
                          {(choices.data?.temin_choices ?? []).map((c) => <option key={c} value={`map:${c}`}>{tx(c)}</option>)}
                          <option value="map:">{tx("Yoksay")}</option>
                        </select>
                      </div>
                    ))}
                  </div>
                )}
                <div className="tabs" style={{ marginTop: 10, marginBottom: 0 }}>
                  <button className={tab === "changes" ? "active" : ""} onClick={() => setTab("changes")}>{tx("Değişiklikler ({0})", fmt(changes.length))}</button>
                  <button className={tab === "unknown" ? "active" : ""} onClick={() => setTab("unknown")}>{tx("Bilinmeyen parça no ({0})", fmt(preview.unknown.length))}</button>
                  <button className={tab === "invalid" ? "active" : ""} onClick={() => setTab("invalid")}>{tx("Geçersiz değerler ({0})", fmt(preview.invalid.length))}</button>
                  {preview.mode === "any" && <button className={tab === "absent" ? "active" : ""} onClick={() => setTab("absent")}>{tx("Excel'de olmayan parçalar ({0})", fmt(preview.not_in_file.length))}</button>}
                </div>
                <div className="imp-body">
                  {tab === "changes" && (
                    <DataGrid<Change>
                      exportName={false}
                      data={changes} columns={columns} getRowId={(r) => r.id}
                      selectable selection={sel} onSelectionChange={setSel}
                      emptyText={tx("Değişiklik yok; dosya ile veritabanı aynı.")}
                      toolbar={<div className="row">
                        <button className="btn small" onClick={() => selectAll(true)}>{tx("Tümünü seç")}</button>
                        <button className="btn small" onClick={() => selectAll(false)}>{tx("Seçimi kaldır")}</button>
                        <span className="muted">{tx("{0} değişiklik seçili", fmt(selectedCount))}</span>
                      </div>}
                    />
                  )}
                  {tab === "unknown" && (
                    <WarnList empty={tx("Tüm parça numaraları güncel BOM'da bulundu.")}
                      note={tx("Bu satırlardaki parça numaraları güncel BOM'da yok; içe aktarılmaz.")}
                      head={[tx("Sayfa"), tx("Satır"), tx("Parça No")]} rows={preview.unknown.map((u) => [u.sheet, u.row, u.part_no])} />
                  )}
                  {tab === "invalid" && (
                    <WarnList empty={tx("Geçersiz değer yok.")}
                      note={tx("Bu hücrelerdeki değerler kabul edilmedi; içe aktarılmaz. Excel'de düzeltip yeniden yükleyin.")}
                      head={[tx("Sayfa"), tx("Satır"), tx("Kalem"), tx("Alan"), tx("Değer"), tx("Hata")]}
                      rows={preview.invalid.map((v) => [v.sheet, v.row, v.key, tx(v.field), v.value || tx("(Boş)"), v.message])} />
                  )}
                  {tab === "absent" && (
                    <WarnList empty={tx("Projedeki tüm parçalar dosyada bulundu.")}
                      note={tx("Bu parçalar projede var ama dosyada yok. Değerleri değişmez.")}
                      head={[tx("Parça No"), tx("Parça Adı"), tx("Temin Şekli"), tx("Durum")]}
                      rows={preview.not_in_file.map((p) => [p.part_no, p.name, tx(p.procurement), tx(p.status)])} />
                  )}
                </div>
                {result && result.skipped.length > 0 && (
                  <div className="card" style={{ marginTop: 8, maxHeight: 140, overflow: "auto" }}>
                    <b className="error">{tx("{0} değişiklik atlandı:", fmt(result.skipped.length))}</b>
                    <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                      {result.skipped.slice(0, 200).map((s, i) => <li key={i}>{s.key}: {s.message}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" onClick={onClose} disabled={busy}>{tx("Kapat")}</button>
              {preview && (
                <button className="btn primary" disabled={busy || selectedCount === 0}
                  onClick={() => ap.mutate(changes.filter((c) => sel[c.id]))}>
                  {ap.isPending ? tx("Uygulanıyor…") : tx("Uygula ({0})", fmt(selectedCount))}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Warning list for side tabs; capped to keep the DOM small. */
export function WarnList({ head, rows, empty, note }: { head: string[]; rows: (string | number)[][]; empty: string; note: string }) {
  if (!rows.length) return <div className="muted" style={{ padding: 12 }}>{empty}</div>;
  const LIMIT = 500;
  return (
    <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
      <div className="muted" style={{ padding: "6px 8px" }}>{note}</div>
      <table className="simple">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.slice(0, LIMIT).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{typeof v === "number" ? v : v}</td>)}</tr>)}</tbody>
      </table>
      {rows.length > LIMIT && <div className="muted" style={{ padding: 8 }}>{tx("İlk {0} / {1} kayıt gösteriliyor.", fmt(LIMIT), fmt(rows.length))}</div>}
    </div>
  );
}
