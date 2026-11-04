import type { Column, ColumnFilter, FilterFn, Row, Table } from "@tanstack/react-table";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { autofit, freezeTo, headerText, isEmpty, type GridColumn } from "./dgTypes";

export type Join = "and" | "or";
export type CondOp = "contains" | "notContains" | "eq" | "ne" | "starts" | "ends" | "in" | "notIn"
  | "gt" | "gte" | "lt" | "lte" | "between" | "empty" | "notEmpty";
export type Cond = { op: CondOp; a?: string; b?: string };
/** Column filter value: allowed display values, a free-text "contains" and up to two conditions. */
export type ColFilter = { values?: string[]; text?: string; conds?: Cond[]; join?: Join };
export type AdvRule = Cond & { col: string };
export type AdvGroup = { join: Join; rules: AdvRule[] };
export type AdvValue = { join: Join; groups: AdvGroup[] };
/** Hidden column that carries the rule tree of the advanced filter. */
export const ADV = "_adv";

export const OPS: { op: CondOp; label: string; args: 0 | 1 | 2 }[] = [
  { op: "contains", label: "içerir", args: 1 },
  { op: "notContains", label: "içermez", args: 1 },
  { op: "eq", label: "eşittir", args: 1 },
  { op: "ne", label: "eşit değil", args: 1 },
  { op: "starts", label: "ile başlar", args: 1 },
  { op: "ends", label: "ile biter", args: 1 },
  { op: "in", label: "listede (virgülle ayırın)", args: 1 },
  { op: "notIn", label: "listede değil", args: 1 },
  { op: "gt", label: "büyüktür", args: 1 },
  { op: "gte", label: "büyük veya eşit", args: 1 },
  { op: "lt", label: "küçüktür", args: 1 },
  { op: "lte", label: "küçük veya eşit", args: 1 },
  { op: "between", label: "arasında", args: 2 },
  { op: "empty", label: "boş", args: 0 },
  { op: "notEmpty", label: "dolu", args: 0 },
];
const argsOf = (op: CondOp) => OPS.find((o) => o.op === op)?.args ?? 1;
const condUsed = (c: Cond) => argsOf(c.op) === 0 || !!(c.a ?? "").trim();

export const norm = (s: string) => s.toLocaleLowerCase("tr-TR");
export const cellText = (v: unknown): string => (isEmpty(v) ? "(Boş)" : String(v));

/** "1.250,5", "1250.5" and "1,5" read as numbers; anything else is null. */
export function parseNum(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const s = String(v ?? "").trim().replace(/\s/g, "");
  if (!s) return null;
  let t = s.replace(",", ".");
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) t = s.replace(/\./g, "").replace(",", ".");
  else if (/^-?\d{1,3}(,\d{3})+\.\d+$/.test(s)) t = s.replace(/,/g, "");
  return /^-?\d*\.?\d+$/.test(t) ? Number(t) : null;
}

const compare = (v: unknown, w: string): number => {
  const x = parseNum(v);
  const y = parseNum(w);
  if (x !== null && y !== null) return x - y;
  return String(v).localeCompare(w, "tr-TR", { numeric: true, sensitivity: "base" });
};

export function matchCond(v: unknown, c: Cond): boolean {
  const t = isEmpty(v) ? "" : norm(String(v));
  const a = norm((c.a ?? "").trim());
  const list = () => a.split(",").map((x) => x.trim()).filter(Boolean);
  switch (c.op) {
    case "contains": return t.includes(a);
    case "notContains": return !t.includes(a);
    case "eq": return t === a || (t !== "" && compare(v, c.a ?? "") === 0);
    case "ne": return !(t === a || (t !== "" && compare(v, c.a ?? "") === 0));
    case "starts": return t.startsWith(a);
    case "ends": return t.endsWith(a);
    case "in": return list().includes(t);
    case "notIn": return !list().includes(t);
    case "empty": return t === "";
    case "notEmpty": return t !== "";
  }
  if (t === "") return false;
  switch (c.op) {
    case "gt": return compare(v, c.a ?? "") > 0;
    case "gte": return compare(v, c.a ?? "") >= 0;
    case "lt": return compare(v, c.a ?? "") < 0;
    case "lte": return compare(v, c.a ?? "") <= 0;
    case "between": return compare(v, c.a ?? "") >= 0 && compare(v, c.b ?? "") <= 0;
  }
  return false;
}

const joined = <X,>(list: X[], join: Join | undefined, hit: (x: X) => boolean) => (join === "or" ? list.some(hit) : list.every(hit));

export const multiFilter: FilterFn<any> = (row, colId, f: ColFilter) => {
  const v = row.getValue(colId);
  const t = cellText(v);
  if (f.values && !f.values.includes(t)) return false;
  if (f.text && !norm(t).includes(norm(f.text))) return false;
  if (f.conds?.length && !joined(f.conds, f.join, (c) => matchCond(v, c))) return false;
  return true;
};
multiFilter.autoRemove = (f?: ColFilter) => !f || (!f.values && !f.text && !f.conds?.length);

export const advFilter: FilterFn<any> = (row, _id, f: AdvValue) =>
  joined(f.groups, f.join, (g) => joined(g.rules, g.join, (r) => matchCond(row.getValue(r.col), r)));
advFilter.autoRemove = (f?: AdvValue) => !f?.groups?.length;

const passes = (row: Row<any>, f: ColumnFilter) => (f.id === ADV ? advFilter : multiFilter)(row, f.id, f.value, () => {});

const condText = (c: Cond) => {
  const label = OPS.find((o) => o.op === c.op)?.label ?? "";
  const n = argsOf(c.op);
  return n === 0 ? label : n === 2 ? `${c.a} – ${c.b}` : `${label} "${c.a}"`;
};

/** Short text for an active column filter chip: «Durum: Tamamlandı», «Malzeme: 3 değer», «Not: içerir "abc"» */
export function filterSummary(f: ColFilter): string {
  const parts: string[] = [];
  if (f.text) parts.push(`"${f.text}"`);
  if (f.conds?.length) parts.push(f.conds.map(condText).join(f.join === "or" ? " veya " : " ve "));
  if (f.values) parts.push(f.values.length === 1 ? f.values[0] || "(boş)" : `${f.values.length.toLocaleString("tr-TR")} değer`);
  return parts.join(" + ");
}

export const advSummary = (f: AdvValue) => {
  const n = f.groups.reduce((s, g) => s + g.rules.length, 0);
  return `${n.toLocaleString("tr-TR")} kural`;
};

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

const filterable = <T,>(table: Table<T>): Column<T, unknown>[] => table.getAllLeafColumns().filter((c) => {
  const d = c.columnDef as GridColumn<T>;
  return !d.noFilter && c.id !== "_sel" && c.id !== "actions" && c.id !== ADV && headerText(d);
});

/** Filter panel for both views: columns on the left (on phones: first step), the chosen column's values on the right. */
export function FilterSheet<T>({ table, initialCol, onClose, onAdvanced }: { table: Table<T>; initialCol: string | null; onClose: () => void; onAdvanced: () => void }) {
  const cols = filterable(table);
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
          <button className="dg-link" onClick={onAdvanced}>Gelişmiş filtre</button>
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

function CondEdit({ c, onChange, onEnter, autoFocus, list }: { c: Cond; onChange: (c: Cond) => void; onEnter?: () => void; autoFocus?: boolean; list?: string }) {
  const n = argsOf(c.op);
  const input = (k: "a" | "b", placeholder: string) => (
    <input value={c[k] ?? ""} placeholder={placeholder} list={list} autoFocus={autoFocus && k === "a"} aria-label="Filtre değeri"
      onChange={(e) => onChange({ ...c, [k]: e.target.value })} onKeyDown={(e) => e.key === "Enter" && onEnter?.()} />
  );
  return (
    <div className="fp-cond">
      <select value={c.op} aria-label="Koşul" onChange={(e) => onChange({ ...c, op: e.target.value as CondOp })}>
        {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
      </select>
      {n >= 1 && input("a", n === 2 ? "en az" : "değer")}
      {n === 2 && input("b", "en çok")}
    </div>
  );
}

function JoinPick({ value, onChange, label }: { value: Join; onChange: (j: Join) => void; label?: string }) {
  return (
    <div className="seg small" role="radiogroup" aria-label={label ?? "Bağlaç"}>
      <button type="button" className={value === "and" ? "on" : ""} onClick={() => onChange("and")}>VE</button>
      <button type="button" className={value === "or" ? "on" : ""} onClick={() => onChange("or")}>VEYA</button>
    </div>
  );
}

const BLANK: Cond = { op: "contains", a: "", b: "" };

/** Excel-like filter: conditions + checkbox list of distinct values (computed on rows that pass the OTHER filters). */
export function FilterPopup<T>({ table, colId, onClose, inline }: { table: Table<T>; colId: string; onClose: () => void; inline?: boolean }) {
  const column = table.getColumn(colId)!;
  const cur = (column.getFilterValue() as ColFilter | undefined) ?? {};
  const start = cur.conds?.length ? cur.conds : cur.text ? [{ op: "contains" as const, a: cur.text }] : [];
  const [c1, setC1] = useState<Cond>(start[0] ?? BLANK);
  const [c2, setC2] = useState<Cond>(start[1] ?? BLANK);
  const [two, setTwo] = useState(start.length > 1);
  const [join, setJoin] = useState<Join>(cur.join ?? "and");
  const [search, setSearch] = useState("");
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    const others = table.getState().columnFilters.filter((f) => f.id !== colId);
    for (const r of table.getCoreRowModel().rows) {
      if (!others.every((f) => passes(r as Row<any>, f))) continue;
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
    const conds = [c1, ...(two ? [c2] : [])].filter(condUsed);
    if (conds.length) next.conds = conds;
    if (conds.length > 1) next.join = join;
    column.setFilterValue(next.values || next.conds ? next : undefined);
    onClose();
  };

  const allOn = shown.length > 0 && shown.every(([k]) => sel.has(k));
  const toggle = (k: string, on: boolean) => { const n = new Set(sel); if (on) n.add(k); else n.delete(k); setSel(n); };
  const max = Math.max(1, ...counts.map((c) => c[1]));
  const act = (fn: () => void) => () => { fn(); onClose(); };

  return (
    <div className={`fp${inline ? " inline" : " pop card"}`} onClick={(e) => e.stopPropagation()}>
      {!inline && (
        <div className="fp-actions">
          {column.getCanSort() && (
            <>
              <button className="btn small" onClick={act(() => column.toggleSorting(false))}>A → Z</button>
              <button className="btn small" onClick={act(() => column.toggleSorting(true))}>Z → A</button>
            </>
          )}
          <button className="btn small" onClick={act(() => autofit(table, colId))}>Sığdır</button>
          <button className="btn small" onClick={act(() => freezeTo(table, colId))}>
            {(table.getState().columnPinning.left ?? []).slice(-1)[0] === colId ? "Sabitlemeyi kaldır" : "Buraya kadar sabitle"}
          </button>
          <button className="btn small" onClick={act(() => column.toggleVisibility(false))}>Sütunu gizle</button>
        </div>
      )}
      <div className="fp-sec fp-conds">
        <span className="fp-label">Koşul</span>
        <CondEdit c={c1} onChange={setC1} onEnter={apply} autoFocus={!inline || matchMedia("(pointer: fine)").matches} />
        {two ? (
          <>
            <JoinPick value={join} onChange={setJoin} />
            <CondEdit c={c2} onChange={setC2} onEnter={apply} />
            <button className="dg-link fp-more" onClick={() => setTwo(false)}>İkinci koşulu kaldır</button>
          </>
        ) : <button className="dg-link fp-more" onClick={() => setTwo(true)}>+ İkinci koşul</button>}
      </div>
      <div className="fp-sec fp-values">
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

/** Rules across columns in groups, each group and the groups themselves joined with VE / VEYA. */
export function AdvancedFilter<T>({ table, onClose }: { table: Table<T>; onClose: () => void }) {
  const column = table.getColumn(ADV)!;
  const cols = filterable(table);
  const rule = (): AdvRule => ({ ...BLANK, col: cols[0]?.id ?? "" });
  const [f, setF] = useState<AdvValue>(() => (column.getFilterValue() as AdvValue | undefined) ?? { join: "and", groups: [{ join: "and", rules: [rule()] }] });
  const clean = useMemo<AdvValue>(() => ({
    join: f.join,
    groups: f.groups.map((g) => ({ ...g, rules: g.rules.filter(condUsed) })).filter((g) => g.rules.length),
  }), [f]);
  const hits = useMemo(() => {
    const others = table.getState().columnFilters.filter((x) => x.id !== ADV);
    return table.getCoreRowModel().rows.filter((r) => others.every((x) => passes(r as Row<any>, x))
      && (!clean.groups.length || advFilter(r as Row<any>, ADV, clean, () => {}))).length;
  }, [table, clean]);
  const lists = useRef(new Map<string, string[]>());
  const valuesOf = (id: string) => {
    let v = lists.current.get(id);
    if (!v) {
      v = [...new Set(table.getCoreRowModel().rows.map((r) => r.getValue(id)).filter((x) => !isEmpty(x)).map(String))].slice(0, 300);
      lists.current.set(id, v);
    }
    return v;
  };
  const group = (gi: number, fn: (g: AdvGroup) => AdvGroup) => setF((s) => ({ ...s, groups: s.groups.map((g, i) => (i === gi ? fn(g) : g)) }));
  const setRule = (gi: number, ri: number, r: AdvRule) => group(gi, (g) => ({ ...g, rules: g.rules.map((x, i) => (i === ri ? r : x)) }));
  const dropRule = (gi: number, ri: number) => setF((s) => ({
    ...s,
    groups: s.groups.map((g, i) => (i === gi ? { ...g, rules: g.rules.filter((_, j) => j !== ri) } : g)).filter((g) => g.rules.length),
  }));
  const used = [...new Set(f.groups.flatMap((g) => g.rules.map((r) => r.col)))];
  return (
    <>
      <div className="fs-backdrop" onClick={onClose} />
      <div className="fs adv card" role="dialog" aria-label="Gelişmiş filtre">
        <div className="fs-head">
          <b>Gelişmiş filtre</b>
          <span className="dg-spacer" />
          <button className="fs-close" onClick={onClose} aria-label="Kapat"><Icon name="x" /></button>
        </div>
        <div className="adv-body">
          {used.map((id) => <datalist key={id} id={`adv-${id}`}>{valuesOf(id).map((v) => <option key={v} value={v} />)}</datalist>)}
          {f.groups.length > 1 && (
            <div className="adv-top"><span>Gruplar arasında</span><JoinPick value={f.join} onChange={(join) => setF((s) => ({ ...s, join }))} label="Gruplar arası bağlaç" /></div>
          )}
          {f.groups.map((g, gi) => (
            <div key={gi} className="adv-group">
              <div className="adv-top"><b>Grup {gi + 1}</b><JoinPick value={g.join} onChange={(join) => group(gi, (x) => ({ ...x, join }))} label="Kurallar arası bağlaç" /></div>
              {g.rules.map((r, ri) => (
                <div key={ri} className="adv-rule">
                  <select value={r.col} aria-label="Sütun" onChange={(e) => setRule(gi, ri, { ...r, col: e.target.value })}>
                    {cols.map((c) => <option key={c.id} value={c.id}>{headerText(c.columnDef as GridColumn<T>)}</option>)}
                  </select>
                  <CondEdit c={r} list={`adv-${r.col}`} onChange={(c) => setRule(gi, ri, { ...r, ...c })} />
                  <button className="fs-close" onClick={() => dropRule(gi, ri)} aria-label="Kuralı sil"><Icon name="x" size={14} /></button>
                </div>
              ))}
              <button className="dg-link" onClick={() => group(gi, (x) => ({ ...x, rules: [...x.rules, rule()] }))}>+ Kural</button>
            </div>
          ))}
          <button className="dg-link" onClick={() => setF((s) => ({ ...s, groups: [...s.groups, { join: "and", rules: [rule()] }] }))}>+ Grup</button>
        </div>
        <div className="fp-foot adv-foot">
          <span className="muted"><b>{hits.toLocaleString("tr-TR")}</b> kayıt eşleşiyor</span>
          <span className="dg-spacer" />
          <button className="btn" onClick={() => { column.setFilterValue(undefined); onClose(); }}>Temizle</button>
          <button className="btn primary" onClick={() => { column.setFilterValue(clean.groups.length ? clean : undefined); onClose(); }}>Uygula</button>
        </div>
      </div>
    </>
  );
}
