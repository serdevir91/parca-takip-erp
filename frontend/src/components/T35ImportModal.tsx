import { useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { api, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { errText, useToast } from "./Toast";
import DataGrid, { type GridColumn } from "./DataGrid";
import { statusStyle } from "../theme/theme";

// Backend: backend/app/api/t35.py
const PREVIEW_PATH = (pid: number) => `/projects/${pid}/t35/preview`;
const APPLY_PATH = (pid: number) => `/projects/${pid}/t35/apply`;

type Field = "progress" | "manufacturer" | "material_status" | "t35_note";
const FIELDS: Field[] = ["progress", "manufacturer", "material_status", "t35_note"];
const FIELD_LABEL: Record<Field, string> = {
  progress: "İlerleme", manufacturer: "Üretici", material_status: "Malzeme Durumu", t35_note: "Durum Notu",
};

type Update = {
  part_no: string;
  row: number;
  text: string;
  changes: Partial<Record<Field, { old: string; new: string }>>;
  changed: boolean;
  status: string;
  rev: string;
};

type Preview = {
  filename: string;
  rows: number;
  updates: Update[];
  only_in_bom: { part_no: string; is_assembly: boolean; status: string }[];
  only_in_list: string[];
  rev_diff: { part_no: string; bom: string; list: string; warning: string }[];
  qty_diff: { part_no: string; bom: number; list: number }[];
  counts: { rows: number; matched: number; changed: number; only_in_bom: number; only_in_list: number; rev_diff: number; qty_diff: number };
};

type ApplyResp = { applied: number; fields: number; errors: { part_no: string; error: string }[] };

type ChangeRow = { id: string; part_no: string; field: Field; label: string; old: string; new: string; text: string; row: number; match: string };

type Tab = "changes" | "only_in_list" | "only_in_bom" | "rev" | "qty";

const fmt = (n: number) => n.toLocaleString("tr-TR");

type Props = { pid: number; open: boolean; onClose: () => void };

export function T35ImportModal(p: Props) {
  if (!p.open) return null;
  return <Inner {...p} />;
}
export default T35ImportModal;

function Inner({ pid, onClose }: Props) {
  const canEdit = useAuth().can("control", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pct, setPct] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [sel, setSel] = useState<RowSelectionState>({});
  const [tab, setTab] = useState<Tab>("changes");
  const [result, setResult] = useState<ApplyResp | null>(null);

  const changeRows = useMemo<ChangeRow[]>(() => {
    if (!preview) return [];
    const out: ChangeRow[] = [];
    for (const u of preview.updates) {
      if (!u.changed) continue;
      for (const f of FIELDS) {
        const c = u.changes[f];
        if (!c) continue;
        out.push({ id: `${u.part_no}|${f}`, part_no: u.part_no, field: f, label: FIELD_LABEL[f], old: c.old ?? "", new: c.new ?? "", text: u.text ?? "", row: u.row, match: "Eşleşti" });
      }
    }
    return out;
  }, [preview]);

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
      for (const u of d.updates) if (u.changed) for (const f of FIELDS) if (u.changes[f]) all[`${u.part_no}|${f}`] = true;
      setSel(all);
      setTab("changes");
    },
    onError: (e) => toast(errText(e), true),
  });

  const ap = useMutation({
    mutationFn: (items: Record<string, string>[]) => api.post<ApplyResp>(APPLY_PATH(pid), { items }),
    onSuccess: (r) => {
      setResult(r);
      toast(`${fmt(r.applied)} parça, ${fmt(r.fields)} alan güncellendi` + (r.errors.length ? ` · ${fmt(r.errors.length)} hata` : ""), r.errors.length > 0);
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
      qc.invalidateQueries({ queryKey: ["control", pid] });
      if (!r.errors.length) onClose();
    },
    onError: (e) => toast(errText(e), true),
  });

  const selectedCount = useMemo(() => changeRows.reduce((n, r) => n + (sel[r.id] ? 1 : 0), 0), [changeRows, sel]);

  const doApply = () => {
    const byPart = new Map<string, Record<string, string>>();
    for (const r of changeRows) {
      if (!sel[r.id]) continue;
      let it = byPart.get(r.part_no);
      if (!it) { it = { part_no: r.part_no }; byPart.set(r.part_no, it); }
      it[r.field] = r.new;
    }
    if (!byPart.size) return;
    ap.mutate([...byPart.values()]);
  };

  const selectAll = (on: boolean) => {
    if (!on) return setSel({});
    const all: RowSelectionState = {};
    for (const r of changeRows) all[r.id] = true;
    setSel(all);
  };

  const columns = useMemo<GridColumn<ChangeRow>[]>(() => [
    { id: "part_no", header: "Parça No", size: 190, accessorKey: "part_no" },
    { id: "label", header: "Alan", size: 120, accessorKey: "label" },
    { id: "old", header: "Mevcut", size: 170, accessorKey: "old", cell: ({ row }) => <span className="muted" title={row.original.old}>{row.original.old || "(Boş)"}</span> },
    { id: "new", header: "Yeni", size: 190, accessorKey: "new", cellStyle: () => statusStyle("C6EFCE"), cell: ({ row }) => <b title={row.original.new}>{row.original.new || "(Boş)"}</b> },
    { id: "text", header: "Listedeki Durum Metni", size: 260, accessorKey: "text", cell: ({ row }) => <span title={row.original.text}>{row.original.text}</span> },
    { id: "row", header: "Satır", size: 60, accessorKey: "row" },
    { id: "match", header: "Eşleşme", size: 80, accessorKey: "match" },
  ], []);

  const busy = pv.isPending || ap.isPending;
  const c = preview?.counts;

  return (
    <div className="modal-back" onClick={() => !busy && onClose()}>
      <div className="modal imp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Durum listesini içe aktar</h3>
          <button className="btn small" onClick={onClose} disabled={busy} aria-label="Kapat">✕</button>
        </div>
        {!canEdit ? (
          <div className="muted" style={{ marginTop: 12 }}>Bu işlem için düzenleme yetkisi gerekir.</div>
        ) : (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <input ref={fileRef} type="file" accept=".xlsx,.xlsm" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); if (f) pv.mutate(f); e.target.value = ""; }} />
              <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>Excel dosyası seç (.xlsx)</button>
              {file && <span className="muted">{file.name}</span>}
              {preview && file && <button className="btn small" disabled={busy} onClick={() => pv.mutate(file)}>Yeniden oku</button>}
            </div>
            {pv.isPending && (
              <div style={{ marginTop: 8 }}>
                <div className="progress"><div style={{ width: `${pct}%` }} /></div>
                <div className="muted">{pct < 100 ? `Yükleniyor… %${pct}` : "Liste BOM ile karşılaştırılıyor…"}</div>
              </div>
            )}
            {!preview && !pv.isPending && (
              <p className="muted">Dosya okunur ve güncel BOM ile karşılaştırılır. Uygula demeden hiçbir şey kaydedilmez.</p>
            )}
            {preview && c && (
              <>
                <div className="row" style={{ marginTop: 10 }}>
                  <span className="badge">{fmt(c.rows)} satır okundu</span>
                  <span className="badge">{fmt(c.matched)} eşleşen parça</span>
                  <span className="badge new">{fmt(c.changed)} parçada değişiklik</span>
                  {c.only_in_list > 0 && <span className="badge warn">{fmt(c.only_in_list)} eşleşmeyen</span>}
                  {c.rev_diff > 0 && <span className="badge warn">{fmt(c.rev_diff)} revizyon farkı</span>}
                </div>
                <div className="tabs" style={{ marginTop: 10, marginBottom: 0 }}>
                  <button className={tab === "changes" ? "active" : ""} onClick={() => setTab("changes")}>Değişiklikler ({fmt(changeRows.length)})</button>
                  <button className={tab === "only_in_list" ? "active" : ""} onClick={() => setTab("only_in_list")}>Eşleşmeyen ({fmt(preview.only_in_list.length)})</button>
                  <button className={tab === "only_in_bom" ? "active" : ""} onClick={() => setTab("only_in_bom")}>Listede olmayan BOM parçaları ({fmt(preview.only_in_bom.length)})</button>
                  <button className={tab === "rev" ? "active" : ""} onClick={() => setTab("rev")}>Revizyon farkı ({fmt(preview.rev_diff.length)})</button>
                  <button className={tab === "qty" ? "active" : ""} onClick={() => setTab("qty")}>Adet farkı ({fmt(preview.qty_diff.length)})</button>
                </div>
                <div className="imp-body">
                  {tab === "changes" && (
                    <DataGrid<ChangeRow>
                      exportName={false}
                      data={changeRows} columns={columns} getRowId={(r) => r.id}
                      selectable selection={sel} onSelectionChange={setSel}
                      emptyText="Uygulanacak değişiklik yok; liste ile takip bilgileri aynı."
                      toolbar={<div className="row">
                        <button className="btn small" onClick={() => selectAll(true)}>Tümünü seç</button>
                        <button className="btn small" onClick={() => selectAll(false)}>Seçimi kaldır</button>
                        <span className="muted">{fmt(selectedCount)} değişiklik seçili</span>
                      </div>}
                    />
                  )}
                  {tab === "only_in_list" && (
                    <SimpleList empty="Listedeki tüm parçalar BOM ile eşleşti." note="Bu parçalar durum listesinde var ama güncel BOM'da (veya alias tablosunda) bulunamadı; uygulanmaz."
                      head={["Parça No"]} rows={preview.only_in_list.map((x) => [x])} />
                  )}
                  {tab === "only_in_bom" && (
                    <SimpleList empty="BOM'daki tüm parçalar listede var." note="Bu BOM parçaları durum listesinde yok."
                      head={["Parça No", "Tip", "Durum"]} rows={preview.only_in_bom.map((x) => [x.part_no, x.is_assembly ? "Montaj" : "Parça", x.status])} />
                  )}
                  {tab === "rev" && (
                    <SimpleList empty="Revizyon farkı yok." note="DİKKAT: üretilmiş parçada revizyon farkı."
                      head={["Parça No", "BOM Rev", "Liste Rev", "Uyarı"]} rows={preview.rev_diff.map((x) => [x.part_no, x.bom || "-", x.list || "-", x.warning])} />
                  )}
                  {tab === "qty" && (
                    <SimpleList empty="Adet farkı yok." note="Listedeki adet BOM toplam adedinden farklı."
                      head={["Parça No", "BOM Toplam Adet", "Liste Adet"]} rows={preview.qty_diff.map((x) => [x.part_no, fmt(x.bom), fmt(x.list)])} />
                  )}
                </div>
                {result && result.errors.length > 0 && (
                  <div className="card" style={{ marginTop: 8, maxHeight: 140, overflow: "auto" }}>
                    <b className="error">{fmt(result.errors.length)} parça uygulanamadı:</b>
                    <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                      {result.errors.slice(0, 200).map((e, i) => <li key={i}>{e.part_no}: {e.error}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" onClick={onClose} disabled={busy}>Kapat</button>
              {preview && (
                <button className="btn primary" disabled={busy || selectedCount === 0} onClick={doApply}>
                  {ap.isPending ? "Uygulanıyor…" : `Uygula (${fmt(selectedCount)})`}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Plain list for side tabs; capped to keep the DOM small. */
function SimpleList({ head, rows, empty, note }: { head: string[]; rows: (string | number)[][]; empty: string; note?: string }) {
  if (!rows.length) return <div className="muted" style={{ padding: 12 }}>{empty}</div>;
  const LIMIT = 500;
  return (
    <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
      {note && <div className="muted" style={{ padding: "6px 8px" }}>{note}</div>}
      <table className="simple">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.slice(0, LIMIT).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
      </table>
      {rows.length > LIMIT && <div className="muted" style={{ padding: 8 }}>İlk {fmt(LIMIT)} / {fmt(rows.length)} kayıt gösteriliyor.</div>}
    </div>
  );
}
