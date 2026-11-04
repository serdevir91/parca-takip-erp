import type { ColumnDef, ColumnFiltersState, RowSelectionState, Table } from "@tanstack/react-table";
import type { CSSProperties, ReactNode } from "react";

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

export type CellChange<T> = { row: T; columnId: string; value: string };

export type GridProps<T> = {
  data: T[];
  columns: GridColumn<T>[];
  getRowId: (r: T) => string;
  onEdit?: (row: T, columnId: string, value: string) => void;
  /** A cell editor opened; the value in it may go stale while the user types. */
  onEditStart?: () => void;
  /** Paste, fill, replace and undo: several cells at once. Without it onEdit is called per cell. */
  onEditMany?: (changes: CellChange<T>[]) => void;
  onRowClick?: (row: T) => void;
  /** Table view: open the row on a single click. By default a click picks the cell and a double click opens the row. */
  openOnClick?: boolean;
  rowStyle?: (row: T) => CSSProperties | undefined;
  selectable?: boolean;
  selection?: RowSelectionState;
  onSelectionChange?: (s: RowSelectionState) => void;
  /** Buttons shown in the selection bar while rows are selected. */
  selectionActions?: ReactNode;
  filters?: ColumnFiltersState;
  onFiltersChange?: (f: ColumnFiltersState) => void;
  onVisibleRowsChange?: (rows: T[]) => void;
  /** Extra text rendered before the count (e.g. tree toggle). */
  toolbar?: ReactNode;
  rowHeight?: number;
  emptyText?: string;
  /** File name (without extension) for "Dışa aktar" and "E-posta ile gönder"; false hides both. */
  exportName?: string | false;
  /** Name under which column layout and saved views are kept on this device. Default: exportName. */
  stateKey?: string;
  /** Left edge of a card (tree indent, status colour strip). */
  cardLead?: (row: T) => ReactNode;
  /** Card accent colour (left border), e.g. the status colour. */
  cardColor?: (row: T) => string | undefined;
};

export const headerText = <T,>(c: GridColumn<T>): string => (typeof c.header === "string" ? c.header : "");
export const colId = <T,>(c: GridColumn<T>): string => c.id ?? ((c as { accessorKey?: string }).accessorKey ?? "");
export const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

/** Columns in the order they are drawn: frozen ones first. */
export const drawnColumns = <T,>(table: Table<T>) =>
  [...table.getLeftVisibleLeafColumns(), ...table.getCenterVisibleLeafColumns(), ...table.getRightVisibleLeafColumns()];

/** Freeze every column up to this one; freezing the same column again unfreezes. */
export function freezeTo<T>(table: Table<T>, id: string): void {
  const ids = drawnColumns(table).map((c) => c.id);
  const left = table.getState().columnPinning.left ?? [];
  table.setColumnPinning({ left: left[left.length - 1] === id ? [] : ids.slice(0, ids.indexOf(id) + 1) });
}

/** Column width that fits the header and the first rows, like a double click on a border in Excel. */
export function autofit<T>(table: Table<T>, id: string): void {
  const ctx = document.createElement("canvas").getContext("2d");
  const col = table.getColumn(id);
  if (!ctx || !col) return;
  ctx.font = "13px system-ui, sans-serif";
  let w = ctx.measureText(headerText(col.columnDef as GridColumn<T>)).width + 44;
  for (const r of table.getRowModel().rows.slice(0, 2000)) {
    const v = r.getValue(id);
    if (!isEmpty(v)) w = Math.max(w, ctx.measureText(String(v)).width + 18);
  }
  table.setColumnSizing((s) => ({ ...s, [id]: Math.min(640, Math.ceil(w)) }));
}
