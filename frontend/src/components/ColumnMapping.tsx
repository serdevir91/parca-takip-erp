import { tx, LOCALE } from "../api/i18n";

export type SheetLayout = {
  name: string;
  header: number;
  use: boolean;
  rows: number;
  matched: number;
  cols: Record<string, number>;
  headers: { col: number; title: string }[];
};

const columnName = (n: number): string => (n > 26 ? columnName(Math.floor((n - 1) / 26)) : "") + String.fromCharCode(65 + ((n - 1) % 26));

/** Which column of each sheet holds what. The server guesses; a change here reads the same file again. */
export default function ColumnMapping({ layouts, fields, busy, open, onChange }: {
  layouts: SheetLayout[];
  fields: [string, string][];
  busy: boolean;
  open: boolean;
  onChange: (layouts: SheetLayout[]) => void;
}) {
  const setLayout = (name: string, ch: Partial<SheetLayout>) => onChange(layouts.map((l) => (l.name === name ? { ...l, ...ch } : l)));
  const setColumn = (l: SheetLayout, field: string, col: number) => {
    const cols = { ...l.cols };
    if (col) cols[field] = col;
    else delete cols[field];
    setLayout(l.name, { cols, use: l.use || field === "part_no" });
  };
  return (
    <details className="imp-map" open={open} key={open ? "open" : "closed"}>
      <summary>{tx("Sütun eşleştirme")}</summary>
      {layouts.map((l) => (
        <div className="imp-map-sheet" key={l.name}>
          <label className="row" style={{ gap: 8 }}>
            <input type="checkbox" checked={l.use} disabled={busy} onChange={(e) => setLayout(l.name, { use: e.target.checked })} />
            <b>{l.name}</b>
            <span className="muted">{tx("{0} parça eşleşti", l.matched.toLocaleString(LOCALE))}</span>
          </label>
          <div className="imp-map-fields">
            {fields.map(([field, label]) => (
              <label key={field}>
                <span className="muted">{label}</span>
                <select value={l.cols[field] ?? 0} disabled={busy} onChange={(e) => setColumn(l, field, Number(e.target.value))}>
                  <option value={0}>{tx("Kullanma")}</option>
                  {l.headers.map((h) => <option key={h.col} value={h.col}>{columnName(h.col)}{h.title ? `: ${h.title}` : ""}</option>)}
                </select>
              </label>
            ))}
          </div>
        </div>
      ))}
    </details>
  );
}
