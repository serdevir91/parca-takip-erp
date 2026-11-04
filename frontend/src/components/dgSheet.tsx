import { flexRender, type Column, type Row, type Table } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { cellText, FilterPopup, norm, parseNum, type ColFilter } from "./dgFilter";
import { autofit, drawnColumns, headerText, isEmpty, type GridColumn, type GridProps } from "./dgTypes";
import { useToast } from "./Toast";

type Pos = { r: number; c: number };
type Range = { r0: number; r1: number; c0: number; c1: number };
type Cell = Pos & { text: string };
type Edit = { id: string; col: string; old: string; val: string };
type Move = "down" | "up" | "right" | "left" | "stay";

const rangeOf = (a: Pos, b: Pos): Range => ({ r0: Math.min(a.r, b.r), r1: Math.max(a.r, b.r), c0: Math.min(a.c, b.c), c1: Math.max(a.c, b.c) });
const inRange = (s: Range | null, r: number, c: number) => !!s && r >= s.r0 && r <= s.r1 && c >= s.c0 && c <= s.c1;
const span = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const isField = (t: EventTarget | null) => !!(t as HTMLElement | null)?.closest?.("input,select,textarea,button,a");
const fmtNum = (n: number) => String(+n.toFixed(10)).replace(".", ",");
/** Cell value as Excel should receive it: Turkish decimals, nothing for empty. */
const asText = (v: unknown) => (isEmpty(v) ? "" : typeof v === "number" ? fmtNum(v) : String(v));

/** Tab-separated text from Excel or any sheet. Quoted cells may hold tabs and line breaks. */
export function parseTsv(text: string): string[][] {
  const s = text.replace(/\r\n?/g, "\n");
  const out: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quoted) {
      if (ch !== '"') cell += ch;
      else if (s[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === "\t") { row.push(cell); cell = ""; } else if (ch === "\n") { row.push(cell); out.push(row); row = []; cell = ""; } else cell += ch;
  }
  // A lone quote mark in plain text: read the lines as they are
  if (quoted) return s.replace(/\n$/, "").split("\n").map((l) => l.split("\t"));
  if (cell !== "" || row.length) { row.push(cell); out.push(row); }
  return out;
}

export function toTsv(block: string[][]): string {
  const q = (t: string) => (/[\t\n\r"]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t);
  return block.map((r) => r.map(q).join("\t")).join("\r\n");
}

/** Constant step of a numeric run, so that dragging 1, 2 continues with 3, 4. */
function seriesStep(seq: string[]): number | null {
  if (seq.length < 2) return null;
  const n = seq.map(parseNum);
  if (n.some((x) => x === null)) return null;
  const step = (n[1] as number) - (n[0] as number);
  return n.every((x, i) => i === 0 || Math.abs((x as number) - (n[i - 1] as number) - step) < 1e-9) ? step : null;
}

/** Text ending in a number, as in T01-0009 or A2: the prefix, the digits, and the step of the run. */
function textSeries(seq: string[]): { prefix: string; start: number; width: number; step: number } | null {
  const m = seq.map((t) => /^(.*\D)(\d+)$/.exec(t));
  if (m.some((x) => !x || x[1] !== m[0]![1])) return null;
  const n = m.map((x) => Number(x![2]));
  const step = n.length > 1 ? n[1] - n[0] : 1;
  if (!n.every((x, i) => i === 0 || x - n[i - 1] === step)) return null;
  return { prefix: m[0]![1], start: n[0], width: m[0]![2].length, step };
}

export function Editor<T>({ row, col, colId, seed, open, onDone }: { row: Row<T>; col: GridColumn<T>; colId: string; seed?: string; open?: boolean; onDone: (v?: string, move?: Move) => void }) {
  const [v, setV] = useState(seed ?? String(row.getValue(colId) ?? ""));
  const e = col.edit!;
  // Enter closes the editor and the input then blurs; only the first of the two counts
  const closed = useRef(false);
  const finish: typeof onDone = (...a) => {
    if (closed.current) return;
    closed.current = true;
    onDone(...a);
  };
  const opts = typeof e.options === "function" ? e.options(row.original) : e.options;
  const out = () => (e.type === "number" ? v.replace(",", ".") : v);
  const key = (ev: React.KeyboardEvent) => {
    if (ev.key === "Enter") finish(out(), ev.shiftKey ? "up" : "down");
    if (ev.key === "Escape") finish(undefined, "stay");
    if (ev.key === "Tab") { ev.preventDefault(); finish(out(), ev.shiftKey ? "left" : "right"); }
  };
  if (e.type === "select") {
    return (
      <select autoFocus value={v} ref={(el) => { if (el && open) { try { el.showPicker(); } catch { /* needs a user action */ } } }}
        onChange={(ev) => finish(ev.target.value, "stay")} onBlur={() => finish(undefined)} onKeyDown={key} onClick={(ev) => ev.stopPropagation()}>
        {!opts?.includes(v) && <option value={v}>{v || "—"}</option>}
        {opts?.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
      </select>
    );
  }
  return (
    <input autoFocus type="text" inputMode={e.type === "number" ? "decimal" : undefined} value={v} onChange={(ev) => setV(ev.target.value)}
      onBlur={() => finish(out())} onKeyDown={key} onClick={(ev) => ev.stopPropagation()} />
  );
}

function FindBar({ replace, onFind, onReplace, onReplaceAll, onClose }: {
  replace: boolean;
  onFind: (q: string, exact: boolean, mcase: boolean, back: boolean) => string;
  onReplace: (q: string, to: string, exact: boolean, mcase: boolean) => string;
  onReplaceAll: (q: string, to: string, exact: boolean, mcase: boolean) => string;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [to, setTo] = useState("");
  const [exact, setExact] = useState(false);
  const [mcase, setMcase] = useState(false);
  const [msg, setMsg] = useState("");
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    if (e.key === "Enter" && q) setMsg(onFind(q, exact, mcase, e.shiftKey));
  };
  return (
    <div className="dg-find" role="search" onKeyDown={key}>
      <input autoFocus placeholder="Bul" aria-label="Bul" value={q} onChange={(e) => setQ(e.target.value)} />
      {replace && <input placeholder="Şununla değiştir" aria-label="Şununla değiştir" value={to} onChange={(e) => setTo(e.target.value)} />}
      <button className="btn small" disabled={!q} onClick={() => setMsg(onFind(q, exact, mcase, true))} title="Önceki (Shift+Enter)">‹</button>
      <button className="btn small" disabled={!q} onClick={() => setMsg(onFind(q, exact, mcase, false))} title="Sonraki (Enter)">›</button>
      {replace && (
        <>
          <button className="btn small" disabled={!q} onClick={() => setMsg(onReplace(q, to, exact, mcase))}>Değiştir</button>
          <button className="btn small" disabled={!q} onClick={() => setMsg(onReplaceAll(q, to, exact, mcase))}>Tümünü değiştir</button>
        </>
      )}
      <label><input type="checkbox" checked={exact} onChange={(e) => setExact(e.target.checked)} /> Tüm hücre</label>
      <label><input type="checkbox" checked={mcase} onChange={(e) => setMcase(e.target.checked)} /> Büyük/küçük harf</label>
      {msg && <span className="muted">{msg}</span>}
      <span className="dg-spacer" />
      <button className="dg-link" onClick={onClose}>Kapat</button>
    </div>
  );
}

const sheetCol = <T,>(c: Column<T, unknown>) => c.id !== "_sel" && c.id !== "actions";

/** Table view that behaves like a spreadsheet: cell ranges, keyboard, clipboard, fill, undo, find and a status bar. */
export function TableView<T>({ p, table, rows }: { p: GridProps<T>; table: Table<T>; rows: Row<T>[] }) {
  const toast = useToast();
  const [editing, setEditing] = useState<{ row: string; col: string; seed?: string; open?: boolean } | null>(null);
  const [openFilter, setOpenFilter] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Pos | null>(null);
  const [head, setHead] = useState<Pos | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [find, setFind] = useState<"find" | "replace" | null>(null);
  const [fillTo, setFillTo] = useState<Range | null>(null);
  const [note, setNote] = useState("");
  // A filter popup closes on Escape and on any press outside it, toolbar included
  useEffect(() => {
    if (!openFilter) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !(e.target as Element).closest?.(".fp, thead th button")) setOpenFilter(null);
    };
    document.addEventListener("keydown", close);
    document.addEventListener("mousedown", close);
    return () => { document.removeEventListener("keydown", close); document.removeEventListener("mousedown", close); };
  }, [openFilter, setOpenFilter]);
  const undo = useRef<Edit[][]>([]);
  const redo = useRef<Edit[][]>([]);
  const drag = useRef<"range" | "fill" | null>(null);
  const dropFill = useRef<() => void>(() => {});
  const findScope = useRef<Range | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rh = p.rowHeight ?? 28;
  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => rh, overscan: 20 });
  const items = virt.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBottom = items.length ? virt.getTotalSize() - items[items.length - 1].end : 0;
  const totalWidth = table.getTotalSize();

  const drawn = drawnColumns(table);
  const cols = drawn.filter(sheetCol);
  const colIndex = new Map(cols.map((c, i) => [c.id, i]));
  const lastR = rows.length - 1;
  const lastC = cols.length - 1;
  const clamp = (q: Pos): Pos => ({ r: Math.max(0, Math.min(q.r, lastR)), c: Math.max(0, Math.min(q.c, lastC)) });
  const ready = lastR >= 0 && lastC >= 0;
  const act = anchor && ready ? clamp(anchor) : null;
  const sel = act && head ? rangeOf(act, clamp(head)) : null;
  const multi = !!sel && (sel.r0 !== sel.r1 || sel.c0 !== sel.c1);

  const raw = (q: Pos) => rows[q.r].getValue(cols[q.c].id);
  const text = (q: Pos) => asText(raw(q));
  const editable = (row: Row<T>, col: Column<T, unknown>) => {
    const d = col.columnDef as GridColumn<T>;
    return !!(d.edit && p.onEdit && (d.edit.canEdit?.(row.original) ?? true));
  };
  const focusGrid = () => scrollRef.current?.focus({ preventScroll: true });

  const reveal = (q: Pos) => {
    const el = scrollRef.current;
    if (!el) return;
    const headH = el.querySelector("thead")?.getBoundingClientRect().height ?? 0;
    if (q.r * rh < el.scrollTop) el.scrollTop = q.r * rh;
    else if (headH + (q.r + 1) * rh > el.scrollTop + el.clientHeight) el.scrollTop = headH + (q.r + 1) * rh - el.clientHeight;
    const col = cols[q.c];
    if (col.getIsPinned()) return;
    const frozen = table.getLeftTotalSize();
    const x = col.getStart("center");
    if (x < el.scrollLeft) el.scrollLeft = x;
    else if (frozen + x + col.getSize() > el.scrollLeft + el.clientWidth) el.scrollLeft = frozen + x + col.getSize() - el.clientWidth;
  };
  const go = (q: Pos, extend = false) => {
    if (!extend) setAnchor(q);
    setHead(q);
    reveal(q);
  };
  const pick = (s: Range) => { setAnchor({ r: s.r0, c: s.c0 }); setHead({ r: s.r1, c: s.c1 }); };

  // ---------- writing cells ----------
  const accept = (row: Row<T>, col: Column<T, unknown>, t: string): string | null => {
    const e = (col.columnDef as GridColumn<T>).edit!;
    const v = t.trim();
    if (e.type === "number") {
      if (!v) return "";
      const n = parseNum(v);
      return n === null ? null : String(n);
    }
    if (e.type === "select") {
      const opts = (typeof e.options === "function" ? e.options(row.original) : e.options) ?? [];
      return opts.find((o) => o === v) ?? opts.find((o) => norm(o) === norm(v)) ?? null;
    }
    return t;
  };
  const apply = (edits: Edit[], record = true) => {
    const byId = table.getCoreRowModel().rowsById;
    const changes = edits.flatMap((e) => (byId[e.id] ? [{ row: byId[e.id].original, columnId: e.col, value: e.val }] : []));
    if (!changes.length) return;
    if (p.onEditMany && changes.length > 1) p.onEditMany(changes);
    else changes.forEach((c) => p.onEdit!(c.row, c.columnId, c.value));
    if (record) {
      undo.current.push(edits);
      if (undo.current.length > 100) undo.current.shift();
      redo.current = [];
    }
  };
  const write = (cells: Cell[], quiet = false): number => {
    const edits: Edit[] = [];
    let skipped = 0;
    for (const x of cells) {
      const row = rows[x.r];
      const col = cols[x.c];
      const val = editable(row, col) ? accept(row, col, x.text) : null;
      if (val === null) { skipped++; continue; }
      const old = String(row.getValue(col.id) ?? "");
      if (val !== old) edits.push({ id: row.id, col: col.id, old, val });
    }
    apply(edits);
    if (skipped && !quiet) toast(`${edits.length.toLocaleString("tr-TR")} hücre yazıldı, ${skipped.toLocaleString("tr-TR")} hücre atlandı (kilitli hücre ya da geçersiz değer)`, true);
    return edits.length;
  };
  const history = (from: React.MutableRefObject<Edit[][]>, to: React.MutableRefObject<Edit[][]>, label: string) => {
    const e = from.current.pop();
    if (!e) return;
    apply(e.map((x) => ({ ...x, old: x.val, val: x.old })), false);
    to.current.push(e.map((x) => ({ ...x, old: x.val, val: x.old })));
    setNote(`${e.length.toLocaleString("tr-TR")} hücre ${label}`);
  };

  const clearCells = (s: Range) => {
    const cells: Cell[] = [];
    for (const r of span(s.r0, s.r1)) for (const c of span(s.c0, s.c1)) cells.push({ r, c, text: "" });
    write(cells, true);
  };
  const block = (s: Range) => span(s.r0, s.r1).map((r) => span(s.c0, s.c1).map((c) => text({ r, c })));

  const paste = (txt: string) => {
    if (!sel) return;
    const src = parseTsv(txt);
    if (!src.length) return;
    const h = src.length;
    const w = src.reduce((m, x) => Math.max(m, x.length), 0);
    const H = sel.r1 - sel.r0 + 1;
    const W = sel.c1 - sel.c0 + 1;
    // A single value fills the selection; a block repeats when it divides the selection evenly
    const tile = (H > h || W > w) && H % h === 0 && W % w === 0;
    const cells: Cell[] = [];
    for (let i = 0; i < (tile ? H : h); i++) {
      for (let j = 0; j < (tile ? W : w); j++) {
        const r = sel.r0 + i;
        const c = sel.c0 + j;
        if (r <= lastR && c <= lastC) cells.push({ r, c, text: src[i % h][j % w] ?? "" });
      }
    }
    const n = write(cells);
    setNote(`${n.toLocaleString("tr-TR")} hücre yapıştırıldı`);
    pick({ r0: sel.r0, c0: sel.c0, r1: Math.min(lastR, sel.r0 + (tile ? H : h) - 1), c1: Math.min(lastC, sel.c0 + (tile ? W : w) - 1) });
  };

  const fill = (src: Range, dst: Range, series = true) => {
    const vertical = dst.r0 < src.r0 || dst.r1 > src.r1;
    const [s0, s1, d0, d1] = vertical ? [src.r0, src.r1, dst.r0, dst.r1] : [src.c0, src.c1, dst.c0, dst.c1];
    const cells: Cell[] = [];
    for (const line of vertical ? span(dst.c0, dst.c1) : span(dst.r0, dst.r1)) {
      const at = (i: number): Pos => (vertical ? { r: i, c: line } : { r: line, c: i });
      const seq = span(s0, s1).map((i) => text(at(i)));
      const step = seriesStep(seq);
      const first = parseNum(seq[0]) ?? 0;
      const named = series && step === null ? textSeries(seq) : null;
      for (let i = d0; i <= d1; i++) {
        if (i >= s0 && i <= s1) continue;
        const k = i - s0;
        const no = named ? named.start + k * named.step : -1;
        cells.push({
          ...at(i),
          text: step !== null ? fmtNum(first + k * step)
            : no >= 0 ? named!.prefix + String(no).padStart(named!.width, "0")
            : seq[((k % seq.length) + seq.length) % seq.length],
        });
      }
    }
    write(cells);
    pick(dst);
  };
  const fillDown = () => {
    if (!sel) return;
    if (sel.r0 === sel.r1 && sel.r0 > 0) fill({ ...sel, r0: sel.r0 - 1, r1: sel.r0 - 1 }, { ...sel, r0: sel.r0 - 1 }, false);
    else if (sel.r1 > sel.r0) fill({ ...sel, r1: sel.r0 }, sel, false);
  };
  const fillRight = () => {
    if (!sel) return;
    if (sel.c0 === sel.c1 && sel.c0 > 0) fill({ ...sel, c0: sel.c0 - 1, c1: sel.c0 - 1 }, { ...sel, c0: sel.c0 - 1 }, false);
    else if (sel.c1 > sel.c0) fill({ ...sel, c1: sel.c0 }, sel, false);
  };
  /** Double click on the fill handle: down as far as the neighbouring column has data. */
  const fillAuto = () => {
    if (!sel) return;
    const n = sel.c0 > 0 ? sel.c0 - 1 : sel.c1 + 1;
    let r = sel.r1;
    while (r < lastR && (n > lastC || !isEmpty(raw({ r: r + 1, c: n })))) r++;
    if (r > sel.r1) fill(sel, { ...sel, r1: r });
  };
  dropFill.current = () => {
    if (drag.current === "fill" && sel && fillTo) fill(sel, fillTo);
    drag.current = null;
    setFillTo(null);
  };
  useEffect(() => {
    const up = () => dropFill.current();
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // ---------- find and replace ----------
  const matcher = (q: string, exact: boolean, mcase: boolean) => {
    const f = (s: string) => (mcase ? s : norm(s));
    const nq = f(q);
    return (t: string) => (exact ? f(t) === nq : f(t).includes(nq));
  };
  const matches = (q: string, exact: boolean, mcase: boolean) => {
    const hit = matcher(q, exact, mcase);
    const s = findScope.current ?? { r0: 0, r1: lastR, c0: 0, c1: lastC };
    const out: Pos[] = [];
    for (let r = s.r0; r <= Math.min(s.r1, lastR); r++) {
      for (let c = s.c0; c <= Math.min(s.c1, lastC); c++) if (hit(text({ r, c }))) out.push({ r, c });
    }
    return out;
  };
  const swap = (t: string, q: string, to: string, exact: boolean, mcase: boolean) =>
    (exact ? to : t.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), mcase ? "gu" : "giu"), () => to));
  const onFind = (q: string, exact: boolean, mcase: boolean, back: boolean) => {
    const m = matches(q, exact, mcase);
    if (!m.length) return "Bulunamadı";
    const cur = act ?? { r: -1, c: -1 };
    const after = (x: Pos) => x.r > cur.r || (x.r === cur.r && x.c > cur.c);
    const before = (x: Pos) => x.r < cur.r || (x.r === cur.r && x.c < cur.c);
    const i = back ? m.reduce((b, x, k) => (before(x) ? k : b), m.length - 1) : Math.max(0, m.findIndex(after));
    go(m[i]);
    return `${(i + 1).toLocaleString("tr-TR")} / ${m.length.toLocaleString("tr-TR")}`;
  };
  const onReplace = (q: string, to: string, exact: boolean, mcase: boolean) => {
    if (act && matcher(q, exact, mcase)(text(act))) write([{ ...act, text: swap(text(act), q, to, exact, mcase) }]);
    return onFind(q, exact, mcase, false);
  };
  const onReplaceAll = (q: string, to: string, exact: boolean, mcase: boolean) => {
    const n = write(matches(q, exact, mcase).map((x) => ({ ...x, text: swap(text(x), q, to, exact, mcase) })));
    return `${n.toLocaleString("tr-TR")} hücre değişti`;
  };
  const openFind = (mode: "find" | "replace") => {
    findScope.current = multi ? sel : null;
    setFind(mode);
  };

  // ---------- editing ----------
  const startEdit = (q: Pos, seed?: string, open?: boolean) => {
    const row = rows[q.r];
    const col = cols[q.c];
    if (!editable(row, col)) return;
    reveal(q);
    setEditing({ row: row.id, col: col.id, seed, open });
  };
  const editDone = (q: Pos, v?: string, move?: Move) => {
    setEditing(null);
    if (v !== undefined) write([{ ...q, text: v }]);
    if (!move) return;
    focusGrid();
    if (move !== "stay") go(clamp({ r: q.r + (move === "down" ? 1 : move === "up" ? -1 : 0), c: q.c + (move === "right" ? 1 : move === "left" ? -1 : 0) }));
  };

  // ---------- keyboard ----------
  const jump = (from: Pos, dr: number, dc: number): Pos => {
    const next = (x: Pos) => ({ r: x.r + dr, c: x.c + dc });
    const inside = (x: Pos) => x.r >= 0 && x.r <= lastR && x.c >= 0 && x.c <= lastC;
    const blank = (x: Pos) => isEmpty(raw(x));
    let q = from;
    if (!inside(next(q))) return q;
    if (!blank(q) && !blank(next(q))) {
      while (inside(next(q)) && !blank(next(q))) q = next(q);
      return q;
    }
    q = next(q);
    while (inside(next(q)) && blank(q)) q = next(q);
    return q;
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (isField(e.target) || editing) return;
    const k = e.key;
    const ctrl = e.ctrlKey || e.metaKey;
    const done = () => e.preventDefault();
    if (!act) {
      if (ready && k.startsWith("Arrow")) { done(); go({ r: 0, c: 0 }); }
      return;
    }
    if (ctrl) {
      switch (k.toLowerCase()) {
        case "a": done(); pick({ r0: 0, r1: lastR, c0: 0, c1: lastC }); return;
        case "f": done(); openFind("find"); return;
        case "h": if (p.onEdit) { done(); openFind("replace"); } return;
        case "d": if (p.onEdit) { done(); fillDown(); } return;
        case "r": if (p.onEdit) { done(); fillRight(); } return;
        case "z": done(); if (e.shiftKey) history(redo, undo, "yinelendi"); else history(undo, redo, "geri alındı"); return;
        case "y": done(); history(redo, undo, "yinelendi"); return;
        case " ": done(); if (sel) pick({ ...sel, r0: 0, r1: lastR }); return;
      }
    }
    const from = e.shiftKey && head ? clamp(head) : act;
    const step = (dr: number, dc: number) => { done(); go(ctrl ? jump(from, dr, dc) : clamp({ r: from.r + dr, c: from.c + dc }), e.shiftKey); };
    const page = Math.max(1, Math.floor((scrollRef.current?.clientHeight ?? 300) / rh) - 2);
    switch (k) {
      case "ArrowUp": step(-1, 0); return;
      case "ArrowDown":
        if (e.altKey) { done(); startEdit(act, undefined, true); return; }
        step(1, 0); return;
      case "ArrowLeft": step(0, -1); return;
      case "ArrowRight": step(0, 1); return;
      case "PageUp": done(); go(clamp({ r: from.r - page, c: from.c }), e.shiftKey); return;
      case "PageDown": done(); go(clamp({ r: from.r + page, c: from.c }), e.shiftKey); return;
      case "Home": done(); go(ctrl ? { r: 0, c: 0 } : { r: from.r, c: 0 }, e.shiftKey); return;
      case "End": done(); go(ctrl ? { r: lastR, c: lastC } : { r: from.r, c: lastC }, e.shiftKey); return;
      case "Tab": done(); go(clamp({ r: act.r, c: act.c + (e.shiftKey ? -1 : 1) })); return;
      case "Enter": done(); go(clamp({ r: act.r + (e.shiftKey ? -1 : 1), c: act.c })); return;
      case "F2": done(); startEdit(act); return;
      case "Delete": case "Backspace": done(); if (sel) clearCells(sel); return;
      case "Escape": setNote(""); setMenu(null); return;
    }
    if (e.shiftKey && k === " ") { done(); if (sel) pick({ ...sel, c0: 0, c1: lastC }); return; }
    if (k.length === 1 && !ctrl && !e.altKey) {
      const d = cols[act.c].columnDef as GridColumn<T>;
      if (d.edit?.type === "number" && !/[\d,.-]/.test(k)) return;
      done();
      startEdit(act, d.edit?.type === "select" ? undefined : k, d.edit?.type === "select");
    }
  };

  // ---------- clipboard: DOM events work on plain http too, where navigator.clipboard does not exist ----------
  const onCopy = (e: React.ClipboardEvent, cut = false) => {
    if (isField(e.target) || !sel) return;
    e.clipboardData.setData("text/plain", toTsv(block(sel)));
    e.preventDefault();
    const n = (sel.r1 - sel.r0 + 1) * (sel.c1 - sel.c0 + 1);
    setNote(`${n.toLocaleString("tr-TR")} hücre ${cut ? "kesildi" : "kopyalandı"}`);
    if (cut) clearCells(sel);
  };
  const onPaste = (e: React.ClipboardEvent) => {
    if (isField(e.target) || !sel || !p.onEdit) return;
    e.preventDefault();
    paste(e.clipboardData.getData("text/plain"));
  };
  const command = (name: "copy" | "cut") => { focusGrid(); document.execCommand(name); };
  const pasteFromMenu = async () => {
    focusGrid();
    try {
      paste(await navigator.clipboard.readText());
    } catch {
      toast("Yapıştırmak için Ctrl+V kullanın");
    }
  };

  // ---------- mouse ----------
  const posOf = (t: EventTarget): Pos | null => {
    const td = (t as HTMLElement).closest?.("td[data-c]") as HTMLElement | null;
    return td ? { r: Number(td.dataset.r), c: Number(td.dataset.c) } : null;
  };
  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest(".dg-fill")) { e.preventDefault(); drag.current = "fill"; return; }
    const q = posOf(t);
    if (!q || t.closest("button,a,input,select,textarea,label")) return;
    e.preventDefault();
    focusGrid();
    setMenu(null);
    setHead(q);
    if (!e.shiftKey || !act) setAnchor(q);
    drag.current = "range";
    if (p.openOnClick && !e.shiftKey) p.onRowClick?.(rows[q.r].original);
  };
  const onMouseOver = (e: React.MouseEvent) => {
    if (!drag.current) return;
    const q = posOf(e.target);
    if (!q) return;
    if (drag.current === "range") { setHead(q); return; }
    if (!sel || inRange(sel, q.r, q.c)) { setFillTo(null); return; }
    const dr = q.r > sel.r1 ? q.r - sel.r1 : sel.r0 - q.r;
    const dc = q.c > sel.c1 ? q.c - sel.c1 : sel.c0 - q.c;
    setFillTo(dr >= dc
      ? { ...sel, r0: Math.min(sel.r0, q.r), r1: Math.max(sel.r1, q.r) }
      : { ...sel, c0: Math.min(sel.c0, q.c), c1: Math.max(sel.c1, q.c) });
  };
  const onMouseMove = (e: React.MouseEvent) => {
    const el = scrollRef.current;
    if (!drag.current || !el) return;
    const b = el.getBoundingClientRect();
    if (e.clientY > b.bottom - 24) el.scrollTop += rh;
    else if (e.clientY < b.top + 48) el.scrollTop -= rh;
    if (e.clientX > b.right - 24) el.scrollLeft += 40;
    else if (e.clientX < b.left + 24) el.scrollLeft -= 40;
  };
  const onDoubleClick = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest(".dg-fill")) { fillAuto(); return; }
    const q = posOf(t);
    if (!q || t.closest("button,a,input,select,textarea,label")) return;
    if (editable(rows[q.r], cols[q.c])) startEdit(q);
    else if (!p.openOnClick) p.onRowClick?.(rows[q.r].original);
  };
  const onContextMenu = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    const q = posOf(t);
    if (!q || t.closest("a,input,select,textarea")) return;
    e.preventDefault();
    if (!inRange(sel, q.r, q.c)) { setAnchor(q); setHead(q); }
    focusGrid();
    setMenu({ x: Math.min(e.clientX, innerWidth - 230), y: Math.min(e.clientY, innerHeight - 340) });
  };

  const stats = useMemo(() => {
    if (!sel) return null;
    let count = 0;
    let nums = 0;
    let sum = 0;
    let min = Infinity;
    let max = -Infinity;
    for (let r = sel.r0; r <= Math.min(sel.r1, rows.length - 1); r++) {
      for (let c = sel.c0; c <= Math.min(sel.c1, cols.length - 1); c++) {
        const v = rows[r].getValue(cols[c].id);
        if (isEmpty(v)) continue;
        count++;
        const n = parseNum(v);
        if (n === null) continue;
        nums++;
        sum += n;
        min = Math.min(min, n);
        max = Math.max(max, n);
      }
    }
    return { count, nums, sum, min, max };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel?.r0, sel?.r1, sel?.c0, sel?.c1, rows, cols.length]);
  const num = (n: number) => (+n.toFixed(4)).toLocaleString("tr-TR");
  const filterTo = (f: ColFilter) => { if (act) cols[act.c].setFilterValue(f); };
  const actCol = act ? (cols[act.c].columnDef as GridColumn<T>) : null;

  return (
    <>
      {find && <FindBar replace={find === "replace" && !!p.onEdit} onFind={onFind} onReplace={onReplace} onReplaceAll={onReplaceAll} onClose={() => { setFind(null); focusGrid(); }} />}
      <div className="dg" ref={scrollRef} tabIndex={0} aria-label="Tablo" onClick={() => setOpenFilter(null)} onKeyDown={onKey} onCopy={onCopy} onCut={(e) => onCopy(e, !!p.onEdit)} onPaste={onPaste}
        onMouseDown={onMouseDown} onMouseOver={onMouseOver} onMouseMove={onMouseMove} onDoubleClick={onDoubleClick} onContextMenu={onContextMenu}>
        <table style={{ width: totalWidth }}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const col = h.column.columnDef as GridColumn<T>;
                  const f = h.column.getFilterValue() as ColFilter | undefined;
                  const sorted = h.column.getIsSorted();
                  const pinned = !!h.column.getIsPinned();
                  const many = table.getState().sorting.length > 1;
                  return (
                    <th key={h.id} className={`${openFilter === h.id ? "fopen " : ""}${pinned ? "pin" : ""}`}
                      style={{ width: h.getSize(), position: "sticky", ...(pinned ? { left: h.column.getStart("left") } : {}) }}>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <span style={{ cursor: h.column.getCanSort() ? "pointer" : "default", overflow: "hidden", textOverflow: "ellipsis" }}
                          title={h.column.getCanSort() ? "Sırala. Shift ile birden çok sütuna göre sıralar." : undefined}
                          onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}{sorted && many ? h.column.getSortIndex() + 1 : ""}
                        </span>
                        {!col.noFilter && h.column.id !== "_sel" && (
                          <button className={"btn small" + (f ? " primary" : "")} style={{ padding: "0 5px", marginLeft: "auto" }}
                            title="Sırala, filtrele, sütun seçenekleri" onClick={(e) => { e.stopPropagation(); setOpenFilter(openFilter === h.id ? null : h.id); }}>▾</button>
                        )}
                      </div>
                      {openFilter === h.id && <FilterPopup table={table} colId={h.column.id} onClose={() => setOpenFilter(null)} />}
                      {h.column.getCanResize() && (
                        <div className="resizer" title="Sürükleyin; çift tıklayınca sığdırır" onMouseDown={h.getResizeHandler()} onTouchStart={h.getResizeHandler()}
                          onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => { e.stopPropagation(); autofit(table, h.column.id); }} />
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 && <tr style={{ height: padTop }}><td colSpan={drawn.length} style={{ border: 0, padding: 0 }} /></tr>}
            {items.map((vi) => {
              const row = rows[vi.index];
              const r = vi.index;
              return (
                <tr key={row.id} className={row.getIsSelected() ? "selected" : ""} style={{ height: rh, ...p.rowStyle?.(row.original) }}>
                  {row.getVisibleCells().map((cell) => {
                    const col = cell.column.columnDef as GridColumn<T>;
                    const c = colIndex.get(cell.column.id);
                    const canEdit = editable(row, cell.column);
                    const isEditing = editing?.row === row.id && editing.col === cell.column.id;
                    const pinned = !!cell.column.getIsPinned();
                    const on = c !== undefined && inRange(sel, r, c);
                    const isAct = c !== undefined && act?.r === r && act.c === c;
                    const corner = !!p.onEdit && !isEditing && sel?.r1 === r && sel.c1 === c;
                    const style: CSSProperties = { width: cell.column.getSize(), ...col.cellStyle?.(row.original), ...(pinned ? { left: cell.column.getStart("left") } : {}) };
                    const cls = [canEdit && "editable", pinned && "pin", on && "rng", isAct && "act", corner && "fh",
                      c !== undefined && inRange(fillTo, r, c) && "fl"].filter(Boolean).join(" ");
                    return (
                      <td key={cell.id} data-r={c === undefined ? undefined : r} data-c={c} className={cls} style={style}
                        title={typeof cell.getValue() === "string" ? (cell.getValue() as string) : undefined}>
                        {isEditing ? (
                          <Editor row={row} col={col} colId={cell.column.id} seed={editing.seed} open={editing.open} onDone={(v, move) => editDone({ r, c: c! }, v, move)} />
                        ) : (
                          flexRender(cell.column.columnDef.cell, cell.getContext())
                        )}
                        {corner && <span className="dg-fill" title="Sürükleyerek doldurun; çift tıklayınca aşağı doldurur" />}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {padBottom > 0 && <tr style={{ height: padBottom }}><td colSpan={drawn.length} style={{ border: 0, padding: 0 }} /></tr>}
          </tbody>
        </table>
        {rows.length === 0 && <div className="muted" style={{ padding: 16 }}>{p.emptyText ?? "Kayıt yok."}</div>}
      </div>
      <div className="dg-status" aria-live="polite">
        {act && actCol ? (
          <>
            <span className="dg-addr"><b>{headerText(actCol) || cols[act.c].id}</b> · {(act.r + 1).toLocaleString("tr-TR")}. satır</span>
            <span className="dg-val" title={text(act)}>{text(act)}</span>
          </>
        ) : <span className="muted">Hücreye tıklayın. Ok tuşları, Ctrl+C / Ctrl+V, Ctrl+F ve sağ tık menüsü çalışır.</span>}
        {note && <span className="muted">{note}</span>}
        <span className="dg-spacer" />
        {multi && stats && (
          <>
            <span>Sayı: <b>{stats.count.toLocaleString("tr-TR")}</b></span>
            {stats.nums > 0 && (
              <>
                <span>Toplam: <b>{num(stats.sum)}</b></span>
                <span>Ortalama: <b>{num(stats.sum / stats.nums)}</b></span>
                <span>En küçük: <b>{num(stats.min)}</b></span>
                <span>En büyük: <b>{num(stats.max)}</b></span>
              </>
            )}
          </>
        )}
      </div>
      {menu && sel && act && (
        <>
          <div className="dg-cmenu-back" onMouseDown={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
          <div className="dg-cmenu card" role="menu" style={{ left: menu.x, top: menu.y }} onClick={() => setMenu(null)}>
            <button role="menuitem" onClick={() => command("copy")}>Kopyala<kbd>Ctrl+C</kbd></button>
            {p.onEdit && (
              <>
                <button role="menuitem" onClick={() => command("cut")}>Kes<kbd>Ctrl+X</kbd></button>
                <button role="menuitem" onClick={() => void pasteFromMenu()}>Yapıştır<kbd>Ctrl+V</kbd></button>
                <button role="menuitem" onClick={() => clearCells(sel)}>Temizle<kbd>Delete</kbd></button>
                <button role="menuitem" onClick={fillDown}>Aşağı doldur<kbd>Ctrl+D</kbd></button>
                <button role="menuitem" onClick={fillRight}>Sağa doldur<kbd>Ctrl+R</kbd></button>
              </>
            )}
            <hr />
            <button role="menuitem" onClick={() => filterTo({ values: [cellText(raw(act))] })}>Bu değere göre filtrele</button>
            <button role="menuitem" onClick={() => filterTo({ conds: [isEmpty(raw(act)) ? { op: "notEmpty" } : { op: "ne", a: text(act) }] })}>Bu değeri hariç tut</button>
            <button role="menuitem" onClick={() => openFind(p.onEdit ? "replace" : "find")}>Bul ve değiştir<kbd>Ctrl+H</kbd></button>
            {p.onRowClick && (
              <>
                <hr />
                <button role="menuitem" onClick={() => p.onRowClick!(rows[act.r].original)}>Ayrıntı</button>
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}
