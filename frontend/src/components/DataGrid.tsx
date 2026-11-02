import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type FilterFn, type Row, type RowSelectionState, type SortingState, type ColumnFiltersState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";

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
};

export default function DataGrid<T>(p: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [localFilters, setLocalFilters] = useState<ColumnFiltersState>([]);
  const [localSel, setLocalSel] = useState<RowSelectionState>({});
  const filters = p.filters ?? localFilters;
  const selection = p.selection ?? localSel;
  const [editing, setEditing] = useState<{ row: string; col: string } | null>(null);
  const [openFilter, setOpenFilter] = useState<string | null>(null);

  const columns = useMemo<GridColumn<T>[]>(() => {
    const cols = p.columns.map((c) => ({ filterFn: multiFilter, ...c }));
    if (!p.selectable) return cols;
    return [{
      id: "_sel", size: 32, enableSorting: false, noFilter: true,
      header: ({ table }) => (
        <input type="checkbox" aria-label="Tümünü seç" checked={table.getIsAllRowsSelected()}
          ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }}
          onChange={table.getToggleAllRowsSelectedHandler()} />
      ),
      cell: ({ row }) => (
        <input type="checkbox" aria-label="Seç" checked={row.getIsSelected()} onClick={(e) => e.stopPropagation()} onChange={row.getToggleSelectedHandler()} />
      ),
    } as GridColumn<T>, ...cols];
  }, [p.columns, p.selectable]);

  const table = useReactTable({
    data: p.data, columns, getRowId: p.getRowId,
    state: { sorting, columnFilters: filters, rowSelection: selection },
    onSortingChange: setSorting,
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

  const scrollRef = useRef<HTMLDivElement>(null);
  const rh = p.rowHeight ?? 28;
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => rh, overscan: 20 });
  const items = virt.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBottom = items.length ? virt.getTotalSize() - items[items.length - 1].end : 0;
  const totalWidth = table.getTotalSize();
  const activeFilters = filters.length;

  return (
    <>
      <div className="toolbar">
        {p.toolbar}
        <span className="spacer" style={{ flex: 1 }} />
        <span><b>{rows.length.toLocaleString("tr-TR")}</b> / {p.data.length.toLocaleString("tr-TR")} satır</span>
        {activeFilters > 0 && (
          <button className="btn small" onClick={() => table.resetColumnFilters()}>Filtreleri temizle ({activeFilters})</button>
        )}
      </div>
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
                    <th key={h.id} style={{ width: h.getSize(), position: "sticky" }}>
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
function FilterPopup<T>({ table, colId, onClose }: { table: ReturnType<typeof useReactTable<T>>; colId: string; onClose: () => void }) {
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

  return (
    <div className="card" onClick={(e) => e.stopPropagation()}
      style={{ position: "absolute", top: "100%", left: 0, zIndex: 20, width: 260, fontWeight: 400, padding: 10 }}>
      <input placeholder="İçeren metin…" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && apply()} style={{ width: "100%", marginBottom: 6 }} autoFocus />
      <input placeholder="Değer ara…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: "100%", marginBottom: 6 }} />
      <div className="row" style={{ marginBottom: 4 }}>
        <button className="btn small" onClick={() => setSel(new Set([...sel, ...shown.map((s) => s[0])]))}>Tümü</button>
        <button className="btn small" onClick={() => { const n = new Set(sel); shown.forEach(([k]) => n.delete(k)); setSel(n); }}>Hiçbiri</button>
      </div>
      <div style={{ maxHeight: 220, overflow: "auto", border: "1px solid var(--border)", borderRadius: 4, padding: 4 }}>
        {shown.map(([k, n]) => (
          <label key={k} className="row" style={{ gap: 6, flexWrap: "nowrap", whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={sel.has(k)} onChange={(e) => { const s = new Set(sel); e.target.checked ? s.add(k) : s.delete(k); setSel(s); }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span>
            <span className="muted" style={{ marginLeft: "auto" }}>{n}</span>
          </label>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
        <button className="btn small" onClick={() => { column.setFilterValue(undefined); onClose(); }}>Temizle</button>
        <button className="btn small primary" onClick={apply}>Uygula</button>
      </div>
    </div>
  );
}
