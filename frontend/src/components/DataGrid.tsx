import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type FilterFn, type Row, type RowSelectionState, type SortingState, type ColumnFiltersState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { mobileApp } from "../api/mobile";
import MailDialog, { shareFiles, type MailFile } from "./MailDialog";
import { errText, useToast } from "./Toast";

/** Column filter value: optional set of allowed display values plus a free-text "contains" filter. */
export type ColFilter = { values?: string[]; text?: string };

const norm = (s: string) => s.toLocaleLowerCase("tr-TR");
export const cellText = (v: unknown): string => (v === null || v === undefined || v === "" ? "(Boş)" : String(v));

export const multiFilter: FilterFn<any> = (row, colId, f: ColFilter) => {
  const t = cellText(row.getValue(colId));
  if (f.values && !f.values.includes(t)) return false;
  if (f.text && !norm(t).includes(norm(f.text))) return false;
  return true;
};
multiFilter.autoRemove = (f?: ColFilter) => !f || (!f.values && !f.text);

export type GridColumn<T> = ColumnDef<T, any> & {
  /** Inline editor. Return undefined for read-only rows. */
  edit?: { type: "text" | "number" | "select"; options?: string[] | ((row: T) => string[]); canEdit?: (row: T) => boolean };
  cellStyle?: (row: T) => CSSProperties | undefined;
  noFilter?: boolean;
  /** Place in the card (list) view. Default: first column = title, second = sub, "actions" column = buttons,
   *  the rest are label/value fields (empty values skipped). */
  card?: "title" | "sub" | "badge" | "field" | "actions" | "hide";
  /** Leave out of the CSV export (action buttons, icons). */
  noExport?: boolean;
};

type Props<T> = {
  data: T[];
  columns: GridColumn<T>[];
  getRowId: (r: T) => string;
  onEdit?: (row: T, columnId: string, value: string) => void;
  onRowClick?: (row: T) => void;
  rowStyle?: (row: T) => CSSProperties | undefined;
  selectable?: boolean;
  selection?: RowSelectionState;
  onSelectionChange?: (s: RowSelectionState) => void;
  filters?: ColumnFiltersState;
  onFiltersChange?: (f: ColumnFiltersState) => void;
  onVisibleRowsChange?: (rows: T[]) => void;
  /** Extra text rendered before the count (e.g. tree toggle). */
  toolbar?: ReactNode;
  rowHeight?: number;
  emptyText?: string;
  /** File name (without extension) for "Dışa aktar" (CSV) and "E-posta ile gönder"; false hides both. */
  exportName?: string | false;
  /** Left edge of a card (tree indent, status colour strip). */
  cardLead?: (row: T) => ReactNode;
  /** Card accent colour (left border), e.g. the status colour. */
  cardColor?: (row: T) => string | undefined;
};

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
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new CustomEvent("dg-view", { detail: v }));
  };
  return [view, set];
}

const headerText = <T,>(c: GridColumn<T>): string => (typeof c.header === "string" ? c.header : "");
const colId = <T,>(c: GridColumn<T>): string => c.id ?? ((c as { accessorKey?: string }).accessorKey ?? "");
const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

const ICONS = {
  search: "M10.5 4a6.5 6.5 0 1 0 4.03 11.6l4.43 4.43 1.06-1.06-4.43-4.43A6.5 6.5 0 0 0 10.5 4Zm0 1.5a5 5 0 1 1 0 10 5 5 0 0 1 0-10Z",
  filter: "M3 5h18l-7 8.2V19l-4 2v-7.8L3 5Zm3.3 1.5 5.2 6.1v5.9l1-.5v-5.4l5.2-6.1H6.3Z",
  x: "m6.4 5.3 5.6 5.6 5.6-5.6 1.1 1.1-5.6 5.6 5.6 5.6-1.1 1.1-5.6-5.6-5.6 5.6-1.1-1.1 5.6-5.6-5.6-5.6 1.1-1.1Z",
  sort: "M7 4 3 8.5h3V20h2V8.5h3L7 4Zm10 16 4-4.5h-3V4h-2v11.5h-3l4 4.5Z",
} as const;
export function Icon({ name, size = 16 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg className="dg-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d={ICONS[name]} />
    </svg>
  );
}

/** Short text for an active column filter chip: «Durum: Tamamlandı», «Malzeme: 3 değer», «Not: "abc"» */
function filterSummary(f: ColFilter): string {
  const parts: string[] = [];
  if (f.text) parts.push(`"${f.text}"`);
  if (f.values) parts.push(f.values.length === 1 ? f.values[0] || "(boş)" : `${f.values.length.toLocaleString("tr-TR")} değer`);
  return parts.join(" + ");
}

function globalMatch(row: Row<any>, id: string, value: string): boolean {
  const v = row.getValue(id);
  return !isEmpty(v) && norm(String(v)).includes(norm(value));
}

export function toCsv<R>(rows: R[], cols: GridColumn<any>[], get: (r: R, id: string) => unknown): string {
  const esc = (v: unknown) => {
    const t = isEmpty(v) ? "" : typeof v === "number" ? String(v).replace(".", ",") : String(v);
    return /[";\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const use = cols.filter((c) => !c.noExport && headerText(c) && colId(c) !== "actions");
  // Semicolon + BOM: Turkish Excel opens it with the right columns and characters
  return "\ufeff" + [use.map((c) => esc(headerText(c))).join(";"),
    ...rows.map((r) => use.map((c) => esc(get(r, colId(c)))).join(";"))].join("\r\n");
}

export default function DataGrid<T>(p: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [localFilters, setLocalFilters] = useState<ColumnFiltersState>([]);
  const [localSel, setLocalSel] = useState<RowSelectionState>({});
  const [search, setSearch] = useState("");
  const filters = p.filters ?? localFilters;
  const selection = p.selection ?? localSel;
  const [view, setView] = useGridView();
  const [sheet, setSheet] = useState<"filter" | "export" | null>(null);
  const [sheetCol, setSheetCol] = useState<string | null>(null);
  const [mail, setMail] = useState<MailFile | null>(null);
  const toast = useToast();
  // Checkbox click: plain toggles one row, Shift also sets every row back to the last clicked one
  const lastChecked = useRef<string | null>(null);
  const checkRow = useRef<(row: Row<T>, shift: boolean) => void>(() => {});

  const columns = useMemo<GridColumn<T>[]>(() => {
    const cols = p.columns.map((c) => ({ filterFn: multiFilter, ...c }));
    if (!p.selectable) return cols;
    return [{
      id: "_sel", size: 32, enableSorting: false, noFilter: true, noExport: true, card: "hide",
      header: ({ table }) => (
        <input type="checkbox" aria-label="Tümünü seç" checked={table.getIsAllRowsSelected()}
          ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }}
          onChange={table.getToggleAllRowsSelectedHandler()} />
      ),
      cell: ({ row }) => (
        <input type="checkbox" aria-label="Seç" checked={row.getIsSelected()} onChange={() => {}}
          onClick={(e) => { e.stopPropagation(); checkRow.current(row, e.shiftKey); }} />
      ),
    } as GridColumn<T>, ...cols];
  }, [p.columns, p.selectable]);

  const table = useReactTable({
    data: p.data, columns, getRowId: p.getRowId,
    state: { sorting, columnFilters: filters, rowSelection: selection, globalFilter: search },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    globalFilterFn: globalMatch,
    getColumnCanGlobalFilter: (c) => c.id !== "_sel" && c.id !== "actions",
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

  const csvFile = (): MailFile => {
    const csv = toCsv(rows, p.columns, (r, id) => r.getValue(id));
    return { name: `${exportName}.csv`, blob: new Blob([csv], { type: "text/csv;charset=utf-8" }) };
  };
  const downloadCsv = async () => {
    const f = csvFile();
    setSheet(null);
    try {
      if (mobileApp()) {
        if (!(await shareFiles([f], f.name))) toast("Bu uygulama sürümü dosya paylaşamıyor; uygulamayı güncelleyin", true);
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

  return (
    <>
      {p.toolbar && <div className="toolbar dg-extra">{p.toolbar}</div>}
      <div className="dg-bar">
        <label className="dg-search">
          <Icon name="search" />
          <input type="search" placeholder="Listede ara…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Listede ara" />
          {search && <button className="dg-search-x" onClick={() => setSearch("")} aria-label="Aramayı temizle"><Icon name="x" size={14} /></button>}
        </label>
        <button className={`dg-tool${sheet === "filter" ? " on" : ""}${activeFilters ? " active" : ""}`} aria-expanded={sheet === "filter"}
          onClick={() => { setSheetCol(null); setSheet(sheet === "filter" ? null : "filter"); }}>
          <Icon name="filter" /> Filtre{activeFilters > 0 && <span className="dg-count-badge">{activeFilters}</span>}
        </button>
        {view === "cards" && sortable.length > 0 && (
          <label className={`dg-tool dg-sort${sortVal ? " active" : ""}`}>
            <Icon name="sort" />
            <select value={sortVal} aria-label="Sırala"
              onChange={(e) => {
                const [id, dir] = e.target.value.split(":");
                setSorting(id ? [{ id, desc: dir === "desc" }] : []);
              }}>
              <option value="">Sıralama</option>
              {sortable.map((c) => (
                <Fragment key={c.id}>
                  <option value={`${c.id}:asc`}>{headerText(c.columnDef as GridColumn<T>)} (artan)</option>
                  <option value={`${c.id}:desc`}>{headerText(c.columnDef as GridColumn<T>)} (azalan)</option>
                </Fragment>
              ))}
            </select>
          </label>
        )}
        {exportName && (
          <div className="dg-menu-wrap">
            <button className="dg-tool" onClick={() => setSheet(sheet === "export" ? null : "export")} aria-haspopup="menu">Paylaş ▾</button>
            {sheet === "export" && (
              <div className="dg-menu card" role="menu">
                <button role="menuitem" className="btn small" onClick={() => void downloadCsv()}>Listeyi indir (CSV, Excel'de açılır)</button>
                <button role="menuitem" className="btn small" onClick={() => { setSheet(null); setMail(csvFile()); }}>E-posta ile gönder</button>
              </div>
            )}
          </div>
        )}
        <span className="dg-spacer" />
        <span className="dg-count" title="Gösterilen / toplam kayıt">
          <b>{rows.length.toLocaleString("tr-TR")}</b>{rows.length !== p.data.length && <> / {p.data.length.toLocaleString("tr-TR")}</>} kayıt
        </span>
        <div className="seg small" role="radiogroup" aria-label="Görünüm">
          <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")} title="Kart görünümü">Liste</button>
          <button className={view === "table" ? "on" : ""} onClick={() => setView("table")} title="Tablo görünümü">Tablo</button>
        </div>
      </div>
      {activeFilters > 0 && (
        <div className="dg-active" aria-label="Etkin filtreler">
          {filters.map((f) => {
            const c = table.getColumn(f.id);
            if (!c) return null;
            return (
              <span key={f.id} className="dg-fchip">
                <button className="dg-fchip-main" title="Filtreyi düzenle" onClick={() => { setSheetCol(f.id); setSheet("filter"); }}>
                  <span className="dg-fchip-k">{headerText(c.columnDef as GridColumn<T>) || f.id}</span>
                  <span className="dg-fchip-v">{filterSummary(f.value as ColFilter)}</span>
                </button>
                <button className="dg-fchip-x" aria-label="Filtreyi kaldır" onClick={() => c.setFilterValue(undefined)}><Icon name="x" size={13} /></button>
              </span>
            );
          })}
          <button className="dg-link" onClick={() => { table.resetColumnFilters(); setSearch(""); }}>Tümünü temizle</button>
        </div>
      )}
      {p.selectable && rows.length > 0 && (view === "cards" || selectedCount > 0) && (
        <div className="dg-selbar">
          <label>
            <input type="checkbox" checked={table.getIsAllRowsSelected()}
              ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }}
              onChange={table.getToggleAllRowsSelectedHandler()} />
            Tümünü seç <span className="muted">({rows.length.toLocaleString("tr-TR")})</span>
          </label>
          {selectedCount > 0 && (
            <>
              <b>{selectedCount.toLocaleString("tr-TR")} seçili</b>
              <button className="dg-link" onClick={invertSelection}>Tersine çevir</button>
              <button className="dg-link" onClick={() => table.setRowSelection({})}>Seçimi temizle</button>
            </>
          )}
        </div>
      )}
      {sheet === "filter" && <FilterSheet key={sheetCol ?? ""} table={table} initialCol={sheetCol} onClose={() => setSheet(null)} />}
      {view === "cards" ? <CardView p={p} table={table} rows={rows} onCheck={(r, shift) => checkRow.current(r, shift)} /> : <TableView p={p} table={table} rows={rows} columns={columns} />}
      {mail && <MailDialog files={[mail]} subject={exportName ?? "Liste"} body={`${exportName} listesi ektedir (${rows.length} satır).`} onClose={() => setMail(null)} />}
    </>
  );
}

type ViewProps<T> = { p: Props<T>; table: ReturnType<typeof useReactTable<T>>; rows: Row<T>[] };

function TableView<T>({ p, table, rows, columns }: ViewProps<T> & { columns: GridColumn<T>[] }) {
  const [editing, setEditing] = useState<{ row: string; col: string } | null>(null);
  const [openFilter, setOpenFilter] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rh = p.rowHeight ?? 28;
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => rh, overscan: 20 });
  const items = virt.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBottom = items.length ? virt.getTotalSize() - items[items.length - 1].end : 0;
  const totalWidth = table.getTotalSize();

  return (
      <div className="dg" ref={scrollRef} onClick={() => setOpenFilter(null)}>
        <table style={{ width: totalWidth }}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const col = h.column.columnDef as GridColumn<T>;
                  const f = h.column.getFilterValue() as ColFilter | undefined;
                  const sorted = h.column.getIsSorted();
                  return (
                    <th key={h.id} className={openFilter === h.id ? "fopen" : undefined} style={{ width: h.getSize(), position: "sticky" }}>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <span style={{ cursor: h.column.getCanSort() ? "pointer" : "default", overflow: "hidden", textOverflow: "ellipsis" }}
                          onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}
                        </span>
                        {!col.noFilter && h.column.id !== "_sel" && (
                          <button className={"btn small" + (f ? " primary" : "")} style={{ padding: "0 5px", marginLeft: "auto" }}
                            title="Filtre" onClick={(e) => { e.stopPropagation(); setOpenFilter(openFilter === h.id ? null : h.id); }}>▾</button>
                        )}
                      </div>
                      {openFilter === h.id && (
                        <FilterPopup table={table} colId={h.column.id} onClose={() => setOpenFilter(null)} />
                      )}
                      {h.column.getCanResize() && (
                        <div className="resizer" onMouseDown={h.getResizeHandler()} onTouchStart={h.getResizeHandler()} onClick={(e) => e.stopPropagation()} />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 && <tr style={{ height: padTop }}><td colSpan={columns.length} style={{ border: 0, padding: 0 }} /></tr>}
            {items.map((vi) => {
              const row = rows[vi.index];
              return (
                <tr key={row.id} className={row.getIsSelected() ? "selected" : ""} style={{ height: rh, ...p.rowStyle?.(row.original) }}
                  onClick={() => p.onRowClick?.(row.original)}>
                  {row.getVisibleCells().map((cell) => {
                    const col = cell.column.columnDef as GridColumn<T>;
                    const canEdit = !!(col.edit && p.onEdit && (col.edit.canEdit?.(row.original) ?? true));
                    const isEditing = editing?.row === row.id && editing.col === cell.column.id;
                    return (
                      <td key={cell.id} className={canEdit ? "editable" : ""} style={{ width: cell.column.getSize(), ...col.cellStyle?.(row.original) }}
                        title={typeof cell.getValue() === "string" ? (cell.getValue() as string) : undefined}
                        onDoubleClick={(e) => { if (canEdit) { e.stopPropagation(); setEditing({ row: row.id, col: cell.column.id }); } }}>
                        {isEditing ? (
                          <Editor row={row} col={col} colId={cell.column.id}
                            onDone={(v) => { setEditing(null); if (v !== undefined && v !== String(cell.getValue() ?? "")) p.onEdit!(row.original, cell.column.id, v); }} />
                        ) : (
                          flexRender(cell.column.columnDef.cell, cell.getContext())
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {padBottom > 0 && <tr style={{ height: padBottom }}><td colSpan={columns.length} style={{ border: 0, padding: 0 }} /></tr>}
          </tbody>
        </table>
        {rows.length === 0 && <div className="muted" style={{ padding: 16 }}>{p.emptyText ?? "Kayıt yok."}</div>}
      </div>
  );
}

/** Modern list: one card per row, fields flow and wrap, so nothing needs horizontal scrolling. */
function CardView<T>({ p, table, rows, onCheck }: ViewProps<T> & { onCheck: (row: Row<T>, shift: boolean) => void }) {
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
                onClick={ed ? (e) => { e.stopPropagation(); setEditing({ row: row.id, col: id }); } : undefined}
                title={ed ? "Değiştirmek için dokunun" : undefined}>
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
                    <input type="checkbox" aria-label="Seç" checked={row.getIsSelected()} onChange={() => {}}
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
                      title={open ? "Boş alanları gizle" : "Boş alanları da göster ve düzenle"}
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
      {rows.length === 0 && <div className="muted" style={{ padding: 16 }}>{p.emptyText ?? "Kayıt yok."}</div>}
    </div>
  );
}

/** Filter panel for both views: columns on the left (on phones: first step), the chosen column's values on the right. */
function FilterSheet<T>({ table, initialCol, onClose }: { table: ReturnType<typeof useReactTable<T>>; initialCol: string | null; onClose: () => void }) {
  const cols = table.getAllLeafColumns().filter((c) => {
    const d = c.columnDef as GridColumn<T>;
    return !d.noFilter && c.id !== "_sel" && c.id !== "actions" && headerText(d);
  });
  const [col, setCol] = useState<string | null>(initialCol);
  const [q, setQ] = useState("");
  const shownCols = cols.filter((c) => !q || norm(headerText(c.columnDef as GridColumn<T>)).includes(norm(q)));
  const active = table.getState().columnFilters.length;
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <>
      <div className="fs-backdrop" onClick={onClose} />
      <div className={`fs card${col ? " has-col" : ""}`} role="dialog" aria-label="Filtreler">
        <div className="fs-head">
          {col && <button className="fs-back" onClick={() => setCol(null)} aria-label="Sütunlara dön">‹</button>}
          <b>{col ? headerText(table.getColumn(col)!.columnDef as GridColumn<T>) : "Filtreler"}</b>
          {active > 0 && <span className="dg-count-badge">{active}</span>}
          <span className="dg-spacer" />
          {active > 0 && <button className="dg-link" onClick={() => table.resetColumnFilters()}>Tümünü temizle</button>}
          <button className="fs-close" onClick={onClose} aria-label="Kapat"><Icon name="x" /></button>
        </div>
        <div className="fs-body">
          <div className="fs-cols">
            {cols.length > 8 && (
              <label className="dg-search fs-colsearch">
                <Icon name="search" size={14} />
                <input type="search" placeholder="Sütun ara…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Sütun ara" />
              </label>
            )}
            {shownCols.map((c) => {
              const f = c.getFilterValue() as ColFilter | undefined;
              return (
                <button key={c.id} className={`fs-col${col === c.id ? " on" : ""}${f ? " active" : ""}`} onClick={() => setCol(c.id)}>
                  <span className="fs-col-name">{headerText(c.columnDef as GridColumn<T>)}</span>
                  {f ? <span className="fs-col-val">{filterSummary(f)}</span> : <span className="fs-col-chev">›</span>}
                </button>
              );
            })}
          </div>
          <div className="fs-vals">
            {col ? (
              <FilterPopup key={col} table={table} colId={col} inline onClose={() => setCol(null)} />
            ) : (
              <div className="fs-hint muted">Filtrelemek için soldan bir sütun seçin.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function Editor<T>({ row, col, colId, onDone }: { row: Row<T>; col: GridColumn<T>; colId: string; onDone: (v?: string) => void }) {
  const initial = String(row.getValue(colId) ?? "");
  const [v, setV] = useState(initial);
  const e = col.edit!;
  const opts = typeof e.options === "function" ? e.options(row.original) : e.options;
  const key = (ev: React.KeyboardEvent) => {
    if (ev.key === "Enter") onDone(v);
    if (ev.key === "Escape") onDone(undefined);
  };
  if (e.type === "select") {
    return (
      <select autoFocus value={v} onChange={(ev) => onDone(ev.target.value)} onBlur={() => onDone(undefined)} onKeyDown={key} onClick={(ev) => ev.stopPropagation()}>
        {!opts?.includes(v) && <option value={v}>{v || "—"}</option>}
        {opts?.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
      </select>
    );
  }
  return (
    <input autoFocus type={e.type === "number" ? "number" : "text"} value={v} onChange={(ev) => setV(ev.target.value)}
      onBlur={() => onDone(v)} onKeyDown={key} onClick={(ev) => ev.stopPropagation()} />
  );
}

/** Excel-like filter: text contains + checkbox list of distinct values (computed on rows that pass the OTHER filters). */
function FilterPopup<T>({ table, colId, onClose, inline }: { table: ReturnType<typeof useReactTable<T>>; colId: string; onClose: () => void; inline?: boolean }) {
  const column = table.getColumn(colId)!;
  const cur = (column.getFilterValue() as ColFilter | undefined) ?? {};
  const [text, setText] = useState(cur.text ?? "");
  const [search, setSearch] = useState("");
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    const others = table.getState().columnFilters.filter((f) => f.id !== colId);
    for (const r of table.getCoreRowModel().rows) {
      if (!others.every((f) => multiFilter(r as Row<any>, f.id, f.value as ColFilter, () => {}))) continue;
      const t = cellText(r.getValue(colId));
      m.set(t, (m.get(t) ?? 0) + 1);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], "tr-TR", { numeric: true }));
  }, [table, colId]);
  const [sel, setSel] = useState<Set<string>>(new Set(cur.values ?? counts.map((c) => c[0])));
  const shown = counts.filter(([k]) => !search || norm(k).includes(norm(search)));

  const apply = () => {
    const all = sel.size === counts.length || counts.every(([k]) => sel.has(k));
    const next: ColFilter = {};
    if (!all) next.values = [...sel];
    if (text.trim()) next.text = text.trim();
    column.setFilterValue(next.values || next.text ? next : undefined);
    onClose();
  };

  const allOn = shown.length > 0 && shown.every(([k]) => sel.has(k));
  const toggle = (k: string, on: boolean) => { const n = new Set(sel); if (on) n.add(k); else n.delete(k); setSel(n); };
  const max = Math.max(1, ...counts.map((c) => c[1]));

  return (
    <div className={`fp${inline ? " inline" : " pop card"}`} onClick={(e) => e.stopPropagation()}>
      <div className="fp-sec">
        <span className="fp-label">Metin içerir</span>
        <label className="dg-search">
          <Icon name="filter" size={14} />
          <input placeholder="örnek: 1250 veya kaynak" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && apply()} autoFocus={!inline || matchMedia("(pointer: fine)").matches} />
        </label>
      </div>
      <div className="fp-sec">
        <div className="fp-row">
          <span className="fp-label">Değerler <span className="muted">({sel.size.toLocaleString("tr-TR")} / {counts.length.toLocaleString("tr-TR")} seçili)</span></span>
          <button className="dg-link" onClick={() => {
            const n = new Set(sel);
            shown.forEach(([k]) => (allOn ? n.delete(k) : n.add(k)));
            setSel(n);
          }}>{allOn ? "Hiçbirini seçme" : "Tümünü seç"}</button>
        </div>
        {counts.length > 6 && (
          <label className="dg-search">
            <Icon name="search" size={14} />
            <input type="search" placeholder="Değer ara…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
        )}
        <div className="fp-list">
          {shown.map(([k, n]) => (
            <label key={k} className={`fp-opt${sel.has(k) ? " on" : ""}`}>
              <input type="checkbox" checked={sel.has(k)} onChange={(e) => toggle(k, e.target.checked)} />
              <span className="fp-opt-k" title={k}>{k}</span>
              <span className="fp-opt-n" style={{ "--w": `${Math.round((n / max) * 100)}%` } as CSSProperties}>{n.toLocaleString("tr-TR")}</span>
            </label>
          ))}
          {shown.length === 0 && <div className="muted fp-empty">Eşleşen değer yok</div>}
        </div>
      </div>
      <div className="fp-foot">
        <button className="btn" onClick={() => { column.setFilterValue(undefined); onClose(); }}>Temizle</button>
        <button className="btn primary" onClick={apply}>Uygula</button>
      </div>
    </div>
  );
}
