import { useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { api, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { errText, useToast } from "./Toast";
import DataGrid, { type GridColumn } from "./DataGrid";
import { statusStyle } from "../theme/theme";
import { LOCALE, tx } from "../api/i18n";

// Backend: backend/app/api/excel.py (router prefix /excel)
const PREVIEW_PATH = (pid: number) => `/excel/${pid}/import`;
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

type Preview = {
  sheets: string[];
  rows: number;
  changes: Change[];
  unknown: { sheet: string; row: number; part_no: string }[];
  invalid: { sheet: string; row: number; key: string; field: string; value: string; message: string }[];
  version_id: number;
};

type ApplyResp = { applied: number; skipped: { key: string; message: string }[] };

const KIND_LABEL: Record<string, string> = { tracking: tx("Parça"), missing: tx("Eksik satırı"), fastener: tx("Bağlantı elemanı") };

const fmt = (n: number) => n.toLocaleString(LOCALE);
const show = (v: Val): string =>
  v === null || v === undefined || v === "" ? tx("(Boş)") : typeof v === "number" ? v.toLocaleString(LOCALE) : typeof v === "boolean" ? (v ? tx("Evet") : tx("Hayır")) : String(v);

type Tab = "changes" | "unknown" | "invalid";
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

  const changes = preview?.changes ?? [];

  const pv = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
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
    mutationFn: (items: Change[]) =>
      api.post<ApplyResp>(APPLY_PATH(pid), { changes: items.map((c) => ({ kind: c.kind, key: c.key, field: c.field, new: c.new, old: c.old })) }),
    onSuccess: (r) => {
      setResult(r);
      toast(tx("{0} değişiklik uygulandı", fmt(r.applied)) + (r.skipped.length ? tx(" · {0} atlandı", fmt(r.skipped.length)) : ""), r.skipped.length > 0);
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
      qc.invalidateQueries({ queryKey: ["fasteners", pid] });
      qc.invalidateQueries({ queryKey: ["control", pid] });
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

  return (
    <div className="modal-back" onClick={() => !busy && onClose()}>
      <div className="modal imp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>{tx("Düzenlenmiş Excel'i geri yükle")}</h3>
          <button className="btn small" onClick={onClose} disabled={busy} aria-label={tx("Kapat")}>✕</button>
        </div>
        {!canEdit ? (
          <div className="muted" style={{ marginTop: 12 }}>{tx("Bu işlem için düzenleme yetkisi gerekir.")}</div>
        ) : (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <input ref={fileRef} type="file" accept=".xlsx,.xlsm" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f) pv.mutate(f); e.target.value = ""; }} />
              <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>{tx("Excel dosyası seç (.xlsx)")}</button>
              {file && <span className="muted">{file.name}</span>}
              {preview && file && <button className="btn small" disabled={busy} onClick={() => pv.mutate(file)}>{tx("Yeniden oku")}</button>}
            </div>
            {pv.isPending && (
              <div style={{ marginTop: 8 }}>
                <div className="progress"><div style={{ width: `${pct}%` }} /></div>
                <div className="muted">{pct < 100 ? tx("Yükleniyor… %{0}", pct) : tx("Dosya veritabanı ile karşılaştırılıyor…")}</div>
              </div>
            )}
            {!preview && !pv.isPending && (
              <p className="muted">{tx("Sistemden alınan Takip Listesi / Parça Takip Excel'ini düzenleyip yükleyin. Değişen alanlar listelenir; Uygula demeden hiçbir şey kaydedilmez.")}</p>
            )}
            {preview && (
              <>
                <div className="row" style={{ marginTop: 10 }}>
                  <span className="badge">{tx("{0} satır okundu", fmt(preview.rows))}</span>
                  <span className="badge" title={preview.sheets.join(", ")}>{tx("{0} sayfa", fmt(preview.sheets.length))}</span>
                  <span className="badge new">{tx("{0} değişiklik", fmt(changes.length))}</span>
                  {preview.unknown.length > 0 && <span className="badge warn">{tx("{0} bilinmeyen parça no", fmt(preview.unknown.length))}</span>}
                  {preview.invalid.length > 0 && <span className="badge err">{tx("{0} geçersiz değer", fmt(preview.invalid.length))}</span>}
                </div>
                <div className="tabs" style={{ marginTop: 10, marginBottom: 0 }}>
                  <button className={tab === "changes" ? "active" : ""} onClick={() => setTab("changes")}>{tx("Değişiklikler ({0})", fmt(changes.length))}</button>
                  <button className={tab === "unknown" ? "active" : ""} onClick={() => setTab("unknown")}>{tx("Bilinmeyen parça no ({0})", fmt(preview.unknown.length))}</button>
                  <button className={tab === "invalid" ? "active" : ""} onClick={() => setTab("invalid")}>{tx("Geçersiz değerler ({0})", fmt(preview.invalid.length))}</button>
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
                      rows={preview.invalid.map((v) => [v.sheet, v.row, v.key, v.field, v.value || tx("(Boş)"), v.message])} />
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
function WarnList({ head, rows, empty, note }: { head: string[]; rows: (string | number)[][]; empty: string; note: string }) {
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
