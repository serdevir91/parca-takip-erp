import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import { LOCALE, tx } from "../api/i18n";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import DataGrid, { type GridColumn } from "../components/DataGrid";

// Backend: backend/app/api/assembly.py
export const PLAN_DRAFT = "Taslak";
export const PLAN_PUBLISHED = "Yayınlandı";
export const PLAN_DONE = "Tamamlandı";

export type PlanItem = { id?: number; part_no: string; qty: number; seq?: number };
export type PlanExtra = { id: number; part_no: string; qty: number; assembly_no: string; note: string };
export type Plan = {
  id: number; no: number; plan_date: string; responsible: string; checker: string; status: string; notes: string;
  drawing_mode: string; rev: number; created_by: string; items: PlanItem[]; extras: PlanExtra[];
  percent?: number; ready_count?: number; done_count?: number; item_count?: number;
};
type Candidate = { part_no: string; name: string; qty: number; depth: number; kinds: number; percent: number; ready: boolean; steps: number };
type Lone = { part_no: string; qty: number };
type Quantity = {
  part_no: string; temin: string; is_asm: boolean; need: number; ready: number; reserved: number; used: number;
  extra: number; progress: string; counted: boolean;
};

export const fmt = (v: number) => v.toLocaleString(LOCALE);
export const planDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(LOCALE);
export const statusBadge = (s: string) => (s === PLAN_DONE ? "badge ok" : s === PLAN_PUBLISHED ? "badge warn" : "badge");

export default function Assembly() {
  const { pid, project } = useProject();
  const { can } = useAuth();
  const [tab, setTab] = useState<"plans" | "quantities">("plans");
  const [creating, setCreating] = useState(false);
  const canEdit = can("assembly", "edit");
  if (!project) return <Page><div className="muted">{tx("Yükleniyor…")}</div></Page>;
  if (!project.current_version_id) return <Page><div className="card">{tx("Önce onaylı bir BOM yükleyin")}</div></Page>;
  if (creating) return <Page><PlanForm pid={pid} onClose={() => setCreating(false)} /></Page>;
  return (
    <Page full>
      <div className="asm-page">
      <div className="row" style={{ marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>{tx("Montaj föyleri")}</h2>
        <span style={{ flex: 1 }} />
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}><Plus size={15} /> {tx("Yeni plan")}</button>}
      </div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "plans"} className={tab === "plans" ? "active" : ""} onClick={() => setTab("plans")}>{tx("Planlar")}</button>
        <button role="tab" aria-selected={tab === "quantities"} className={tab === "quantities" ? "active" : ""} onClick={() => setTab("quantities")}>{tx("Parça adetleri")}</button>
      </div>
      {tab === "plans" ? <Plans pid={pid} /> : <Quantities pid={pid} canEdit={canEdit} />}
      </div>
    </Page>
  );
}

function Plans({ pid }: { pid: number }) {
  const q = useQuery({ queryKey: ["assembly", pid, "plans"], queryFn: () => api.get<{ rows: Plan[] }>(`/projects/${pid}/assembly/plans`) });
  const columns = useMemo<GridColumn<Plan>[]>(() => [
    { accessorKey: "no", header: tx("Plan no"), size: 80, card: "title", cell: (c) => <Link to={`/p/${pid}/assembly/${c.row.original.id}`}>{tx("Plan {0}", c.row.original.no)}</Link> },
    { accessorKey: "plan_date", header: tx("Tarih"), size: 110, cell: (c) => planDate(c.row.original.plan_date) },
    { accessorKey: "responsible", header: tx("Sorumlu"), size: 160 },
    { accessorKey: "status", header: tx("Durum"), size: 120, cell: (c) => <span className={statusBadge(c.row.original.status)}>{tx(c.row.original.status)}</span> },
    { id: "assemblies", header: tx("Montaj sayısı"), size: 110, accessorFn: (r) => r.items.length },
    { accessorKey: "ready_count", header: tx("Montaja hazır"), size: 110 },
    { accessorKey: "percent", header: tx("Hazırlık %"), size: 120, cell: (c) => <Meter value={c.row.original.percent ?? 0} /> },
  ], [pid]);
  if (q.isError) return <div className="card error">{errText(q.error)}</div>;
  return (
    <DataGrid<Plan> stateKey="Montaj planları" exportName={tx("Montaj planları")} data={q.data?.rows ?? []} columns={columns}
      getRowId={(r) => String(r.id)} emptyText={tx("Henüz montaj planı yok.")} />
  );
}

export function Meter({ value }: { value: number }) {
  return (
    <span className="asm-meter" title={`%${fmt(Math.round(value))}`}>
      <span style={{ width: `${Math.min(100, value)}%` }} />
      <b>%{fmt(Math.round(value))}</b>
    </span>
  );
}

function Quantities({ pid, canEdit }: { pid: number; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [showConvert, setShowConvert] = useState(false);
  const q = useQuery({
    queryKey: ["assembly", pid, "quantities"],
    queryFn: () => api.get<{ rows: Quantity[]; convert: { part_no: string; progress: string; ready: number }[] }>(`/projects/${pid}/assembly/quantities`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["assembly", pid] });
  const save = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/assembly/quantities`, {
      items: Object.entries(edits).map(([part_no, v]) => ({ part_no, ready_qty: Number(v.replace(",", ".")) || 0 })),
    }),
    onSuccess: () => { setEdits({}); refresh(); toast(tx("Kaydedildi")); },
    onError: (e) => toast(errText(e), true),
  });
  const convert = useMutation({
    mutationFn: () => api.post<{ converted: number }>(`/projects/${pid}/assembly/quantities/convert`),
    onSuccess: (r) => { setShowConvert(false); refresh(); toast(tx("{0} parça adede geçirildi", fmt(r.converted))); },
    onError: (e) => toast(errText(e), true),
  });
  const columns = useMemo<GridColumn<Quantity>[]>(() => [
    { accessorKey: "part_no", header: tx("Parça No"), size: 180, card: "title" },
    { accessorKey: "temin", header: tx("Temin"), size: 140, cell: (c) => tx(c.row.original.temin) },
    { accessorKey: "need", header: tx("BOM adedi"), size: 90 },
    { accessorKey: "extra", header: tx("Ek"), size: 60 },
    {
      accessorKey: "ready", header: tx("Hazır"), size: 100, cell: (c) => {
        const r = c.row.original;
        if (!canEdit) return r.ready;
        return <input className="asm-num" inputMode="decimal" aria-label={tx("Hazır")} value={edits[r.part_no] ?? String(r.ready)}
          onChange={(e) => { const v = e.target.value; setEdits((s) => ({ ...s, [r.part_no]: v })); }} />;
      },
    },
    { accessorKey: "reserved", header: tx("Rezerve"), size: 80 },
    { accessorKey: "used", header: tx("Kullanılan"), size: 90 },
    { id: "free", header: tx("Serbest"), size: 80, accessorFn: (r) => Math.max(0, r.ready - r.used - r.reserved) },
  ], [canEdit, edits]);
  const pending = q.data?.convert ?? [];
  const toolbar = canEdit && (
    <>
      {Object.keys(edits).length > 0 && <button className="btn small primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>}
      {pending.length > 0 && <button className="btn small" onClick={() => setShowConvert(true)}>{tx("Durumdan adede geç ({0})", fmt(pending.length))}</button>}
    </>
  );
  return (
    <>
      <DataGrid<Quantity> stateKey="Parça adetleri" exportName={tx("Parça adetleri")} data={q.data?.rows ?? []} columns={columns}
        getRowId={(r) => r.part_no} toolbar={toolbar} emptyText={tx("Kayıt yok.")} />
      {showConvert && (
        <div className="modal-back" onClick={() => setShowConvert(false)}>
          <div className="modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>{tx("Durumdan adede geçiş")}</h3>
            <p className="muted">{tx("Tamamlandı görünen parçalar BOM adedi kadar hazır sayılır. Diğer parçalara dokunulmaz.")}</p>
            <div className="asm-scroll">
              <table className="simple"><tbody>
                {pending.map((r) => <tr key={r.part_no}><td>{r.part_no}</td><td>{tx(r.progress)}</td><td>{r.ready}</td></tr>)}
              </tbody></table>
            </div>
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" onClick={() => setShowConvert(false)}>{tx("Vazgeç")}</button>
              <button className="btn primary" disabled={convert.isPending} onClick={() => convert.mutate()}>{tx("Uygula")}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** New plan, or the plan given in `plan`. A published plan keeps its items: only their order moves. */
export function PlanForm({ pid, plan, onClose }: { pid: number; plan?: Plan; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const locked = !!plan && plan.status !== PLAN_DRAFT;
  const [search, setSearch] = useState("");
  const [onlyReady, setOnlyReady] = useState(false);
  const [items, setItems] = useState<PlanItem[]>(plan?.items.map((i) => ({ part_no: i.part_no, qty: i.qty })) ?? []);
  const [date, setDate] = useState(plan?.plan_date ?? new Date().toLocaleDateString("en-CA"));
  const [responsible, setResponsible] = useState(plan?.responsible ?? "");
  const [checker, setChecker] = useState(plan?.checker ?? "");
  const [notes, setNotes] = useState(plan?.notes ?? "");
  const [mode, setMode] = useState(plan?.drawing_mode ?? "none");
  const [dragged, setDragged] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["assembly", pid, "candidates"],
    queryFn: () => api.get<{ rows: Candidate[]; lone: Lone[] }>(`/projects/${pid}/assembly/candidates`),
  });
  const list = useMemo(() => {
    const s = search.trim().toLocaleLowerCase(LOCALE);
    return (q.data?.rows ?? []).filter((c) => (!onlyReady || c.ready) && (!s || `${c.part_no} ${c.name}`.toLocaleLowerCase(LOCALE).includes(s)));
  }, [q.data, search, onlyReady]);
  const lone = (q.data?.lone ?? []).filter((c) => !onlyReady && (!search.trim() || c.part_no.toLocaleLowerCase(LOCALE).includes(search.trim().toLocaleLowerCase(LOCALE))));
  const has = (part: string) => items.some((i) => i.part_no === part);
  const add = (part_no: string, qty: number) => setItems((s) => (s.some((i) => i.part_no === part_no) ? s : [...s, { part_no, qty: qty || 1 }]));
  const move = (from: number, to: number) => setItems((s) => {
    if (to < 0 || to >= s.length) return s;
    const next = [...s];
    const [row] = next.splice(from, 1);
    next.splice(to, 0, row);
    return next;
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { plan_date: date, responsible, checker, notes, drawing_mode: mode, items, rev: plan?.rev };
      return plan ? api.put<Plan>(`/projects/${pid}/assembly/plans/${plan.id}`, body) : api.post<Plan>(`/projects/${pid}/assembly/plans`, body);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["assembly", pid] });
      if (plan) onClose(); else nav(`/p/${pid}/assembly/${r.id}`);
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <div className="asm-form">
      <h2 style={{ marginTop: 0 }}>{plan ? tx("Plan {0}", plan.no) : tx("Yeni montaj planı")}</h2>
      <div className="card asm-fields">
        <label>{tx("Tarih")}<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <label>{tx("Montaj sorumlusu")}<input value={responsible} maxLength={120} onChange={(e) => setResponsible(e.target.value)} /></label>
        <label>{tx("Kontrol eden")}<input value={checker} maxLength={120} onChange={(e) => setChecker(e.target.value)} /></label>
        <label>{tx("Teknik resim")}
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="none">{tx("Resim ekleme")}</option>
            <option value="pages">{tx("Föyün arkasına resim sayfaları")}</option>
            <option value="list">{tx("Resim listesi ve QR")}</option>
            <option value="both">{tx("Liste ve resim sayfaları")}</option>
          </select>
        </label>
        <label className="asm-wide">{tx("Not")}<textarea rows={2} value={notes} maxLength={4000} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      <div className="asm-pick">
        {!locked && (
          <div className="card">
            <h3>{tx("Montaj seç")}</h3>
            <div className="row">
              <input type="search" style={{ flex: 1 }} placeholder={tx("Parça no veya ad ara…")} value={search} onChange={(e) => setSearch(e.target.value)} />
              <label className="row"><input type="checkbox" checked={onlyReady} onChange={(e) => setOnlyReady(e.target.checked)} /> {tx("Montaja hazır")}</label>
            </div>
            <div className="asm-scroll">
              {q.isLoading && <div className="muted">{tx("Yükleniyor…")}</div>}
              {list.map((c) => (
                <button key={c.part_no} type="button" className="asm-candidate" disabled={has(c.part_no)} style={{ paddingLeft: 8 + Math.max(0, c.depth - 1) * 16 }} onClick={() => add(c.part_no, c.qty)}>
                  <b>{c.part_no}</b>
                  <span className="muted">{c.name} · {tx("{0} kalem", fmt(c.kinds))} · {tx("{0} adet", fmt(c.qty))}</span>
                  <span style={{ flex: 1 }} />
                  {c.ready ? <span className="badge ok">{tx("Montaja hazır")}</span> : <Meter value={c.percent} />}
                </button>
              ))}
              {lone.length > 0 && <div className="muted" style={{ marginTop: 8 }}>{tx("Tekil parçalar")}</div>}
              {lone.map((c) => (
                <button key={c.part_no} type="button" className="asm-candidate" disabled={has(c.part_no)} onClick={() => add(c.part_no, c.qty)}>
                  <b>{c.part_no}</b><span className="muted">{tx("{0} adet", fmt(c.qty))}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="card">
          <h3>{tx("Plan ve rezervasyon sırası")}</h3>
          <p className="muted">{tx("Az olan parça önce üstteki montaja ayrılır. Sürükleyerek sırayı değiştirin.")}</p>
          {items.length === 0 && <div className="muted">{tx("Plana en az bir montaj ekleyin")}</div>}
          {items.map((it, i) => (
            <div key={it.part_no} className={dragged === i ? "asm-item dragging" : "asm-item"} draggable
              onDragStart={() => setDragged(i)} onDragEnd={() => setDragged(null)}
              onDragOver={(e) => { e.preventDefault(); if (dragged !== null && dragged !== i) { move(dragged, i); setDragged(i); } }}>
              <GripVertical size={15} className="muted" />
              <span className="asm-seq">{i + 1}</span>
              <b style={{ flex: 1 }}>{it.part_no}</b>
              <input className="asm-num" type="number" min={1} step="any" disabled={locked} aria-label={tx("Montaj adedi")} value={it.qty}
                onChange={(e) => { const qty = Number(e.target.value); setItems((s) => s.map((x, k) => (k === i ? { ...x, qty } : x))); }} />
              <button type="button" className="btn small" aria-label={tx("Yukarı")} onClick={() => move(i, i - 1)}><ArrowUp size={13} /></button>
              <button type="button" className="btn small" aria-label={tx("Aşağı")} onClick={() => move(i, i + 1)}><ArrowDown size={13} /></button>
              {!locked && <button type="button" className="btn small danger" aria-label={tx("Sil")} onClick={() => setItems((s) => s.filter((_, k) => k !== i))}><Trash2 size={13} /></button>}
            </div>
          ))}
        </div>
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={!items.length || !date || items.some((i) => !(i.qty > 0)) || save.isPending} onClick={() => save.mutate()}>
          {plan ? tx("Kaydet") : tx("Önizle")}
        </button>
      </div>
    </div>
  );
}
