import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
  type ColumnFiltersState, type ColumnOrderState, type ColumnPinningState, type ColumnSizingState, type Row, type RowSelectionState,
  type SortingState, type Table, type VisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, download } from "../api/client";
import { mobileApp } from "../api/mobile";
import { savePref } from "../api/prefs";
import { ADV, advFilter, AdvancedFilter, advSummary, cellText, FilterSheet, filterSummary, Icon, multiFilter, norm, type AdvValue, type ColFilter } from "./dgFilter";
import { Editor, TableView } from "./dgSheet";
import { colId, drawnColumns, freezeTo, headerText, isEmpty, type GridColumn, type GridProps } from "./dgTypes";
import MailDialog, { shareFiles, type MailFile } from "./MailDialog";
import { useAuth } from "../api/auth";
import { errText, useToast } from "./Toast";
import { LOCALE, tx } from "../api/i18n";

export { cellText, Icon, multiFilter, type ColFilter };
export type { CellChange, GridColumn } from "./dgTypes";

export type GridView = "cards" | "table";
const VIEW_KEY = "dg.view";

function readView(): GridView {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    if (v === "cards" || v === "table") return v;
  } catch {
    /* storage unavailable */
  }
  return "cards";
}

/** One "Kart / Tablo" choice for every list, remembered on this device. */
export function useGridView(): [GridView, (v: GridView) => void] {
  const [view, setView] = useState<GridView>(readView);
  useEffect(() => {
    const h = (e: Event) => setView((e as CustomEvent<GridView>).detail);
    window.addEventListener("dg-view", h);
    return () => window.removeEventListener("dg-view", h);
  }, []);
  const set = (v: GridView) => {
    try {
      localStorage.setItem(VIEW_KEY, v);
      savePref(VIEW_KEY);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new CustomEvent("dg-view", { detail: v }));
  };
  return [view, set];
}

function globalMatch(row: Row<any>, id: string, value: string): boolean {
  const v = row.getValue(id);
  return !isEmpty(v) && norm(String(v)).includes(norm(value));
}

export function toCsv<R>(rows: R[], cols: GridColumn<any>[], get: (r: R, id: string) => unknown): string {
  const esc = (v: unknown) => {
    let t = isEmpty(v) ? "" : typeof v === "number" ? String(v).replace(".", ",") : String(v);
    // Excel would run a cell starting with = + - @ as a formula; plain numbers and phone numbers stay as they are
    if (typeof v !== "number" && /^[=+\-@\t\r]/.test(t) && !/^[+-]?\d[\d\s.,]*$/.test(t)) t = `'${t}`;
    return /[";\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const use = cols.filter((c) => !c.noExport && headerText(c) && colId(c) !== "actions");
  // Semicolon + BOM: Turkish Excel opens it with the right columns and characters
  return "\ufeff" + [use.map((c) => esc(headerText(c))).join(";"),
    ...rows.map((r) => use.map((c) => esc(get(r, colId(c)))).join(";"))].join("\r\n");
}

/** What a saved view remembers; the layout part also survives on its own between visits. */
type Layout = { visibility: VisibilityState; order: ColumnOrderState; pinning: ColumnPinningState; sizing: ColumnSizingState };
type SavedView = Omit<Layout, "sizing"> & { name: string; filters: ColumnFiltersState; sorting: SortingState };

function loadJson<V>(key: string | null, fallback: V): V {
  if (!key) return fallback;
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : { ...fallback, ...JSON.parse(v) };
  } catch {
    return fallback;
  }
}
function saveJson(key: string | null, v: unknown): void {
  if (!key) return;
  try { localStorage.setItem(key, JSON.stringify(v)); savePref(key); } catch { /* storage unavailable */ }
}

/** These columns hold fixed values stored in Turkish. Anything else is user data and is shown as it is. */
const VALUE_COLUMNS = new Set(["status", "progress", "main_group", "material_status", "kind", "unit", "type", "row_type", "procurement", "procurement_csv", "method", "desc", "fastener_desc"]);
const VALUE_CELL = {
  cell: (c: { column: { id: string }; getValue: () => unknown }) => {
    const v = c.getValue();
    return typeof v === "string" && VALUE_COLUMNS.has(c.column.id) ? tx(v) : (v as ReactNode);
  },
};

/** Show, hide and reorder columns. Dragging works with a mouse, the arrows work on a phone. */
function ColumnsPanel<T>({ table, onReset, onClose }: { table: Table<T>; onReset: () => void; onClose: () => void }) {
  const all = table.getAllLeafColumns().filter((c) => c.id !== "_sel" && c.id !== ADV);
  const [dragged, setDragged] = useState<string | null>(null);
  const frozen = table.getState().columnPinning.left ?? [];
  const label = (id: string) => headerText(table.getColumn(id)!.columnDef as GridColumn<T>) || tx("İşlemler");
  const move = (id: string, to: number) => {
    const ids = all.map((c) => c.id);
    ids.splice(ids.indexOf(id), 1);
    ids.splice(Math.max(0, Math.min(to, ids.length)), 0, id);
    table.setColumnOrder(ids);
  };
  return (
    <>
      <div className="fs-backdrop" onClick={onClose} />
      <div className="fs cols card" role="dialog" aria-label={tx("Sütunlar")}>
        <div className="fs-head">
          <b>{tx("Sütunlar")}</b>
          <span className="dg-spacer" />
          <button className="dg-link" onClick={() => table.toggleAllColumnsVisible(true)}>{tx("Tümünü göster")}</button>
          <button className="dg-link" onClick={onReset}>{tx("Varsayılana dön")}</button>
          <button className="fs-close" onClick={onClose} aria-label={tx("Kapat")}><Icon name="x" /></button>
        </div>
        <div className="cols-list">
          {all.map((c, i) => (
            <div key={c.id} className={`cols-row${dragged === c.id ? " drag" : ""}`} draggable
              onDragStart={() => setDragged(c.id)} onDragEnd={() => setDragged(null)}
              onDragOver={(e) => { e.preventDefault(); if (dragged && dragged !== c.id) move(dragged, i); }}>
              <span className="cols-grip" aria-hidden="true">⠿</span>
              <label><input type="checkbox" checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} /> {label(c.id)}</label>
              {frozen.includes(c.id) && <span className="badge">{tx("Sabit")}</span>}
              <span className="dg-spacer" />
              {c.getIsVisible() && <button className="dg-link" onClick={() => freezeTo(table, c.id)}>{frozen[frozen.length - 1] === c.id ? tx("Sabitlemeyi kaldır") : tx("Buraya kadar sabitle")}</button>}
              <button className="fs-close" disabled={i === 0} onClick={() => move(c.id, i - 1)} aria-label={tx("{0} yukarı", label(c.id))}>↑</button>
              <button className="fs-close" disabled={i === all.length - 1} onClick={() => move(c.id, i + 1)} aria-label={tx("{0} aşağı", label(c.id))}>↓</button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

export default function DataGrid<T>(p: GridProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [localFilters, setLocalFilters] = useState<ColumnFiltersState>([]);
  const [localSel, setLocalSel] = useState<RowSelectionState>({});
  const [search, setSearch] = useState("");
  const filters = p.filters ?? localFilters;
  const selection = p.selection ?? localSel;
  const [view, setView] = useGridView();
  const [sheet, setSheet] = useState<"filter" | "advanced" | "export" | "columns" | "views" | null>(null);
  const [sheetCol, setSheetCol] = useState<string | null>(null);
  const [mail, setMail] = useState<MailFile | null>(null);
  const canMail = useAuth().can("mail", "edit");
  const toast = useToast();
  const stateKey = p.stateKey ?? (p.exportName || null);
  const layoutKey = stateKey ? `dg.layout.${stateKey}` : null;
  const viewsKey = stateKey ? `dg.views.${stateKey}` : null;
  const [layout, setLayout] = useState<Layout>(() => loadJson(layoutKey, { visibility: {}, order: [], pinning: { left: [] }, sizing: {} }));
  const [views, setViews] = useState<SavedView[]>(() => loadJson(viewsKey, { list: [] as SavedView[] }).list);
  const [viewName, setViewName] = useState("");
  useEffect(() => saveJson(layoutKey, layout), [layoutKey, layout]);
  useEffect(() => saveJson(viewsKey, { list: views }), [viewsKey, views]);
  const patchLayout = <K extends keyof Layout>(k: K, u: Layout[K] | ((old: Layout[K]) => Layout[K])) =>
    setLayout((s) => ({ ...s, [k]: typeof u === "function" ? (u as (old: Layout[K]) => Layout[K])(s[k]) : u }));
  // Checkbox click: plain toggles one row, Shift also sets every row back to the last clicked one
  const lastChecked = useRef<string | null>(null);
  const checkRow = useRef<(row: Row<T>, shift: boolean) => void>(() => {});

  const columns = useMemo<GridColumn<T>[]>(() => {
    const cols: GridColumn<T>[] = [...p.columns.map((c) => ({ filterFn: multiFilter, ...c })), {
      id: ADV, accessorFn: (r: T) => r, filterFn: advFilter, enableSorting: false, enableHiding: false,
      noFilter: true, noExport: true, card: "hide", header: "",
    }];
    if (!p.selectable) return cols;
    return [{
      id: "_sel", size: 32, enableSorting: false, noFilter: true, noExport: true, card: "hide",
      header: ({ table }) => (
        <input type="checkbox" aria-label={tx("Tümünü seç")} checked={table.getIsAllRowsSelected()}
          ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }}
          onChange={table.getToggleAllRowsSelectedHandler()} />
      ),
      cell: ({ row }) => (
        <input type="checkbox" aria-label={tx("Seç")} checked={row.getIsSelected()} onChange={() => {}}
          onClick={(e) => { e.stopPropagation(); checkRow.current(row, e.shiftKey); }} />
      ),
    } as GridColumn<T>, ...cols];
  }, [p.columns, p.selectable]);

  const table = useReactTable({
    data: p.data, columns, getRowId: p.getRowId, defaultColumn: VALUE_CELL,
    state: {
      sorting, columnFilters: filters, rowSelection: selection, globalFilter: search,
      columnVisibility: { ...layout.visibility, [ADV]: false },
      columnOrder: layout.order.length ? ["_sel", ...layout.order] : [],
      columnPinning: { left: layout.pinning.left?.length ? ["_sel", ...layout.pinning.left.filter((x) => x !== "_sel")] : [] },
      columnSizing: layout.sizing,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: (u) => patchLayout("visibility", u),
    onColumnOrderChange: (u) => patchLayout("order", u),
    onColumnPinningChange: (u) => patchLayout("pinning", u),
    onColumnSizingChange: (u) => patchLayout("sizing", u),
    onGlobalFilterChange: setSearch,
    globalFilterFn: globalMatch,
    getColumnCanGlobalFilter: (c) => c.id !== "_sel" && c.id !== "actions" && c.id !== ADV,
    onColumnFiltersChange: (u) => {
      const next = typeof u === "function" ? u(filters) : u;
      (p.onFiltersChange ?? setLocalFilters)(next);
    },
    onRowSelectionChange: (u) => {
      const next = typeof u === "function" ? u(selection) : u;
      (p.onSelectionChange ?? setLocalSel)(next);
    },
    enableRowSelection: !!p.selectable,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const rows = table.getRowModel().rows;
  const { onVisibleRowsChange } = p;
  // A row the filter hides must not stay selected, or a bulk change would reach rows nobody sees
  useEffect(() => {
    const on = Object.keys(selection).filter((k) => selection[k]);
    if (!on.length) return;
    const seen = new Set(table.getFilteredRowModel().rows.map((r) => r.id));
    const keep = on.filter((k) => seen.has(k));
    if (keep.length !== on.length) table.setRowSelection(Object.fromEntries(keep.map((k) => [k, true])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, search]);
  useEffect(() => { onVisibleRowsChange?.(rows.map((r) => r.original)); }, [rows, onVisibleRowsChange]);
  checkRow.current = (row, shift) => {
    const on = !row.getIsSelected();
    const from = rows.findIndex((r) => r.id === lastChecked.current);
    const to = rows.findIndex((r) => r.id === row.id);
    lastChecked.current = row.id;
    if (!shift || from < 0 || to < 0) { row.toggleSelected(on); return; }
    const next = { ...selection };
    for (const r of rows.slice(Math.min(from, to), Math.max(from, to) + 1)) {
      if (on) next[r.id] = true; else delete next[r.id];
    }
    table.setRowSelection(next);
  };
  const selectedCount = Object.values(selection).filter(Boolean).length;
  const invertSelection = () => {
    const next = { ...selection };
    for (const r of rows) {
      if (next[r.id]) delete next[r.id]; else next[r.id] = true;
    }
    table.setRowSelection(next);
  };
  const activeFilters = filters.length;
  const sortable = table.getAllLeafColumns().filter((c) => c.getCanSort() && headerText(c.columnDef as GridColumn<T>));
  const sortVal = sorting[0] ? `${sorting[0].id}:${sorting[0].desc ? "desc" : "asc"}` : "";
  const exportName = p.exportName === false ? null : p.exportName || "liste";

  const exportCols = () => drawnColumns(table).filter((c) => {
    const d = c.columnDef as GridColumn<T>;
    return !d.noExport && headerText(d) && c.id !== "actions";
  });
  const csvFile = (): MailFile => {
    const csv = toCsv(rows, exportCols().map((c) => c.columnDef as GridColumn<T>), (r, id) => r.getValue(id));
    return { name: `${exportName}.csv`, blob: new Blob([csv], { type: "text/csv;charset=utf-8" }) };
  };
  const downloadCsv = async () => {
    const f = csvFile();
    setSheet(null);
    try {
      if (mobileApp()) {
        if (!(await shareFiles([f], f.name))) toast(tx("Bu uygulama sürümü dosya paylaşamıyor; uygulamayı güncelleyin"), true);
        return;
      }
      const url = URL.createObjectURL(f.blob!);
      const a = document.createElement("a");
      a.href = url;
      a.download = f.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      toast(errText(e), true);
    }
  };

  const downloadXlsx = async () => {
    setSheet(null);
    const use = exportCols();
    try {
      const { id } = await api.post<{ id: string }>("/export/grid", {
        columns: use.map((c) => headerText(c.columnDef as GridColumn<T>)),
        widths: use.map((c) => c.getSize()),
        rows: rows.map((r) => use.map((c) => {
          const v = r.getValue(c.id);
          return isEmpty(v) ? null : typeof v === "number" ? v : String(v);
        })),
      });
      await download(`/export/grid/${id}?name=${encodeURIComponent(exportName ?? "liste")}`, `${exportName}.xlsx`);
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const saveView = () => {
    const name = viewName.trim();
    if (!name) return;
    const v: SavedView = { name, filters, sorting, visibility: layout.visibility, order: layout.order, pinning: layout.pinning };
    setViews((s) => [...s.filter((x) => x.name !== name), v]);
    setViewName("");
  };
  const openView = (v: SavedView) => {
    (p.onFiltersChange ?? setLocalFilters)(v.filters);
    setSorting(v.sorting);
    setLayout((s) => ({ ...s, visibility: v.visibility, order: v.order, pinning: v.pinning }));
    setSheet(null);
  };
  const resetLayout = () => setLayout((s) => ({ ...s, visibility: {}, order: [], pinning: { left: [] } }));
  const advanced = filters.find((f) => f.id === ADV);

  return (
    <>
      {p.toolbar && <div className="toolbar dg-extra">{p.toolbar}</div>}
      <div className="dg-bar">
        <label className="dg-search">
          <Icon name="search" />
          <input type="search" placeholder={tx("Listede ara…")} value={search} onChange={(e) => setSearch(e.target.value)} aria-label={tx("Listede ara")} />
          {search && <button className="dg-search-x" onClick={() => setSearch("")} aria-label={tx("Aramayı temizle")}><Icon name="x" size={14} /></button>}
        </label>
        <button className={`dg-tool${sheet === "filter" ? " on" : ""}${activeFilters ? " active" : ""}`} aria-expanded={sheet === "filter"}
          onClick={() => { setSheetCol(null); setSheet(sheet === "filter" ? null : "filter"); }}>
          <Icon name="filter" />{" "}{tx("Filtre")}{activeFilters > 0 && <span className="dg-count-badge">{activeFilters}</span>}
        </button>
        <button className={`dg-tool${advanced ? " active" : ""}`} onClick={() => setSheet("advanced")}>{tx("Gelişmiş")}</button>
        <button className="dg-tool" onClick={() => setSheet("columns")}>{tx("Sütunlar")}</button>
        {stateKey && (
          <div className="dg-menu-wrap">
            <button className="dg-tool" onClick={() => setSheet(sheet === "views" ? null : "views")} aria-haspopup="menu">{tx("Görünümler ▾")}</button>
            {sheet === "views" && (
              <div className="dg-menu card" role="menu">
                {views.map((v) => (
                  <div key={v.name} className="dg-view-row">
                    <button className="btn small" onClick={() => openView(v)}>{v.name}</button>
                    <button className="fs-close" aria-label={tx("{0} görünümünü sil", v.name)} onClick={() => setViews((s) => s.filter((x) => x !== v))}><Icon name="x" size={14} /></button>
                  </div>
                ))}
                {views.length === 0 && <span className="muted">{tx("Kayıtlı görünüm yok. Filtre, sıralama ve sütunlar birlikte kaydedilir.")}</span>}
                <div className="dg-view-row">
                  <input placeholder={tx("Görünüm adı")} aria-label={tx("Görünüm adı")} value={viewName} onChange={(e) => setViewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && saveView()} />
                  <button className="btn small primary" disabled={!viewName.trim()} onClick={saveView}>{tx("Kaydet")}</button>
                </div>
              </div>
            )}
          </div>
        )}
        {view === "cards" && sortable.length > 0 && (
          <label className={`dg-tool dg-sort${sortVal ? " active" : ""}`}>
            <Icon name="sort" />
            <select value={sortVal} aria-label={tx("Sırala")}
              onChange={(e) => {
                const [id, dir] = e.target.value.split(":");
                setSorting(id ? [{ id, desc: dir === "desc" }] : []);
              }}>
              <option value="">{tx("Sıralama")}</option>
              {sortable.map((c) => (
                <Fragment key={c.id}>
                  <option value={`${c.id}:asc`}>{tx("{0} (artan)", headerText(c.columnDef as GridColumn<T>))}</option>
                  <option value={`${c.id}:desc`}>{tx("{0} (azalan)", headerText(c.columnDef as GridColumn<T>))}</option>
                </Fragment>
              ))}
            </select>
          </label>
        )}
        {exportName && (
          <div className="dg-menu-wrap">
            <button className="dg-tool" onClick={() => setSheet(sheet === "export" ? null : "export")} aria-haspopup="menu">{tx("Paylaş ▾")}</button>
            {sheet === "export" && (
              <div className="dg-menu card" role="menu">
                <button role="menuitem" className="btn small" onClick={() => void downloadXlsx()}>{tx("Excel dosyası indir (.xlsx)")}</button>
                <button role="menuitem" className="btn small" onClick={() => void downloadCsv()}>{tx("CSV indir")}</button>
                {canMail && <button role="menuitem" className="btn small" onClick={() => { setSheet(null); setMail(csvFile()); }}>{tx("E-posta ile gönder")}</button>}
              </div>
            )}
          </div>
        )}
        <span className="dg-spacer" />
        <span className="dg-count" title={tx("Gösterilen / toplam kayıt")}>
          <b>{rows.length.toLocaleString(LOCALE)}</b>{rows.length !== p.data.length && <> / {p.data.length.toLocaleString(LOCALE)}</>}{" "}{tx("kayıt")}
        </span>
        <div className="seg small" role="radiogroup" aria-label={tx("Görünüm")}>
          <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")} title={tx("Kart görünümü")}>{tx("Liste")}</button>
          <button className={view === "table" ? "on" : ""} onClick={() => setView("table")} title={tx("Tablo görünümü")}>{tx("Tablo")}</button>
        </div>
      </div>
      {activeFilters > 0 && (
        <div className="dg-active" aria-label={tx("Etkin filtreler")}>
          {filters.map((f) => {
            const c = table.getColumn(f.id);
            if (!c) return null;
            if (f.id === ADV) {
              return (
                <span key={f.id} className="dg-fchip">
                  <button className="dg-fchip-main" title={tx("Filtreyi düzenle")} onClick={() => setSheet("advanced")}>
                    <span className="dg-fchip-k">{tx("Gelişmiş filtre")}</span>
                    <span className="dg-fchip-v">{advSummary(f.value as AdvValue)}</span>
                  </button>
                  <button className="dg-fchip-x" aria-label={tx("Filtreyi kaldır")} onClick={() => c.setFilterValue(undefined)}><Icon name="x" size={13} /></button>
                </span>
              );
            }
            return (
              <span key={f.id} className="dg-fchip">
                <button className="dg-fchip-main" title={tx("Filtreyi düzenle")} onClick={() => { setSheetCol(f.id); setSheet("filter"); }}>
                  <span className="dg-fchip-k">{headerText(c.columnDef as GridColumn<T>) || f.id}</span>
                  <span className="dg-fchip-v">{filterSummary(f.value as ColFilter)}</span>
                </button>
                <button className="dg-fchip-x" aria-label={tx("Filtreyi kaldır")} onClick={() => c.setFilterValue(undefined)}><Icon name="x" size={13} /></button>
              </span>
            );
          })}
          <button className="dg-link" onClick={() => { table.resetColumnFilters(); setSearch(""); }}>{tx("Tümünü temizle")}</button>
        </div>
      )}
      {p.selectable && rows.length > 0 && (view === "cards" || selectedCount > 0) && (
        <div className="dg-selbar">
          <label>
            <input type="checkbox" checked={table.getIsAllRowsSelected()}
              ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }}
              onChange={table.getToggleAllRowsSelectedHandler()} />
            {tx("Tümünü seç")}{" "}<span className="muted">({rows.length.toLocaleString(LOCALE)})</span>
          </label>
          {selectedCount > 0 && (
            <>
              <b>{tx("{0} seçili", selectedCount.toLocaleString(LOCALE))}</b>
              <button className="dg-link" onClick={invertSelection}>{tx("Tersine çevir")}</button>
              <button className="dg-link" onClick={() => table.setRowSelection({})}>{tx("Seçimi temizle")}</button>
              {p.selectionActions}
            </>
          )}
        </div>
      )}
      {sheet === "filter" && <FilterSheet key={sheetCol ?? ""} table={table} initialCol={sheetCol} onClose={() => setSheet(null)} onAdvanced={() => setSheet("advanced")} />}
      {sheet === "advanced" && <AdvancedFilter table={table} onClose={() => setSheet(null)} />}
      {sheet === "columns" && <ColumnsPanel table={table} onReset={resetLayout} onClose={() => setSheet(null)} />}
      {view === "cards" ? <CardView p={p} table={table} rows={rows} onCheck={(r, shift) => checkRow.current(r, shift)} /> : <TableView p={p} table={table} rows={rows} />}
      {mail && <MailDialog files={[mail]} subject={exportName ?? tx("Liste")} body={tx("{0} listesi ektedir ({1} satır).", exportName, rows.length)} onClose={() => setMail(null)} />}
    </>
  );
}

/** Modern list: one card per row, fields flow and wrap, so nothing needs horizontal scrolling. */
function CardView<T>({ p, table, rows, onCheck }: { p: GridProps<T>; table: Table<T>; rows: Row<T>[]; onCheck: (row: Row<T>, shift: boolean) => void }) {
  const [editing, setEditing] = useState<{ row: string; col: string } | null>(null);
  // Cards whose empty editable fields are shown (the ✎ button); others show only filled fields
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const toggleExpand = (id: string) => setExpanded((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const scrollRef = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => 120, overscan: 8 });
  const leaf = table.getVisibleLeafColumns().filter((c) => c.id !== "_sel");
  const role = (c: (typeof leaf)[number], i: number) => {
    const d = c.columnDef as GridColumn<T>;
    if (d.card) return d.card;
    if (c.id === "actions") return "actions";
    if (!leaf.some((x) => (x.columnDef as GridColumn<T>).card === "title") && i === 0) return "title";
    if (!leaf.some((x) => (x.columnDef as GridColumn<T>).card === "sub") && i === 1) return "sub";
    return "field";
  };
  const roles = leaf.map((c, i) => ({ c, role: role(c, i) }));
  const items = virt.getVirtualItems();

  return (
    <div className="dg-cards" ref={scrollRef}>
      <div style={{ height: virt.getTotalSize(), position: "relative" }}>
        {items.map((vi) => {
          const row = rows[vi.index];
          const cells = Object.fromEntries(row.getVisibleCells().map((c) => [c.column.id, c]));
          const render = (id: string) => flexRender(cells[id].column.columnDef.cell, cells[id].getContext());
          const editable = (id: string) => {
            const d = cells[id].column.columnDef as GridColumn<T>;
            return !!(d.edit && p.onEdit && (d.edit.canEdit?.(row.original) ?? true));
          };
          const value = (id: string) => {
            const d = cells[id].column.columnDef as GridColumn<T>;
            if (editing?.row === row.id && editing.col === id) {
              return <Editor row={row} col={d} colId={id}
                onDone={(v) => { setEditing(null); if (v !== undefined && v !== String(cells[id].getValue() ?? "")) p.onEdit!(row.original, id, v); }} />;
            }
            const ed = editable(id);
            return (
              <span className={ed ? "dgc-val editable" : "dgc-val"} style={d.cellStyle?.(row.original)}
                onClick={ed ? (e) => { e.stopPropagation(); p.onEditStart?.(); setEditing({ row: row.id, col: id }); } : undefined}
                title={ed ? tx("Değiştirmek için dokunun") : undefined}>
                {isEmpty(cells[id].getValue()) && ed ? "—" : render(id)}
              </span>
            );
          };
          const open = expanded.has(row.id);
          const show = (id: string) => !isEmpty(cells[id].getValue()) || (open && editable(id));
          const hiddenEdits = roles.some((r) => r.role !== "actions" && r.role !== "hide" && editable(r.c.id) && isEmpty(cells[r.c.id].getValue()));
          const accent = p.cardColor?.(row.original);
          const fields = roles.filter((r) => r.role === "field" && show(r.c.id));
          const badges = roles.filter((r) => r.role === "badge" && show(r.c.id));
          return (
            <div key={row.id} data-index={vi.index} ref={virt.measureElement}
              className={`dgc${row.getIsSelected() ? " selected" : ""}${p.onRowClick ? " clickable" : ""}`}
              style={{ position: "absolute", top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)`, ...p.rowStyle?.(row.original), ...(accent ? { borderLeftColor: accent } : {}), ...p.rowStyle?.(row.original) }}
              onClick={() => p.onRowClick?.(row.original)}>
              {p.cardLead?.(row.original)}
              <div className="dgc-body">
                <div className="dgc-head">
                  {p.selectable && (
                    <input type="checkbox" aria-label={tx("Seç")} checked={row.getIsSelected()} onChange={() => {}}
                      onClick={(e) => { e.stopPropagation(); onCheck(row, e.shiftKey); }} />
                  )}
                  <div className="dgc-titles">
                    {roles.filter((r) => r.role === "title").map(({ c }) => <b key={c.id} className="dgc-title">{value(c.id)}</b>)}
                    {roles.filter((r) => r.role === "sub" && show(r.c.id)).map(({ c }) => <div key={c.id} className="dgc-sub">{value(c.id)}</div>)}
                  </div>
                  {badges.length > 0 && (
                    <div className="dgc-badges">{badges.map(({ c }) => <span key={c.id} className="dgc-badge">{value(c.id)}</span>)}</div>
                  )}
                  {(hiddenEdits || open) && (
                    <button className={`dgc-more${open ? " on" : ""}`} aria-expanded={open}
                      title={open ? tx("Boş alanları gizle") : tx("Boş alanları da göster ve düzenle")}
                      onClick={(e) => { e.stopPropagation(); toggleExpand(row.id); }}>✎</button>
                  )}
                </div>
                {fields.length > 0 && (
                  <div className="dgc-grid">
                    {fields.map(({ c }) => (
                      <div key={c.id} className={`dgc-cell${cellText(cells[c.id].getValue()).length > 28 ? " wide" : ""}`}>
                        <span className="dgc-label">{headerText(c.columnDef as GridColumn<T>) || c.id}</span>
                        {value(c.id)}
                      </div>
                    ))}
                  </div>
                )}
                {roles.filter((r) => r.role === "actions").map(({ c }) => (
                  <div key={c.id} className="dgc-actions" onClick={(e) => e.stopPropagation()}>{render(c.id)}</div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {rows.length === 0 && <div className="muted" style={{ padding: 16 }}>{p.emptyText ?? tx("Kayıt yok.")}</div>}
    </div>
  );
}

