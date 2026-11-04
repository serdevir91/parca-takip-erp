import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, download } from "../api/client";
import { useAuth } from "../api/auth";
import BulkEdit from "../components/BulkEdit";
import DataGrid, { type CellChange, type GridColumn } from "../components/DataGrid";
import MailDialog, { type MailFile } from "../components/MailDialog";
import ExcelImportModal from "../components/ExcelImportModal";
import { Page, useProject } from "../components/Layout";
import PartDetail, { type PartChoices, type PartRow } from "../components/PartDetail";
import PartNamesModal from "../components/PartNamesModal";
import T35ImportModal from "../components/T35ImportModal";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";

// backend/app/api/excel.py: GET /excel/{project_id}/parca-takip and /takip-listesi
const EXPORT_PARCA_TAKIP = (pid: number) => `/excel/${pid}/parca-takip`;
const EXPORT_TAKIP_LISTESI = (pid: number) => `/excel/${pid}/takip-listesi`;

type View = "tree" | "flat";
type PartsResp = { version_id: number | null; view: string; total: number; count: number; total_qty: number; rows: PartRow[] };
type GridRow = PartRow & { _key: string; _kids?: boolean; _open?: boolean; _dim?: boolean };
type EditVars = { partNo: string; changes: Record<string, unknown> };
type CellsResult = { fields_changed: number; error_count: number; errors: string[]; not_found: string[] };

const LS = { view: "parts.view", widths: "parts.colWidths", inPurchased: "parts.inPurchased", archived: "parts.showArchived",
  kinds: "parts.kinds" };
// Row-type chips; the flat view starts without assemblies (the old "Sadece parçalar" behaviour)
type Kind = "part" | "asm" | "purasm" | "fastener";
const KINDS: { key: Kind; label: string }[] = [
  { key: "part", label: "Parça" },
  { key: "asm", label: "Montaj" },
  { key: "purasm", label: "Satın alınan montaj" },
  { key: "fastener", label: "Bağlantı elemanı" },
];
const DEFAULT_KINDS: Record<View, Kind[]> = { tree: ["part", "asm", "purasm", "fastener"], flat: ["part", "purasm", "fastener"] };
const rowKind = (r: PartRow): Kind =>
  r.fastener ? "fastener" : r.is_purchased_assembly ? "purasm" : r.is_assembly ? "asm" : "part";
const RESET_PROC = "(BOM değerine dön)";
const NEW_COLOR = "D9EAD3";
const IMALAT = "İmalat";
const HAZIR = "Hazır Alım";
const NONE = "Belirtilmemiş";
const STATUS_MAP: Record<string, Record<string, string>> = {
  [IMALAT]: { Bekliyor: "Üretilmedi", "Devam ediyor": "Üretilmedi", "Tamamlandı": "Üretildi" },
  [HAZIR]: { Bekliyor: "Sipariş Verilmedi", "Devam ediyor": "Sipariş Verildi", "Tamamlandı": "Sipariş Teslim Edildi" },
  Montaj: { Bekliyor: "Montajlanmadı", "Devam ediyor": "Montajlanmadı", "Tamamlandı": "Montajlandı" },
};
const SERVER_FIELDS = ["progress", "procurement_override", "note", "t35_note", "manufacturer", "material_status",
  "is_new", "updated_at", "updated_by"] as const;
const namable = (r: PartRow) => !r.fastener && !r.archived;
/** What a grid cell means to the server. */
function cellChange(col: string, v: string): Record<string, unknown> | null {
  switch (col) {
    case "procurement": return { procurement_override: v === RESET_PROC ? null : v };
    case "is_new": return { is_new: v === "Yeni" };
    case "progress": case "manufacturer": case "material_status": case "note": case "t35_note": case "part_name":
      return { [col]: v };
    default: return null;
  }
}

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function save(key: string, v: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* storage unavailable */ }
}

const fmt = (n: number | null | undefined) => (n === null || n === undefined ? "" : n.toLocaleString("tr-TR"));
const getRowId = (r: GridRow) => r._key;
const rowStyle = (r: GridRow): CSSProperties | undefined => (r._dim ? { opacity: 0.35 } : r.archived ? { opacity: 0.55 } : undefined);
const cardColor = (r: GridRow) => (r.status_color ? `#${r.status_color}` : undefined);
const tracked = (r: PartRow) => !r.fastener && !r.archived && (r.depth ?? 1) > 0;

function drawingText(r: PartRow): string {
  if (r.archived || r.fastener) return "";
  if (r.has_drawing) return `Var${r.drawing_rev ? ` (Rev ${r.drawing_rev})` : ""}${r.drawing_rev_mismatch ? " · Rev farkı" : ""}`;
  if (r.needs_drawing && !r.in_purchased) return "Resim yok";
  return "";
}

/** Local copy of backend derive_status, used only for the optimistic cell colour until the server answers. */
function patchRow(r: PartRow, ch: Record<string, unknown>, colors: Record<string, string>, choices?: PartChoices): PartRow {
  const n: PartRow = { ...r, ...(ch as Partial<PartRow>) };
  if ("procurement_override" in ch && !r.is_purchased_assembly && !r.archived) {
    const o = ch.procurement_override as string | null;
    n.procurement = o || r.procurement_csv || (r.is_assembly ? "" : NONE);
    n.needs_drawing = !r.is_assembly && (choices?.temin_drawing ?? [IMALAT]).includes(n.procurement ?? "");
  }
  if (!r.fastener && !r.in_purchased && !r.archived) {
    const proc = n.procurement ?? "";
    const base = choices?.temin_kinds[proc] ?? proc;
    const kind = base === HAZIR ? HAZIR : r.is_assembly && !r.is_purchased_assembly ? "Montaj" : base === IMALAT ? IMALAT : null;
    n.status = kind ? STATUS_MAP[kind][n.progress] ?? STATUS_MAP[kind].Bekliyor : "Temin seçilmedi";
    n.status_color = colors[n.status] ?? r.status_color;
  }
  return n;
}

function mergeServer(r: PartRow, s: PartRow): PartRow {
  const n: PartRow = { ...r };
  for (const f of SERVER_FIELDS) if (f in s) (n as Record<string, unknown>)[f] = s[f];
  if (!r.fastener && !r.in_purchased && !r.archived && s.status !== undefined) {
    n.status = s.status;
    n.status_color = s.status_color;
    n.status_kind = s.status_kind;
    if (s.procurement !== undefined) n.procurement = s.procurement;
  }
  return n;
}

export default function Parts() {
  const { pid, project } = useProject();
  const canEdit = useAuth().can("parts", "edit");
  const toast = useToast();
  const qc = useQueryClient();

  const [view, setView] = useState<View>(() => (load<string>(LS.view, "tree") === "flat" ? "flat" : "tree"));
  const [inPurchased, setInPurchased] = useState<boolean>(() => load(LS.inPurchased, false));
  const [showArchived, setShowArchived] = useState<boolean>(() => load(LS.archived, false));
  const [kindsByView, setKindsByView] = useState<Record<View, Kind[]>>(() => ({ ...DEFAULT_KINDS, ...load(LS.kinds, {}) }));
  const kinds = useMemo(() => new Set(kindsByView[view]), [kindsByView, view]);
  const toggleKind = (k: Kind) => setKindsByView((cur) => {
    const set = new Set(cur[view]);
    if (set.has(k)) set.delete(k); else set.add(k);
    return { ...cur, [view]: KINDS.map((x) => x.key).filter((x) => set.has(x)) };
  });
  // Widths saved before the grid kept its own layout; still the starting width of each column
  const [widths] = useState<Record<string, number>>(() => load(LS.widths, {}));
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [detail, setDetail] = useState<string | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [imp, setImp] = useState<"t35" | "excel" | "names" | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [visibleQty, setVisibleQty] = useState(0);
  const [menu, setMenu] = useState<"show" | "export" | "import" | null>(null);
  const [mail, setMail] = useState<MailFile | null>(null);

  useEffect(() => save(LS.view, view), [view]);
  useEffect(() => save(LS.inPurchased, inPurchased), [inPurchased]);
  useEffect(() => save(LS.archived, showArchived), [showArchived]);
  useEffect(() => save(LS.kinds, kindsByView), [kindsByView]);
  useEffect(() => setSelection({}), [view, inPurchased, showArchived, kindsByView]);

  const choicesQ = useQuery({
    queryKey: ["partChoices", pid],
    queryFn: () => api.get<PartChoices>(`/projects/${pid}/parts/choices`),
    enabled: !!pid, staleTime: 60_000,
  });
  const choices = choicesQ.data;
  const colors = useMemo(() => choices?.colors ?? {}, [choices]);

  const mainQ = useQuery({
    queryKey: ["parts", pid, view, inPurchased],
    queryFn: () => api.get<PartsResp>(`/projects/${pid}/parts?view=${view}${inPurchased ? "" : "&in_purchased=false"}`),
    enabled: !!pid,
  });
  const archQ = useQuery({
    queryKey: ["parts", pid, "archived"],
    queryFn: () => api.get<PartsResp>(`/projects/${pid}/parts?archived=true`),
    enabled: !!pid && showArchived,
  });

  // Tree: mark rows with children, then drop descendants of collapsed rows (rows come in BOM/DFS order).
  const baseRows = useMemo<GridRow[]>(() => {
    const all = mainQ.data?.rows ?? [];
    // Rows inside purchased assemblies follow their own checkbox, not the type chips
    const match = (r: PartRow) => r.in_purchased || kinds.has(rowKind(r));
    if (view === "flat") {
      return all.filter(match).map((r) => ({ ...r, _key: `p${r.part_no}` }));
    }
    // Tree: keep the ancestors of every matching row so the hierarchy stays readable
    const keep = new Set<PartRow>();
    const stack: PartRow[] = [];
    for (const r of all) {
      const d = r.depth ?? 0;
      stack.length = Math.min(stack.length, d);
      if (match(r)) {
        keep.add(r);
        for (const a of stack) if (a) keep.add(a);
      }
      stack[d] = r;
    }
    const rows = all.filter((r) => keep.has(r));
    const parents = new Set<string>();
    for (const r of rows) if (r.parent_level) parents.add(r.parent_level);
    const out: GridRow[] = [];
    let skip = Infinity;
    for (const r of rows) {
      const d = r.depth ?? 0;
      if (d > skip) continue;
      skip = Infinity;
      const key = `t${r.id}`;
      const kids = !!r.level && parents.has(r.level);
      const open = !collapsed.has(key);
      out.push({ ...r, _key: key, _kids: kids, _open: open });
      if (kids && !open) skip = d;
    }
    return out;
  }, [mainQ.data, view, collapsed, kinds]);

  const kindCounts = useMemo(() => {
    const c: Record<Kind, number> = { part: 0, asm: 0, purasm: 0, fastener: 0 };
    for (const r of mainQ.data?.rows ?? []) if (!r.in_purchased) c[rowKind(r)]++;
    return c;
  }, [mainQ.data]);

  const data = useMemo<GridRow[]>(() => {
    // A hidden assembly dims everything below it in the tree
    const dimmed = new Set<string>();
    const rows = baseRows.map((r) => {
      const dim = !!r.hidden || (view === "tree" && !!r.parent_level && dimmed.has(r.parent_level));
      if (dim && r.level) dimmed.add(r.level);
      return dim ? { ...r, _dim: true } : r;
    });
    if (!showArchived || !archQ.data) return rows;
    return [...rows, ...archQ.data.rows.map((r) => ({ ...r, archived: true, _dim: r.hidden, _key: `a${r.part_no}` }))];
  }, [baseRows, showArchived, archQ.data, view]);

  const toggleRef = useRef<(key: string) => void>(() => {});
  toggleRef.current = (key: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  const collapseAll = () => {
    const rows = mainQ.data?.rows ?? [];
    const parents = new Set<string>();
    for (const r of rows) if (r.parent_level) parents.add(r.parent_level);
    setCollapsed(new Set(rows.filter((r) => (r.depth ?? 0) >= 1 && r.level && parents.has(r.level)).map((r) => `t${r.id}`)));
  };

  // ---------- inline edit (optimistic) ----------
  const updateRows = useCallback((partNo: string, fn: (r: PartRow) => PartRow) => {
    qc.setQueriesData<unknown>({ queryKey: ["parts", pid] }, (d: unknown) => {
      const resp = d as PartsResp | undefined;
      if (!resp || !Array.isArray(resp.rows)) return d;
      return { ...resp, rows: resp.rows.map((r) => (r.part_no === partNo ? fn(r) : r)) };
    });
  }, [qc, pid]);

  const edit = useMutation({
    mutationFn: ({ partNo, changes }: EditVars) =>
      api.patch<{ changed: number; part: PartRow }>(`/projects/${pid}/parts/${encodeURIComponent(partNo)}`, changes),
    onMutate: async ({ partNo, changes }: EditVars) => {
      await qc.cancelQueries({ queryKey: ["parts", pid] });
      const snap = qc.getQueriesData<unknown>({ queryKey: ["parts", pid] });
      updateRows(partNo, (r) => patchRow(r, changes, colors, choices));
      return { snap };
    },
    onError: (e, _v, ctx) => {
      ctx?.snap.forEach(([k, d]) => qc.setQueryData(k, d));
      toast(errText(e), true);
    },
    onSuccess: (res, { partNo }) => {
      if (res?.part) updateRows(partNo, (r) => mergeServer(r, res.part));
      qc.invalidateQueries({ queryKey: ["parts", pid, "detail", partNo] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
    },
  });
  const mutate = edit.mutate;

  // Pasted, filled and replaced cells: one request and one optimistic update for all of them
  const cells = useMutation({
    mutationFn: (list: EditVars[]) => api.post<CellsResult>(`/projects/${pid}/parts/cells`, {
      changes: list.flatMap(({ partNo, changes }) => Object.entries(changes).map(([field, value]) => ({ part_no: partNo, field, value }))),
    }),
    onMutate: async (list: EditVars[]) => {
      await qc.cancelQueries({ queryKey: ["parts", pid] });
      const snap = qc.getQueriesData<unknown>({ queryKey: ["parts", pid] });
      const byPart = new Map<string, Record<string, unknown>>();
      for (const { partNo, changes } of list) byPart.set(partNo, { ...byPart.get(partNo), ...changes });
      qc.setQueriesData<unknown>({ queryKey: ["parts", pid] }, (d: unknown) => {
        const resp = d as PartsResp | undefined;
        if (!resp || !Array.isArray(resp.rows)) return d;
        return { ...resp, rows: resp.rows.map((r) => (byPart.has(r.part_no) ? patchRow(r, byPart.get(r.part_no)!, colors, choices) : r)) };
      });
      return { snap };
    },
    onError: (e, _v, ctx) => {
      ctx?.snap.forEach(([k, d]) => qc.setQueryData(k, d));
      toast(errText(e), true);
    },
    onSuccess: (res) => {
      if (res.error_count) toast(`${res.error_count.toLocaleString("tr-TR")} hücre kaydedilemedi: ${res.errors[0]}`, true);
      else if (res.not_found.length) toast(`${res.not_found.length.toLocaleString("tr-TR")} parça bulunamadı`, true);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
    },
  });
  const saveCells = cells.mutate;

  const onEdit = useCallback((r: GridRow, col: string, v: string) => {
    const changes = cellChange(col, v);
    if (!changes) return;
    if (col === "part_name") saveCells([{ partNo: r.part_no, changes }]);
    else mutate({ partNo: r.part_no, changes });
  }, [mutate, saveCells]);

  const onEditMany = useCallback((list: CellChange<GridRow>[]) => {
    const out: EditVars[] = [];
    for (const c of list) {
      const changes = cellChange(c.columnId, c.value);
      if (changes) out.push({ partNo: c.row.part_no, changes });
    }
    if (out.length) saveCells(out);
  }, [saveCells]);

  // ---------- columns ----------
  const columns = useMemo<GridColumn<GridRow>[]>(() => {
    const w = (id: string, d: number) => widths[id] ?? d;
    const can = (r: GridRow) => tracked(r);
    const mans = choices?.manufacturers ?? [];
    return [
      {
        id: "level", header: "Seviye", size: w("level", view === "tree" ? 170 : 110), card: view === "tree" ? "hide" : "field",
        accessorFn: (r) => (r.levels && r.levels.length > 1 ? `${r.levels[0]} (+${r.levels.length - 1})` : r.level ?? ""),
        cell: ({ row, getValue }) => {
          const r = row.original;
          if (view !== "tree" || r.archived) return getValue() as string;
          return (
            <span style={{ paddingLeft: (r.depth ?? 0) * 14 }}>
              {r._kids ? (
                <button className="tree-toggle" aria-label={r._open ? "Daralt" : "Genişlet"} aria-expanded={r._open}
                  onClick={(e) => { e.stopPropagation(); toggleRef.current(r._key); }}>{r._open ? "▾" : "▸"}</button>
              ) : <span className="tree-spacer" />}
              {r.level}
            </span>
          );
        },
      },
      {
        id: "part_no", accessorKey: "part_no", header: "Parça No", size: w("part_no", 200), card: "title",
        cellStyle: (r) => (r.is_new ? statusStyle(colors.new || NEW_COLOR) : undefined),
        cell: ({ row }) => <span style={{ fontWeight: row.original.is_assembly ? 600 : 400 }}>{row.original.part_no}</span>,
      },
      {
        id: "part_name", header: "Parça Adı", size: w("part_name", 190), card: "sub", accessorFn: (r) => r.part_name ?? "",
        edit: { type: "text", canEdit: namable },
      },
      { id: "row_type", header: "Tip", size: w("row_type", 120), card: "sub", accessorFn: (r) => (r.archived ? "Arşivlenmiş" : r.row_type ?? "") },
      { id: "main_group", accessorKey: "main_group", header: "Ana Grup", size: w("main_group", 150) },
      { id: "parent_part_no", accessorKey: "parent_part_no", header: "Üst Montaj", size: w("parent_part_no", 170), card: view === "tree" ? "hide" : "field" },
      { id: "qty", accessorKey: "qty", header: "Adet", size: w("qty", 70), cell: ({ getValue }) => fmt(getValue() as number) },
      { id: "total_qty", accessorKey: "total_qty", header: "Toplam Adet", size: w("total_qty", 95), cell: ({ getValue }) => fmt(getValue() as number) },
      { id: "material", accessorKey: "material", header: "Malzeme", size: w("material", 130) },
      { id: "weight", accessorKey: "weight", header: "Ağırlık", size: w("weight", 80), cell: ({ getValue }) => fmt(getValue() as number | null) },
      {
        id: "procurement", header: "Temin Şekli", size: w("procurement", 120),
        accessorFn: (r) => r.procurement ?? r.procurement_override ?? "",
        cellStyle: (r) => (r.procurement === NONE ? { color: "var(--danger)", fontWeight: 600 } : undefined),
        cell: ({ row, getValue }) => (
          <>{getValue() as string}{row.original.procurement_override ? <span className="muted" title="Elle değiştirildi"> *</span> : null}</>
        ),
        edit: { type: "select", options: [...(choices?.temin_choices ?? []), RESET_PROC], canEdit: (r) => can(r) && !r.is_purchased_assembly },
      },
      { id: "coating", accessorKey: "coating", header: "Kaplama", size: w("coating", 100) },
      { id: "rev", accessorKey: "rev", header: "Rev", size: w("rev", 60) },
      {
        id: "progress", accessorKey: "progress", header: "İlerleme", size: w("progress", 115),
        edit: { type: "select", options: choices?.progress_choices ?? [], canEdit: can },
      },
      {
        id: "status", accessorKey: "status", header: "Durum", size: w("status", 160), card: "badge",
        cellStyle: (r) => statusStyle(r.status_color),
      },
      {
        id: "manufacturer", accessorKey: "manufacturer", header: "Üretici", size: w("manufacturer", 120),
        edit: mans.length ? { type: "select", options: ["", ...mans], canEdit: can } : { type: "text", canEdit: can },
      },
      { id: "t35_note", accessorKey: "t35_note", header: "Durum Notu", size: w("t35_note", 210), edit: { type: "text", canEdit: can } },
      { id: "note", accessorKey: "note", header: "Not", size: w("note", 210), edit: { type: "text", canEdit: can } },
      {
        id: "drawing", header: "Teknik Resim", size: w("drawing", 140), accessorFn: drawingText,
        cell: ({ getValue, row }) => {
          const t = getValue() as string;
          if (t === "Resim yok") return <span className="badge warn">Resim yok</span>;
          if (row.original.drawing_rev_mismatch) return <span className="warn" title="Resim revizyonu BOM revizyonundan farklı">{t}</span>;
          return t;
        },
      },
      {
        id: "material_status", accessorKey: "material_status", header: "Malzeme Durumu", size: w("material_status", 140),
        edit: { type: "select", options: ["", ...(choices?.material_status_choices ?? [])], canEdit: can },
      },
      {
        id: "is_new", header: "Yeni", size: w("is_new", 70), accessorFn: (r) => (r.is_new ? "Yeni" : ""), card: "badge",
        cell: ({ getValue }) => (getValue() ? <span className="badge new">Yeni</span> : null),
        edit: { type: "select", options: ["Yeni", ""], canEdit: can },
      },
    ];
  }, [view, choices, colors, widths]);

  const onRowClick = useCallback((r: GridRow) => setDetail(r.part_no), []);
  const closeDetail = useCallback(() => setDetail(null), []);

  // ---------- visible totals ----------
  const onVisibleRowsChange = useCallback((rows: GridRow[]) => {
    let s = 0;
    for (const r of rows) if (r.counted && (!r.is_assembly || r.is_purchased_assembly)) s += r.total_qty ?? 0;
    setVisibleQty(s);
  }, []);

  // ---------- selection ----------
  const selectedPartNos = useMemo(() => {
    const keys = new Set(Object.keys(selection).filter((k) => selection[k]));
    if (!keys.size) return [];
    const out = new Set<string>();
    for (const r of data) if (keys.has(r._key) && !r.fastener && (r.depth ?? 1) > 0) out.add(r.part_no);
    return [...out];
  }, [selection, data]);

  const selectedFasteners = useMemo(() => {
    const out = new Set<string>();
    for (const r of data) if (selection[r._key] && r.fastener && r.fastener_key) out.add(r.fastener_key);
    return [...out];
  }, [selection, data]);
  const selectedCount = selectedPartNos.length + selectedFasteners.length;
  const allHidden = selectedCount > 0 && data.every((r) => !selection[r._key] || r.hidden || (!r.fastener && (r.depth ?? 1) === 0));
  const bulk = useMutation({
    mutationFn: (changes: Record<string, unknown>) => api.post<{ updated: number }>(`/projects/${pid}/parts/bulk`, { part_nos: selectedPartNos, changes }),
    onSuccess: (r) => {
      toast(`${r.updated.toLocaleString("tr-TR")} parça güncellendi`);
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
    },
    onError: (e) => toast(errText(e), true),
  });
  const hide = useMutation({
    mutationFn: async (hidden: boolean) => {
      if (selectedPartNos.length) {
        await api.post(`/projects/${pid}/parts/bulk`, { part_nos: selectedPartNos, changes: { hidden } });
      }
      if (selectedFasteners.length) {
        await api.put(`/projects/${pid}/fasteners/settings`, { keys: selectedFasteners, hidden });
      }
    },
    onSuccess: () => {
      setSelection({});
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["fasteners", pid] });
    },
    onError: (e) => toast(errText(e), true),
  });

  const base = (project?.root_part_no || "Proje").replace(/[^\w.-]+/g, "_");
  const xlsxFile = (kind: "pt" | "tl"): MailFile => kind === "pt"
    ? { path: EXPORT_PARCA_TAKIP(pid), name: `${base}_Parca_Takip.xlsx` }
    : { path: EXPORT_TAKIP_LISTESI(pid), name: `${base}_Takip_Listesi.xlsx` };
  const exportXlsx = async (kind: "pt" | "tl") => {
    setExporting(kind);
    setMenu(null);
    try {
      if (kind === "pt") await download(EXPORT_PARCA_TAKIP(pid), `${base}_Parca_Takip.xlsx`);
      else await download(EXPORT_TAKIP_LISTESI(pid), `${base}_Takip_Listesi.xlsx`);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setExporting(null);
    }
  };

  const loading = mainQ.isLoading;
  const shownChanged = inPurchased || showArchived || kindsByView[view].join() !== DEFAULT_KINDS[view].join();
  const cardLead = useCallback((r: GridRow) => {
    if (view !== "tree" || r.archived) return null;
    return (
      <span className="tree-lead" style={{ "--d": Math.min(r.depth ?? 0, 8) } as CSSProperties}>
        {r._kids ? (
          <button className="tree-toggle" aria-label={r._open ? "Daralt" : "Genişlet"} aria-expanded={r._open}
            onClick={(e) => { e.stopPropagation(); toggleRef.current(r._key); }}>{r._open ? "▾" : "▸"}</button>
        ) : null}
        <span className="tree-level">{r.level}</span>
      </span>
    );
  }, [view]);
  return (
    <Page full>
      <div className="toolbar parts-top" onClick={(e) => e.target === e.currentTarget && setMenu(null)}>
        <div className="seg" role="radiogroup" aria-label="Görünüm">
          <button role="radio" aria-checked={view === "tree"} className={view === "tree" ? "on" : ""} onClick={() => setView("tree")}>Ağaç</button>
          <button role="radio" aria-checked={view === "flat"} className={view === "flat" ? "on" : ""} onClick={() => setView("flat")}>Düz liste</button>
        </div>
        <div className="dg-menu-wrap">
          <button className={`btn small${shownChanged ? " primary" : ""}`} onClick={() => setMenu(menu === "show" ? null : "show")} aria-haspopup="true">
            Göster ▾
          </button>
          {menu === "show" && (
            <div className="dg-menu card parts-show">
              <div className="row kind-chips" role="group" aria-label="Satır tipi filtresi">
                {KINDS.filter((k) => kindCounts[k.key] > 0).map((k) => (
                  <button key={k.key} className={`chip${kinds.has(k.key) ? " on" : ""}`} aria-pressed={kinds.has(k.key)}
                    onClick={() => toggleKind(k.key)}>
                    {k.label} <span className="muted">{fmt(kindCounts[k.key])}</span>
                  </button>
                ))}
              </div>
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={inPurchased} onChange={(e) => setInPurchased(e.target.checked)} />
                Satın alınan montajların içi
              </label>
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                Arşivlenenler
              </label>
              <button className="btn small" onClick={() => setMenu(null)}>Tamam</button>
            </div>
          )}
        </div>
        <div className="dg-menu-wrap">
          <button className="btn small" disabled={!!exporting} onClick={() => setMenu(menu === "export" ? null : "export")} aria-haspopup="menu">
            {exporting ? "Hazırlanıyor…" : "Excel / e-posta ▾"}
          </button>
          {menu === "export" && (
            <div className="dg-menu card" role="menu">
              <button role="menuitem" className="btn small" onClick={() => void exportXlsx("pt")}>Excel indir: Parça Takip</button>
              <button role="menuitem" className="btn small" onClick={() => void exportXlsx("tl")}>Excel indir: Takip Listesi</button>
              <button role="menuitem" className="btn small" onClick={() => { setMenu(null); setMail(xlsxFile("pt")); }}>E-posta ile gönder: Parça Takip</button>
              <button role="menuitem" className="btn small" onClick={() => { setMenu(null); setMail(xlsxFile("tl")); }}>E-posta ile gönder: Takip Listesi</button>
            </div>
          )}
        </div>
        {canEdit && (
          <div className="dg-menu-wrap">
            <button className="btn small" onClick={() => setMenu(menu === "import" ? null : "import")} aria-haspopup="menu">İçe aktar ▾</button>
            {menu === "import" && (
              <div className="dg-menu card" role="menu">
                <button role="menuitem" className="btn small" onClick={() => { setMenu(null); setImp("excel"); }}>Excel'den içe aktar</button>
                <button role="menuitem" className="btn small" onClick={() => { setMenu(null); setImp("t35"); }}>Durum listesi içe aktar</button>
                <button role="menuitem" className="btn small" onClick={() => { setMenu(null); setImp("names"); }}>Parça adlarını yapıştır</button>
              </div>
            )}
          </div>
        )}
      </div>

      {mainQ.isError ? (
        <div className="error" style={{ padding: 16 }}>{errText(mainQ.error)}</div>
      ) : loading ? (
        <div className="muted" style={{ padding: 16 }}>Yükleniyor…</div>
      ) : (
        <div className="parts-wrap">
          <DataGrid<GridRow>
            data={data}
            columns={columns}
            getRowId={getRowId}
            onEdit={canEdit ? onEdit : undefined}
            onEditMany={canEdit ? onEditMany : undefined}
            onRowClick={onRowClick}
            rowStyle={rowStyle}
            selectable={canEdit}
            selection={selection}
            onSelectionChange={setSelection}
            onVisibleRowsChange={onVisibleRowsChange}
            exportName={`${base}_parca_listesi`}
            stateKey="parts"
            selectionActions={canEdit ? (
              <>
                <select className="dg-bulk" aria-label="Seçilenlere ilerleme ata" value="" disabled={!selectedPartNos.length || bulk.isPending}
                  onChange={(e) => e.target.value && bulk.mutate({ progress: e.target.value })}>
                  <option value="">İlerleme ata…</option>
                  {choices?.progress_choices.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <select className="dg-bulk" aria-label="Seçilenlere temin şekli ata" value="" disabled={!selectedPartNos.length || bulk.isPending}
                  onChange={(e) => e.target.value && bulk.mutate({ procurement_override: e.target.value })}>
                  <option value="">Temin ata…</option>
                  {choices?.temin_choices.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <button className="btn small" disabled={!selectedPartNos.length} onClick={() => setBulkOpen(true)}>Diğer alanlar</button>
                <button className="btn small" disabled={!selectedCount || hide.isPending} onClick={() => hide.mutate(!allHidden)}
                  title="Seçilenler listede kalır, yalnızca soluk görünür. Adet ve durumlar değişmez.">
                  {allHidden ? "Gizlemeyi kaldır" : "Gizle"}
                </button>
                {selectedFasteners.length > 0 && <span className="muted">Bağlantı elemanları yalnızca gizlenebilir; durumları Bağlantı Elemanları sayfasından değişir.</span>}
              </>
            ) : undefined}
            cardLead={cardLead}
            cardColor={cardColor}
            emptyText={project && !project.current_version_id ? "Bu projede onaylı BOM sürümü yok." : "Kayıt yok."}
            toolbar={
              <>
                {view === "tree" && (
                  <>
                    <button className="btn small" onClick={() => setCollapsed(new Set())}>Tümünü aç</button>
                    <button className="btn small" onClick={collapseAll}>Tümünü kapat</button>
                  </>
                )}
                <span className="muted">Toplam adet: <b>{visibleQty.toLocaleString("tr-TR")}</b></span>
                {(mainQ.isFetching || archQ.isFetching) && <span className="muted">Yenileniyor…</span>}
                {archQ.isError && <span className="error">Arşiv: {errText(archQ.error)}</span>}
                {choicesQ.isError && <span className="error">Seçenekler: {errText(choicesQ.error)}</span>}
              </>
            }
          />
        </div>
      )}

      {detail && <PartDetail pid={pid} partNo={detail} onClose={closeDetail} />}
      {bulkOpen && (
        <BulkEdit pid={pid} partNos={selectedPartNos} choices={choices} onClose={() => setBulkOpen(false)} onDone={() => setSelection({})} />
      )}
      {imp === "t35" && <T35ImportModal pid={pid} open onClose={() => setImp(null)} />}
      {imp === "excel" && <ExcelImportModal pid={pid} open onClose={() => setImp(null)} />}
      {imp === "names" && <PartNamesModal pid={pid} onClose={() => setImp(null)} />}
      {mail && <MailDialog files={[mail]} subject={`${project?.name ?? base}: ${mail.name.replace(/\.xlsx$/, "").replace(/_/g, " ")}`}
        body="Güncel liste ektedir." onClose={() => setMail(null)} />}
    </Page>
  );
}
