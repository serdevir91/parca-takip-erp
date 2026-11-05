import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus } from "lucide-react";
import { useMemo, useState, type CSSProperties } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../api/auth";
import DataGrid, { type GridColumn } from "../../components/DataGrid";
import LabelsModal, { type Label } from "../../components/Labels";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal } from "../admin/shared";
import { fmtQty, numOrNull } from "./common";

type NeedProject = { id: number; name: string; required: number; issued: number; open: number };
type Row = {
  key: string; item_id: number | null; type: string; std: string; size: string; name: string; unit: string; qty: number;
  min_qty: number; location: string; open_need: number; on_order: number; shortage: number; low: boolean; projects: NeedProject[];
};
type Resp = { rows: Row[]; short_count: number; low_count: number; without_card: number };
type MoveKind = "in" | "out" | "count" | "issue";
type Filter = "all" | "short" | "low";

const MOVE_LABELS: Record<MoveKind, string> = { in: "Giriş", out: "Çıkış", count: "Sayım", issue: "Projeye ver" };
const num: CSSProperties = { textAlign: "right" };
const title = (r: Row) => [r.type, r.std, r.size].filter(Boolean).join(" ");
const rowStyle = (r: Row): CSSProperties | undefined => (r.shortage > 0 || r.low
  ? { background: `color-mix(in srgb, var(--${r.shortage > 0 ? "danger" : "warn"}) 14%, transparent)` } : undefined);

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["fastener-stock", "stock", "stock-moves", "requirements"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Bağlantı elemanları tab of Stok: BOM demand and shelf stock side by side, moved with one or two taps. */
export default function FastenerStock() {
  const canEdit = useAuth().can("stock", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const list = useQuery({ queryKey: ["fastener-stock"], queryFn: () => api.get<Resp>("/fastener-stock") });
  const [filter, setFilter] = useState<Filter>("all");
  const [moving, setMoving] = useState<{ row: Row; kind: MoveKind } | null>(null);
  const [card, setCard] = useState<Row | "new" | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [labels, setLabels] = useState<Label[] | null>(null);
  const step = useMutation({
    mutationFn: ({ row, kind }: { row: Row; kind: "in" | "out" }) =>
      api.post<Row>("/fastener-stock/move", { key: row.key, kind, qty: 1, unit: row.unit }),
    onSuccess: refresh,
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<Row>[]>(() => [
    { accessorKey: "type", header: "Tip", size: 150 },
    { accessorKey: "std", header: "Standart", size: 110 },
    { accessorKey: "size", header: "Ölçü", size: 100, cellStyle: () => ({ fontWeight: 600 }) },
    { accessorKey: "qty", header: "Stok", size: 80, cellStyle: () => ({ ...num, fontWeight: 700 }), cell: (c) => fmtQty(c.row.original.qty) },
    { accessorKey: "unit", header: "Birim", size: 60 },
    { accessorKey: "min_qty", header: "Min.", size: 70, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.min_qty || null) },
    { accessorKey: "open_need", header: "Açık ihtiyaç", size: 95, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.open_need || null) },
    { accessorKey: "on_order", header: "Siparişte", size: 80, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.on_order || null) },
    { accessorKey: "shortage", header: "Eksik", size: 80, cellStyle: (r) => ({ ...num, fontWeight: 700, ...(r.shortage > 0 ? { color: "var(--danger)" } : {}) }), cell: (c) => fmtQty(c.row.original.shortage || null) },
    { accessorKey: "location", header: "Raf", size: 90 },
    {
      id: "projects", header: "Projeler", size: 170, accessorFn: (r) => r.projects.map((p) => p.name).join(", "),
    },
    ...(canEdit ? [{
      id: "actions", header: "", size: 300, noFilter: true, enableSorting: false,
      cell: (c) => {
        const r = c.row.original;
        return (
          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
            <button className="btn small" disabled={step.isPending || r.qty <= 0} aria-label={`${title(r)} bir azalt`} onClick={() => step.mutate({ row: r, kind: "out" })}><Minus size={14} /></button>
            <button className="btn small" disabled={step.isPending} aria-label={`${title(r)} bir artır`} onClick={() => step.mutate({ row: r, kind: "in" })}><Plus size={14} /></button>
            <button className="btn small primary" onClick={() => setMoving({ row: r, kind: "in" })}>Hareket</button>
            <button className="btn small" onClick={() => setMoving({ row: r, kind: "count" })}>Sayım</button>
            <button className="btn small" disabled={!r.projects.length} onClick={() => setMoving({ row: r, kind: "issue" })}>Projeye ver</button>
            <button className="btn small" onClick={() => setCard(r)}>Ayar</button>
          </div>
        );
      },
    } satisfies GridColumn<Row>] : []),
  ], [canEdit, step]);

  const d = list.data;
  const rows = (d?.rows ?? []).filter((r) => filter === "all" || (filter === "short" ? r.shortage > 0 : r.low));
  const chip = (f: Filter, label: string, n: number) => (
    <button className={`chip${filter === f ? " on" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(filter === f ? "all" : f)}>
      {label} <span className="muted">{fmtQty(n)}</span>
    </button>
  );
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Loading error={list.error} loading={list.isLoading} />
      <DataGrid<Row>
        exportName="Bağlantı elemanı stoğu"
        data={rows} columns={columns} getRowId={(r) => r.key} rowStyle={rowStyle}
        selectable selection={selection} onSelectionChange={setSelection}
        selectionActions={<button className="btn small" onClick={() => setLabels(rows.filter((r) => selection[r.key] && r.item_id)
          .map((r) => ({ payload: `STK:${r.key}`, title: title(r), sub: r.location })))}>QR etiket</button>}
        emptyText={filter === "all" ? "Bağlantı elemanı yok. BOM yüklenince burada kendiliğinden görünür, elle de ekleyebilirsiniz." : "Bu filtrede kayıt yok."}
        toolbar={<>
          {canEdit && <button className="btn small primary" onClick={() => setCard("new")}>+ Yeni bağlantı elemanı</button>}
          <span className="muted">{fmtQty(d?.rows.length ?? 0)} çeşit</span>
          {chip("short", "Eksik", d?.short_count ?? 0)}
          {chip("low", "Min. altında", d?.low_count ?? 0)}
        </>}
      />
      {moving && <MoveModal row={moving.row} start={moving.kind} onClose={() => setMoving(null)} />}
      {card && <CardModal row={card === "new" ? undefined : card} onClose={() => setCard(null)} />}
      {labels && <LabelsModal labels={labels} onClose={() => setLabels(null)} />}
    </div>
  );
}

function MoveModal({ row, start, onClose }: { row: Row; start: MoveKind; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [kind, setKind] = useState<MoveKind>(start);
  const [project, setProject] = useState<number | null>(row.projects[0]?.id ?? null);
  const open = row.projects.find((p) => p.id === project)?.open ?? 0;
  const [qty, setQty] = useState(start === "issue" ? String(Math.min(open, row.qty)) : "");
  const [note, setNote] = useState("");
  const change = (k: MoveKind) => { setKind(k); setQty(k === "issue" ? String(Math.min(open, row.qty)) : ""); };
  const pickProject = (id: number) => {
    setProject(id);
    setQty(String(Math.min(row.projects.find((p) => p.id === id)?.open ?? 0, row.qty)));
  };
  const save = useMutation({
    mutationFn: () => api.post<Row>("/fastener-stock/move", {
      key: row.key, kind, qty: numOrNull(qty) ?? 0, project_id: kind === "issue" ? project : null, unit: row.unit, note,
    }),
    onSuccess: (r) => { toast(`${title(row)}: stok ${fmtQty(r.qty)} ${r.unit}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={title(row)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || numOrNull(qty) === null || (kind === "issue" && !project)} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <p className="muted" style={{ marginTop: 0 }}>Stok <b>{fmtQty(row.qty)} {row.unit}</b>{row.location ? ` · Raf ${row.location}` : ""}</p>
      <div className="seg" style={{ marginBottom: 10 }}>
        {(Object.keys(MOVE_LABELS) as MoveKind[]).filter((k) => k !== "issue" || row.projects.length).map((k) => (
          <button key={k} className={kind === k ? "on" : ""} onClick={() => change(k)}>{MOVE_LABELS[k]}</button>
        ))}
      </div>
      <div className="adm-form">
        {kind === "issue" && (
          <Field label="Proje">
            <select value={project ?? ""} onChange={(e) => pickProject(Number(e.target.value))}>
              {row.projects.map((p) => <option key={p.id} value={p.id}>{p.name} (açık {fmtQty(p.open)})</option>)}
            </select>
          </Field>
        )}
        <Field label={kind === "count" ? "Sayılan miktar" : "Miktar"}>
          <input autoFocus inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && numOrNull(qty) !== null) save.mutate(); }} />
        </Field>
        <Field label="Not"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function CardModal({ row, onClose }: { row?: Row; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [type, setType] = useState("");
  const [std, setStd] = useState("");
  const [size, setSize] = useState("");
  const [unit, setUnit] = useState(row?.unit ?? "Adet");
  const [min, setMin] = useState(row?.min_qty ? String(row.min_qty) : "");
  const [location, setLocation] = useState(row?.location ?? "");
  const save = useMutation({
    mutationFn: () => api.put<Row>("/fastener-stock/card", {
      key: row?.key ?? null, type, std, size, unit, min_qty: numOrNull(min) ?? 0, location,
    }),
    onSuccess: () => { toast(row ? "Kaydedildi" : "Bağlantı elemanı eklendi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={row ? title(row) : "Yeni bağlantı elemanı"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || (!row && (!type.trim() || !size.trim()))} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form">
        {!row && <>
          <Field label="Tip"><input autoFocus placeholder="Civata" maxLength={60} value={type} onChange={(e) => setType(e.target.value)} /></Field>
          <Field label="Standart"><input placeholder="DIN 933" maxLength={60} value={std} onChange={(e) => setStd(e.target.value)} /></Field>
          <Field label="Ölçü"><input placeholder="M8x30" maxLength={60} value={size} onChange={(e) => setSize(e.target.value)} /></Field>
        </>}
        <Field label="Birim"><input maxLength={20} value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
        <Field label="Min. stok" hint="Stok bunun altına düşünce bildirim gelir."><input inputMode="decimal" value={min} onChange={(e) => setMin(e.target.value)} /></Field>
        <Field label="Raf"><input maxLength={100} value={location} onChange={(e) => setLocation(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
