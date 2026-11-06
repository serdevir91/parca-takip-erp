import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { upload } from "../api/client";
import { errText, useToast } from "./Toast";
import ColumnMapping, { type SheetLayout } from "./ColumnMapping";
import DataGrid, { type GridColumn } from "./DataGrid";
import { WarnList } from "./ExcelImportModal";
import { statusStyle } from "../theme/theme";
import { LOCALE, tx } from "../api/i18n";

// Backend: backend/app/services/tree_excel.py
type Val = string | number | boolean | null;
type Change = { id: string; part_no: string; parent_no: string; field: string; old: Val; new: Val };
type Add = {
  id: string; part_no: string; name: string; qty: number; material: string; weight: number | null; rev: string;
  procurement: string; coating: string; assembly: boolean; parent_no: string;
};
type Preview = {
  layouts: SheetLayout[];
  sheets: string[];
  rows: number;
  matched: number;
  changes: Change[];
  add: Add[];
  absent: { part_no: string; name: string; qty: number }[];
  invalid: { sheet: string; row: number; part_no: string; field: string; value: string; message: string }[];
  root: Record<string, Val> | null;
  placed: boolean;
};
export type TreeExcelApply = { root: Record<string, Val> | null; changes: Change[]; add: Add[] };
type Tab = "changes" | "add" | "absent" | "invalid";

const fmt = (n: number) => n.toLocaleString(LOCALE);
const show = (v: Val) => (v === null || v === "" ? tx("(Boş)") : typeof v === "number" ? v.toLocaleString(LOCALE) : String(v));

const mapFields = (): [string, string][] => [
  ["part_no", tx("Parça No")], ["name", tx("Parça Adı")], ["qty", tx("Adet")], ["material", tx("Malzeme")], ["weight", tx("Ağırlık")],
  ["rev", tx("Rev")], ["temin", tx("Temin Şekli")], ["coating", tx("Kaplama")], ["level", tx("Seviye")], ["parent", tx("Üst montaj")],
  ["type", tx("Tip")],
];
const fieldName = (): Record<string, string> => ({
  name: tx("Parça Adı"), qty: tx("Adet"), material: tx("Malzeme"), weight: tx("Ağırlık (g)"), rev: tx("Rev"),
  procurement: tx("Temin Şekli"), coating: tx("Kaplama"), temin: tx("Temin Şekli"), part_no: tx("Parça No"),
});

/** Any spreadsheet against the tree on screen. The result goes back to the page, so it can be undone like any edit. */
export default function TreeExcelModal({ pid, tree, target, onApply, onClose }: {
  pid: number;
  tree: unknown;
  target: string;
  onApply: (a: TreeExcelApply) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pct, setPct] = useState(0);
  const [tab, setTab] = useState<Tab>("changes");
  const [sel, setSel] = useState<RowSelectionState>({});
  const [selAdd, setSelAdd] = useState<RowSelectionState>({});

  const pv = useMutation({
    mutationFn: ({ f, layouts }: { f: File; layouts?: SheetLayout[] }) => {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("tree", JSON.stringify(tree));
      if (layouts) fd.append("config", JSON.stringify({ sheets: Object.fromEntries(layouts.map((l) => [l.name, { use: l.use, cols: l.cols }])) }));
      setPct(0);
      return upload<Preview>(`/projects/${pid}/bom/tree/excel`, fd, setPct);
    },
    onSuccess: (d) => {
      setPreview(d);
      setSel(Object.fromEntries(d.changes.map((c) => [c.id, true])));
      setSelAdd(Object.fromEntries(d.add.map((a) => [a.id, true])));
      setTab(d.changes.length ? "changes" : d.add.length ? "add" : d.invalid.length ? "invalid" : "changes");
    },
    onError: (e) => toast(errText(e), true),
  });

  const changeColumns = useMemo<GridColumn<Change>[]>(() => [
    { id: "part_no", header: tx("Parça No"), size: 210, accessorKey: "part_no" },
    { id: "parent_no", header: tx("Üst montaj"), size: 170, accessorKey: "parent_no" },
    { id: "field", header: tx("Alan"), size: 140, accessorFn: (r) => fieldName()[r.field] ?? r.field },
    { id: "old", header: tx("Eski"), size: 190, accessorFn: (r) => show(r.old), cellStyle: () => statusStyle("FFEB9C") },
    { id: "new", header: tx("Yeni"), size: 190, accessorFn: (r) => show(r.new), cellStyle: () => statusStyle("C6EFCE") },
  ], []);
  const addColumns = useMemo<GridColumn<Add>[]>(() => [
    { id: "part_no", header: tx("Parça No"), size: 210, accessorKey: "part_no" },
    { id: "name", header: tx("Parça Adı"), size: 200, accessorKey: "name" },
    { id: "parent_no", header: tx("Üst montaj"), size: 170, accessorFn: (r) => r.parent_no || target },
    { id: "qty", header: tx("Adet"), size: 70, accessorKey: "qty" },
    { id: "assembly", header: tx("Tip"), size: 90, accessorFn: (r) => (r.assembly ? tx("Montaj") : tx("Parça")) },
    { id: "material", header: tx("Malzeme"), size: 140, accessorKey: "material" },
    { id: "procurement", header: tx("Temin Şekli"), size: 140, accessorKey: "procurement" },
  ], [target]);

  const changes = preview?.changes ?? [];
  const add = preview?.add ?? [];
  const chosen = changes.filter((c) => sel[c.id]);
  const chosenAdd = add.filter((a) => selAdd[a.id]);
  const count = chosen.length + chosenAdd.length + (preview?.root ? 1 : 0);
  const busy = pv.isPending;
  const pick = (f: File) => { setFile(f); setPreview(null); pv.mutate({ f }); };
  const allOf = <T extends { id: string }>(rows: T[], on: boolean): RowSelectionState => (on ? Object.fromEntries(rows.map((r) => [r.id, true])) : {});

  return (
    <div className="modal-back" onClick={() => !busy && onClose()}>
      <div className="modal imp-modal" role="dialog" aria-label={tx("Excel ile eşleştir")} onClick={(e) => e.stopPropagation()}>
        <h2 style={{ marginTop: 0 }}>{tx("Excel ile eşleştir")}</h2>
        <div className="row">
          <label className="btn small primary">
            {tx("Dosya seç")}
            <input type="file" hidden accept=".xlsx,.xlsm,.xls,.csv" onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); e.target.value = ""; }} />
          </label>
          {file && <span className="muted">{file.name}</span>}
        </div>
        {busy && (
          <div style={{ marginTop: 8 }}>
            <div className="progress"><div style={{ width: `${pct}%` }} /></div>
            <div className="muted">{pct < 100 ? tx("Yükleniyor… %{0}", pct) : tx("Dosya ürün ağacı ile karşılaştırılıyor…")}</div>
          </div>
        )}
        {!preview && !busy && (
          <p className="muted">{tx("Herhangi bir Excel veya CSV dosyası seçin. Sütunlar otomatik bulunur, yeni satırlar ve değişen alanlar önce burada gösterilir. Seviye veya üst montaj sütunu varsa yeni satırlar doğru yere eklenir.")}</p>
        )}
        {preview && (
          <>
            <div className="row" style={{ marginTop: 10 }}>
              <span className="badge">{tx("{0} satır okundu", fmt(preview.rows))}</span>
              <span className="badge">{tx("{0} parça eşleşti", fmt(preview.matched))}</span>
              <span className="badge new">{tx("{0} değişiklik", fmt(changes.length))}</span>
              <span className="badge new">{tx("{0} yeni satır", fmt(add.length))}</span>
              {preview.invalid.length > 0 && <span className="badge err">{tx("{0} geçersiz değer", fmt(preview.invalid.length))}</span>}
            </div>
            <ColumnMapping layouts={preview.layouts} fields={mapFields()} busy={busy}
              open={preview.matched === 0 && !add.length} onChange={(layouts) => file && pv.mutate({ f: file, layouts })} />
            {preview.root && <p>{tx("Ağacın kökü dosyadan alınacak: {0}", String(preview.root.part_no))}</p>}
            {add.length > 0 && !preview.placed && <p className="muted">{tx("Dosyada seviye veya üst montaj sütunu yok. Yeni satırlar şu montajın altına eklenir: {0}", target || tx("Kök"))}</p>}
            <div className="tabs" style={{ marginTop: 10 }}>
              <button className={tab === "changes" ? "active" : ""} onClick={() => setTab("changes")}>{tx("Değişiklikler ({0})", fmt(changes.length))}</button>
              <button className={tab === "add" ? "active" : ""} onClick={() => setTab("add")}>{tx("Yeni satırlar ({0})", fmt(add.length))}</button>
              <button className={tab === "absent" ? "active" : ""} onClick={() => setTab("absent")}>{tx("Dosyada yok ({0})", fmt(preview.absent.length))}</button>
              <button className={tab === "invalid" ? "active" : ""} onClick={() => setTab("invalid")}>{tx("Geçersiz ({0})", fmt(preview.invalid.length))}</button>
            </div>
            <div className="imp-body">
              {tab === "changes" && (
                <DataGrid<Change> exportName={false} data={changes} columns={changeColumns} getRowId={(r) => r.id}
                  selectable selection={sel} onSelectionChange={setSel} emptyText={tx("Değişiklik yok; dosya ile ağaç aynı.")}
                  toolbar={<div className="row">
                    <button className="btn small" onClick={() => setSel(allOf(changes, true))}>{tx("Tümünü seç")}</button>
                    <button className="btn small" onClick={() => setSel({})}>{tx("Seçimi kaldır")}</button>
                  </div>} />
              )}
              {tab === "add" && (
                <DataGrid<Add> exportName={false} data={add} columns={addColumns} getRowId={(r) => r.id}
                  selectable selection={selAdd} onSelectionChange={setSelAdd} emptyText={tx("Dosyada ağaca eklenecek yeni satır yok.")}
                  toolbar={<div className="row">
                    <button className="btn small" onClick={() => setSelAdd(allOf(add, true))}>{tx("Tümünü seç")}</button>
                    <button className="btn small" onClick={() => setSelAdd({})}>{tx("Seçimi kaldır")}</button>
                  </div>} />
              )}
              {tab === "absent" && (
                <WarnList empty={tx("Ağaçtaki tüm parçalar dosyada bulundu.")} note={tx("Bu parçalar ağaçta var ama dosyada yok. Ağaçtan silinmez.")}
                  head={[tx("Parça No"), tx("Parça Adı"), tx("Adet")]} rows={preview.absent.map((a) => [a.part_no, a.name, a.qty])} />
              )}
              {tab === "invalid" && (
                <WarnList empty={tx("Geçersiz değer yok.")} note={tx("Bu hücrelerdeki değerler kabul edilmedi; ağaca aktarılmaz. Excel'de düzeltip yeniden yükleyin.")}
                  head={[tx("Sayfa"), tx("Satır"), tx("Parça No"), tx("Alan"), tx("Değer"), tx("Hata")]}
                  rows={preview.invalid.map((v) => [v.sheet, v.row, v.part_no, fieldName()[v.field] ?? v.field, v.value || tx("(Boş)"), v.message])} />
              )}
            </div>
          </>
        )}
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose} disabled={busy}>{tx("Kapat")}</button>
          {preview && (
            <button className="btn primary" disabled={busy || !count}
              onClick={() => { onApply({ root: preview.root, changes: chosen, add: chosenAdd }); toast(tx("{0} değişiklik uygulandı", fmt(count))); onClose(); }}>
              {tx("Uygula ({0})", fmt(count))}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
