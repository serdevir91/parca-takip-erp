import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, FileDown, FileSpreadsheet, FileUp, Printer, Trash2 } from "lucide-react";
import { api, blobUrl, download, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { LOCALE, tx } from "../api/i18n";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { fmt, Meter, PLAN_DONE, PLAN_DRAFT, PLAN_PUBLISHED, PlanForm, planDate, statusBadge, type Plan, type PlanExtra } from "./Assembly";

// Backend: backend/app/services/assembly.py plan_out, doc_out
type State = "ready" | "partial" | "run" | "none";
type Row = {
  item_id: number; path: string; poz: string; part_no: string; qty: number; need: number; is_sub: boolean; temin: string;
  kind: string; material: string; rev: string; allocated: number; mounted: boolean; state: State; notes: { text: string; warn: boolean }[];
};
type Step = { no: number; total: number; part_no: string; path: string; is_top: boolean; parent: string; per_parent: number; make: number; done: boolean; ready: boolean; rows: Row[] };
type Foy = {
  item_id: number; part_no: string; qty: number; name: string; rev: string; single: boolean; ready: boolean; done: boolean; percent: number;
  kinds: number; total: number; ready_rows: number; short_rows: number; extra_note: string; steps: Step[];
};
type Pick = { part_no: string; temin: string; material: string; rev: string; uses: string; need: number; extra: number; ready: number; short: number; status: string };
type Issue = { code: number; severity: string; part_no: string; message: string; action?: Change; extra_id?: number };
type Detail = Plan & { foys: Foy[]; picks: Pick[]; plan_total: number; pick_total: number; extra_total: number; issues: Issue[]; photos: { id: number; filename: string; uploaded_by: string }[] };
type Log = { id: number; ts: string; username: string; field: string; old: string | null; new: string | null };
type Change = { type: "ready" | "state" | "mounted" | "step" | "extra"; part_no: string; item_id?: number; path?: string; old?: unknown; new?: unknown; qty?: number };
type Preview = { changes: Change[]; issues: Issue[] };
type Tab = "plan" | "picks" | "foys" | "field" | "issues" | "history";
type Edit = { state?: "ready" | "run" | "none"; ready_qty?: number; mounted?: boolean };

const rowKey = (r: { item_id: number; path: string; part_no: string }) => `${r.item_id}|${r.path}|${r.part_no}`;
const stepKey = (itemId: number, path: string) => `${itemId}|${path}`;
const BOXES: ["ready" | "run" | "none", string, string][] = [
  ["ready", "Üretildi / Geldi", "1"], ["run", "Üretimde / Siparişte", "2"], ["none", "Üretilmedi / Gelmedi", "3"],
];

export default function AssemblyPlan() {
  const { pid } = useProject();
  const { id } = useParams();
  const planId = Number(id);
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const [tab, setTab] = useState<Tab>("plan");
  const [editing, setEditing] = useState(false);
  const [returned, setReturned] = useState<Preview | null>(null);
  const excelInput = useRef<HTMLInputElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const base = `/projects/${pid}/assembly/plans/${planId}`;
  const canEdit = can("assembly", "edit");
  const q = useQuery({ queryKey: ["assembly", pid, "plan", planId], queryFn: () => api.get<Detail>(base), enabled: !!pid });
  const refresh = () => qc.invalidateQueries({ queryKey: ["assembly", pid] });
  const fail = (e: unknown) => toast(errText(e), true);
  const status = useMutation({ mutationFn: (s: string) => api.post(`${base}/status`, { status: s }), onSuccess: refresh, onError: fail });
  const remove = useMutation({ mutationFn: () => api.del(base), onSuccess: () => { refresh(); nav(`/p/${pid}/assembly`); }, onError: fail });
  const excelIn = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return upload<Preview>(`${base}/return/preview`, form); },
    onSuccess: setReturned, onError: fail,
  });
  const photoIn = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return upload(`${base}/photos`, form); },
    onSuccess: () => { refresh(); setTab("field"); toast(tx("Fotoğraf yüklendi. Saha ekranında işaretleyin.")); }, onError: fail,
  });
  if (q.isError) return <Page><div className="card error">{errText(q.error)}</div></Page>;
  const d = q.data;
  if (!d) return <Page><div className="muted">{tx("Yükleniyor…")}</div></Page>;
  if (editing) return <Page><PlanForm pid={pid} plan={d} onClose={() => setEditing(false)} /></Page>;
  const errors = d.issues.filter((i) => i.severity === "error").length;
  const tabs: [Tab, string, number?][] = [
    ["plan", tx("Plan")], ["picks", tx("Toplama Listesi")], ["foys", tx("Föyler")], ["field", tx("Saha işleme")],
    ["issues", tx("Tutarlılık Uyarıları"), d.issues.length], ["history", tx("Geçmiş")],
  ];
  return (
    <Page full>
      <div className="asm-page">
      <div className="row asm-head">
        <Link className="muted" to={`/p/${pid}/assembly`}>{tx("Montaj föyleri")}</Link>
        <h2 style={{ margin: 0 }}>{tx("Plan {0}", d.no)}</h2>
        <span className={statusBadge(d.status)}>{tx(d.status)}</span>
        <span className="muted">{planDate(d.plan_date)}{d.responsible ? ` · ${d.responsible}` : ""}</span>
        <Meter value={d.percent ?? 0} />
        <span style={{ flex: 1 }} />
        <button className="btn small" onClick={() => download(`${base}/pdf`, `montaj_plani_${d.no}.pdf`).catch(fail)}><Printer size={14} /> {tx("Yazdır (PDF)")}</button>
        <button className="btn small" onClick={() => download(`${base}/excel`, `montaj_plani_${d.no}.xlsx`).catch(fail)}><FileSpreadsheet size={14} /> {tx("Excel'e aktar")}</button>
        {canEdit && d.status !== PLAN_DRAFT && (
          <>
            <button className="btn small" disabled={photoIn.isPending} onClick={() => photoInput.current?.click()}><Camera size={14} /> {tx("Fotoğraf yükle")}</button>
            <button className="btn small" disabled={excelIn.isPending} onClick={() => excelInput.current?.click()}><FileUp size={14} /> {tx("Excel geri yükle")}</button>
          </>
        )}
        {canEdit && d.status !== PLAN_DONE && <button className="btn small" onClick={() => setEditing(true)}>{tx("Düzenle")}</button>}
        {canEdit && d.status === PLAN_DRAFT && <button className="btn small primary" onClick={() => status.mutate(PLAN_PUBLISHED)}>{tx("Yayınla")}</button>}
        {canEdit && d.status === PLAN_PUBLISHED && <button className="btn small" onClick={() => status.mutate(PLAN_DONE)}>{tx("Tamamlandı say")}</button>}
        {canEdit && d.status === PLAN_DONE && <button className="btn small" onClick={() => status.mutate(PLAN_PUBLISHED)}>{tx("Yeniden aç")}</button>}
        {canEdit && d.status === PLAN_DRAFT && <button className="btn small danger" aria-label={tx("Sil")} disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 size={14} /></button>}
        <input ref={excelInput} type="file" hidden accept=".xlsx" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) excelIn.mutate(f); }} />
        <input ref={photoInput} type="file" hidden accept="image/*" capture="environment" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) photoIn.mutate(f); }} />
      </div>
      <div className="tabs" role="tablist">
        {tabs.map(([k, label, n]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {label}{n ? <span className={errors ? "badge err" : "badge warn"} style={{ marginLeft: 6 }}>{fmt(n)}</span> : null}
          </button>
        ))}
      </div>
      {tab === "plan" && <PlanTab d={d} pid={pid} base={base} canEdit={canEdit && d.status !== PLAN_DONE} />}
      {tab === "picks" && <PicksTab d={d} />}
      {tab === "foys" && <FoysTab d={d} base={base} />}
      {tab === "field" && <FieldTab d={d} base={base} canEdit={canEdit} onSaved={refresh} />}
      {tab === "issues" && <IssuesTab d={d} base={base} canEdit={canEdit} onSaved={refresh} />}
      {tab === "history" && <HistoryTab pid={pid} planId={planId} base={base} />}
      {returned && <ReturnModal preview={returned} base={base} onClose={() => setReturned(null)} onDone={refresh} />}
      </div>
    </Page>
  );
}

function PlanTab({ d, pid, base, canEdit }: { d: Detail; pid: number; base: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [part, setPart] = useState("");
  const [qty, setQty] = useState("1");
  const [assembly, setAssembly] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`${base}/extras`, { part_no: part.trim(), qty: Number(qty), assembly_no: assembly }),
    onSuccess: () => { setPart(""); setQty("1"); qc.invalidateQueries({ queryKey: ["assembly", pid] }); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: (id: number) => api.del(`${base}/extras/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assembly", pid] }),
    onError: (e) => toast(errText(e), true),
  });
  const columns = useMemo<GridColumn<Foy>[]>(() => [
    { accessorKey: "part_no", header: tx("Montaj / Parça No"), size: 170, card: "title" },
    { accessorKey: "name", header: tx("Tanım"), size: 200, cell: (c) => (c.row.original.single ? tx("Tekil parça – ana montaja doğrudan takılır") : c.row.original.extra_note || c.row.original.name) },
    { accessorKey: "qty", header: tx("Montaj Adedi"), size: 90 },
    { accessorKey: "kinds", header: tx("Parça Çeşidi"), size: 90 },
    { accessorKey: "total", header: tx("Toplam Parça"), size: 90 },
    { accessorKey: "ready_rows", header: tx("Hazır Kalem"), size: 90 },
    { accessorKey: "short_rows", header: tx("Eksik Kalem"), size: 90 },
    { accessorKey: "percent", header: tx("Hazırlık %"), size: 120, cell: (c) => <Meter value={c.row.original.percent} /> },
    { id: "state", header: tx("Durum"), size: 130, accessorFn: (r) => (r.done ? tx("Tamamlandı") : r.ready ? tx("Montaja hazır") : tx("Eksik var")) },
  ], []);
  return (
    <>
      <div className="asm-totals">
        <span>{tx("Plan toplamı")}: <b>{fmt(d.plan_total)}</b></span>
        <span>{tx("Ek adet")}: <b>{fmt(d.extra_total)}</b></span>
        <span>{tx("Toplama toplamı")}: <b>{fmt(d.pick_total)}</b></span>
      </div>
      <div className="asm-grid">
        <DataGrid<Foy> stateKey="Montaj planı" exportName={tx("Montaj Planı")} data={d.foys} columns={columns} getRowId={(r) => String(r.item_id)} emptyText={tx("Kayıt yok.")} />
      </div>
      <div className="card" style={{ marginTop: 10 }}>
        <h3 style={{ marginTop: 0 }}>{tx("Ek adetler")}</h3>
        <p className="muted">{tx("Ek adet plan ihtiyacından sonra ayrılır, montajı bekletmez.")}</p>
        {d.extras.map((e) => (
          <div key={e.id} className="row">
            <b>{e.part_no}</b><span>+{fmt(e.qty)}</span><span className="muted">{e.assembly_no} {e.note}</span>
            {canEdit && <button className="btn small danger" aria-label={tx("Sil")} onClick={() => del.mutate(e.id)}><Trash2 size={13} /></button>}
          </div>
        ))}
        {canEdit && (
          <form className="row" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
            <input list="asm-parts" placeholder={tx("Parça No")} value={part} onChange={(e) => setPart(e.target.value)} />
            <datalist id="asm-parts">{d.picks.map((p) => <option key={p.part_no} value={p.part_no} />)}</datalist>
            <input className="asm-num" type="number" min={1} step="any" aria-label={tx("Adet")} value={qty} onChange={(e) => setQty(e.target.value)} />
            <select value={assembly} aria-label={tx("Montaj")} onChange={(e) => setAssembly(e.target.value)}>
              <option value="">{tx("Montaj seçilmedi")}</option>
              {d.foys.map((f) => <option key={f.part_no} value={f.part_no}>{f.part_no}</option>)}
            </select>
            <button className="btn small" disabled={!part.trim() || !(Number(qty) > 0) || add.isPending}>{tx("Ekle")}</button>
          </form>
        )}
      </div>
    </>
  );
}

function PicksTab({ d }: { d: Detail }) {
  const columns = useMemo<GridColumn<Pick>[]>(() => [
    { accessorKey: "part_no", header: tx("Parça No"), size: 170, card: "title" },
    { accessorKey: "temin", header: tx("Temin"), size: 130, cell: (c) => tx(c.row.original.temin) },
    { accessorKey: "material", header: tx("Malzeme"), size: 130 },
    { accessorKey: "rev", header: tx("Rev"), size: 50 },
    { accessorKey: "uses", header: tx("Kullanıldığı Montaj (1 montaj için adet)"), size: 280 },
    { accessorKey: "need", header: tx("Toplam Gerekli"), size: 80 },
    { accessorKey: "ready", header: tx("Hazır"), size: 70 },
    { accessorKey: "short", header: tx("Eksik"), size: 70, cell: (c) => (c.row.original.short > 0 ? <b>{fmt(c.row.original.short)}</b> : "✓") },
    { accessorKey: "status", header: tx("Durum"), size: 200 },
  ], []);
  return <DataGrid<Pick> stateKey="Toplama listesi" exportName={tx("Toplama Listesi")} data={d.picks} columns={columns} getRowId={(r) => r.part_no} emptyText={tx("Kayıt yok.")} />;
}

function FoysTab({ d, base }: { d: Detail; base: string }) {
  const toast = useToast();
  return (
    <div className="asm-foys">
      {d.foys.filter((f) => !f.single).map((f) => (
        <div key={f.item_id} className="card">
          <div className="row">
            <h3 style={{ margin: 0 }}>{f.part_no}</h3>
            <span className="muted">{tx("Montaj adedi:")} {fmt(f.qty)}</span>
            <Meter value={f.percent} />
            <span style={{ flex: 1 }} />
            <button className="btn small" onClick={() => download(`${base}/pdf?foy=${encodeURIComponent(f.part_no)}`, `${f.part_no}.pdf`).catch((e) => toast(errText(e), true))}><FileDown size={14} /> {tx("Bu föyü yazdır")}</button>
          </div>
          {f.steps.map((s) => (
            <div key={s.path} className="asm-step">
              <div className="asm-step-title">
                <b>{tx("ADIM {0}/{1}", s.no, s.total)} · {s.is_top ? tx("ANA MONTAJ") : tx("ALT MONTAJ")}: {s.part_no}</b>
                <span>{tx("Yapılacak:")} {fmt(s.make)} {tx("adet")} {s.done ? "☒" : "☐"}</span>
              </div>
              <div className="asm-table">
                <table className="simple">
                  <thead><tr><th>{tx("Poz")}</th><th>{tx("Parça No")}</th><th>{tx("Temin")}</th><th>{tx("Adet")}</th><th>{tx("Toplam Gerekli")}</th><th>{tx("Durum")}</th><th>{tx("Not")}</th></tr></thead>
                  <tbody>
                    {s.rows.map((r) => (
                      <tr key={r.part_no}>
                        <td>{r.poz}</td><td><b>{r.part_no}</b></td><td>{r.is_sub ? tx("Alt montaj") : tx(r.temin || "Belirtilmemiş")}</td>
                        <td>{fmt(r.qty)}</td><td>{fmt(r.need)}</td>
                        <td>{r.is_sub ? "—" : boxText(r)}{r.mounted ? ` · ${tx("Takıldı")}` : ""}</td>
                        <td className="muted">{r.notes.map((n) => n.text).join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function boxText(r: Row) {
  const state = r.state === "partial" ? "run" : r.state;
  const hazir = r.kind === "Hazır Alım";
  if (state === "ready") return hazir ? tx("Geldi") : tx("Üretildi");
  if (state === "run") return hazir ? tx("Siparişte") : tx("Üretimde");
  return hazir ? tx("Gelmedi") : tx("Üretilmedi");
}

function FieldTab({ d, base, canEdit, onSaved }: { d: Detail; base: string; canEdit: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [steps, setSteps] = useState<Record<string, boolean>>({});
  const [cursor, setCursor] = useState(0);
  const [foyId, setFoyId] = useState<number | null>(d.foys[0]?.item_id ?? null);
  const foy = d.foys.find((f) => f.item_id === foyId) ?? d.foys[0];
  const rows = useMemo(() => foy?.steps.flatMap((s) => s.rows) ?? [], [foy]);
  const active = useRef<HTMLTableRowElement>(null);
  const blocked = d.status === PLAN_DRAFT || !canEdit;
  const dirty = Object.keys(edits).length + Object.keys(steps).length;
  const edit = (r: Row, e: Edit) => setEdits((s) => ({ ...s, [rowKey(r)]: { ...s[rowKey(r)], ...e } }));
  const save = useMutation({
    mutationFn: () => api.post<{ changed: number }>(`${base}/field`, {
      ops: Object.entries(edits).map(([k, v]) => {
        const [item_id, path, part_no] = k.split("|");
        return { item_id: Number(item_id), path, part_no, ...v };
      }),
      steps: Object.entries(steps).map(([k, done]) => {
        const [item_id, path] = k.split("|");
        return { item_id: Number(item_id), path, done };
      }),
    }),
    onSuccess: (r) => { setEdits({}); setSteps({}); onSaved(); toast(tx("{0} değişiklik kaydedildi", fmt(r.changed))); },
    onError: (e) => toast(errText(e), true),
  });
  useEffect(() => { active.current?.scrollIntoView({ block: "nearest" }); }, [cursor]);
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "SELECT") return;
    const r = rows[cursor];
    if (e.key === "ArrowDown") setCursor((c) => Math.min(rows.length - 1, c + 1));
    else if (e.key === "ArrowUp") setCursor((c) => Math.max(0, c - 1));
    else if (!r || blocked) return;
    else if (["1", "2", "3"].includes(e.key) && !r.is_sub) edit(r, { state: BOXES[Number(e.key) - 1][0], ready_qty: undefined });
    else if (e.key === "4") edit(r, { mounted: !(edits[rowKey(r)]?.mounted ?? r.mounted) });
    else return;
    e.preventDefault();
  };
  if (!foy) return <div className="muted">{tx("Kayıt yok.")}</div>;
  return (
    <div className="asm-field">
      <div className="asm-field-main" tabIndex={0} onKeyDown={onKey}>
        <div className="row">
          <select value={foy.item_id} aria-label={tx("Föy")} onChange={(e) => { setFoyId(Number(e.target.value)); setCursor(0); }}>
            {d.foys.map((f) => <option key={f.item_id} value={f.item_id}>{f.part_no}</option>)}
          </select>
          <span className="muted">{tx("Oklar: satır · 1 / 2 / 3: durum · 4: takıldı")}</span>
          <span style={{ flex: 1 }} />
          {!blocked && <button className="btn primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}{dirty ? ` (${fmt(dirty)})` : ""}</button>}
        </div>
        {d.status === PLAN_DRAFT && <div className="card">{tx("Önce planı yayınlayın")}</div>}
        {foy.steps.map((s) => {
          const key = stepKey(foy.item_id, s.path);
          const done = steps[key] ?? s.done;
          return (
            <div key={s.path} className="asm-step">
              <label className="asm-step-title">
                <b>{tx("ADIM {0}/{1}", s.no, s.total)} · {s.part_no}</b>
                <span>{tx("Yapılacak:")} {fmt(s.make)} {tx("adet")}{" "}
                  <input type="checkbox" checked={done} disabled={blocked} onChange={(e) => { const v = e.target.checked; setSteps((x) => ({ ...x, [key]: v })); }} />
                </span>
              </label>
              <div className="asm-table">
                <table className="simple">
                  <thead><tr><th>{tx("Parça No")}</th><th>{tx("Gerekli")}</th>{BOXES.map(([k, l, n]) => <th key={k}>{n} · {tx(l)}</th>)}<th>{tx("Hazır adet")}</th><th>4 · {tx("Takıldı")}</th></tr></thead>
                  <tbody>
                    {s.rows.map((r) => {
                      const i = rows.indexOf(r);
                      const e = edits[rowKey(r)] ?? {};
                      const state = e.state ?? (r.state === "partial" ? "run" : r.state);
                      return (
                        <tr key={r.part_no} ref={i === cursor ? active : undefined} className={i === cursor ? "asm-cursor" : ""} onClick={() => setCursor(i)}>
                          <td><b>{r.part_no}</b></td><td>{fmt(r.need)}</td>
                          {BOXES.map(([k, l]) => (
                            <td key={k} className="asm-box">
                              {r.is_sub ? "—" : <button type="button" disabled={blocked} aria-label={tx(l)} aria-pressed={state === k} onClick={() => edit(r, { state: k, ready_qty: undefined })}>{state === k ? "☒" : "☐"}</button>}
                            </td>
                          ))}
                          <td>{r.is_sub ? "—" : <input className="asm-num" inputMode="decimal" disabled={blocked} aria-label={tx("Hazır adet")} value={e.ready_qty ?? Math.min(r.allocated, r.need)}
                            onChange={(x) => edit(r, { ready_qty: Number(x.target.value.replace(",", ".")) || 0, state: undefined })} />}</td>
                          <td className="asm-box"><button type="button" disabled={blocked} aria-label={tx("Takıldı")} aria-pressed={e.mounted ?? r.mounted} onClick={() => edit(r, { mounted: !(e.mounted ?? r.mounted) })}>{(e.mounted ?? r.mounted) ? "☒" : "☐"}</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>
      {d.photos.length > 0 && <aside className="asm-photos">{d.photos.map((p) => <SheetPhoto key={p.id} url={`${base}/photos/${p.id}`} name={p.filename} />)}</aside>}
    </div>
  );
}

function SheetPhoto({ url, name }: { url: string; name: string }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let kept = "";
    let gone = false;
    blobUrl(url).then((u) => { if (gone) URL.revokeObjectURL(u); else { kept = u; setSrc(u); } }).catch(() => undefined);
    return () => { gone = true; if (kept) URL.revokeObjectURL(kept); };
  }, [url]);
  return src ? <a href={src} target="_blank" rel="noreferrer"><img src={src} alt={name} /></a> : <div className="muted">{name}</div>;
}

function IssueList({ issues, onAccept, accepted }: { issues: Issue[]; onAccept?: (i: Issue) => void; accepted?: Set<Issue> }) {
  if (!issues.length) return <div className="muted">{tx("Tutarsızlık yok.")}</div>;
  return (
    <>
      {issues.map((i, n) => (
        <div key={n} className={`asm-issue ${i.severity}`}>
          <span className={i.severity === "error" ? "badge err" : i.severity === "warning" ? "badge warn" : "badge"}>{fmt(i.code)}</span>
          <b>{i.part_no}</b>
          <span style={{ flex: 1 }}>{i.message}</span>
          {i.action && onAccept && (
            <button type="button" className={accepted?.has(i) ? "btn small primary" : "btn small"} onClick={() => onAccept(i)}>{tx("Ek adet olarak kaydet")}</button>
          )}
        </div>
      ))}
    </>
  );
}

function IssuesTab({ d, base, canEdit, onSaved }: { d: Detail; base: string; canEdit: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [fix, setFix] = useState<{ extra: PlanExtra; part: string; assembly: string } | null>(null);
  const save = useMutation({
    mutationFn: () => api.put(`${base}/extras/${fix!.extra.id}`, { part_no: fix!.part, qty: fix!.extra.qty, assembly_no: fix!.assembly, note: fix!.extra.note }),
    onSuccess: () => { setFix(null); onSaved(); },
    onError: (e) => toast(errText(e), true),
  });
  const wrong = d.issues.filter((i) => i.extra_id);
  return (
    <div className="card">
      <IssueList issues={d.issues} />
      {canEdit && wrong.map((i) => {
        const extra = d.extras.find((e) => e.id === i.extra_id);
        if (!extra) return null;
        return <button key={extra.id} className="btn small" style={{ marginTop: 8 }} onClick={() => setFix({ extra, part: extra.part_no, assembly: extra.assembly_no })}>{tx("{0} ek adedini düzelt", extra.part_no)}</button>;
      })}
      {fix && (
        <form className="row" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <select aria-label={tx("Parça No")} value={fix.part} onChange={(e) => setFix({ ...fix, part: e.target.value })}>
            {[fix.extra.part_no, ...d.picks.map((p) => p.part_no).filter((p) => p !== fix.extra.part_no)].map((p) => <option key={p}>{p}</option>)}
          </select>
          <select aria-label={tx("Montaj")} value={fix.assembly} onChange={(e) => setFix({ ...fix, assembly: e.target.value })}>
            <option value="">{tx("Montaj seçilmedi")}</option>
            {d.foys.map((f) => <option key={f.part_no}>{f.part_no}</option>)}
          </select>
          <button className="btn small primary" disabled={save.isPending}>{tx("Kaydet")}</button>
        </form>
      )}
    </div>
  );
}

function HistoryTab({ pid, planId, base }: { pid: number; planId: number; base: string }) {
  const q = useQuery({ queryKey: ["assembly", pid, "history", planId], queryFn: () => api.get<{ rows: Log[] }>(`${base}/history`) });
  const columns = useMemo<GridColumn<Log>[]>(() => [
    { accessorKey: "ts", header: tx("Zaman"), size: 160, cell: (c) => new Date(c.row.original.ts).toLocaleString(LOCALE) },
    { accessorKey: "username", header: tx("Kullanıcı"), size: 120 },
    { accessorKey: "field", header: tx("Alan"), size: 220, card: "title", cell: (c) => tx(c.row.original.field) },
    { accessorKey: "old", header: tx("Eski"), size: 160 },
    { accessorKey: "new", header: tx("Yeni"), size: 240 },
  ], []);
  return <DataGrid<Log> stateKey="Montaj geçmişi" exportName={tx("Geçmiş")} data={q.data?.rows ?? []} columns={columns} getRowId={(r) => String(r.id)} emptyText={tx("Kayıt yok.")} />;
}

function describe(c: Change): string {
  const where = c.path !== undefined && c.part_no ? c.part_no : c.part_no;
  if (c.type === "ready") return tx("{0}: hazır {1} → {2}", where, fmt(Number(c.old)), fmt(Number(c.new)));
  if (c.type === "state") return tx("{0}: durum kutusu değişti", where);
  if (c.type === "mounted") return c.new ? tx("{0}: takıldı", where) : tx("{0}: takıldı işareti kaldırıldı", where);
  if (c.type === "step") return c.new ? tx("{0}: adım tamam", where) : tx("{0}: adım geri alındı", where);
  return tx("{0}: +{1} ek adet", where, fmt(c.qty ?? 0));
}

function ReturnModal({ preview, base, onClose, onDone }: { preview: Preview; base: string; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [skip, setSkip] = useState<Set<number>>(new Set());
  const [extras, setExtras] = useState<Set<Issue>>(new Set());
  const [sure, setSure] = useState(false);
  const errors = preview.issues.filter((i) => i.severity === "error").length;
  const chosen = [...preview.changes.filter((_, i) => !skip.has(i)), ...[...extras].map((i) => i.action!)];
  const apply = useMutation({
    mutationFn: () => api.post<{ changed: number }>(`${base}/return/apply`, { changes: chosen }),
    onSuccess: (r) => { onDone(); onClose(); toast(tx("{0} değişiklik kaydedildi", fmt(r.changed))); },
    onError: (e) => toast(errText(e), true),
  });
  const toggle = (i: Issue) => setExtras((s) => { const n = new Set(s); if (!n.delete(i)) n.add(i); return n; });
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{tx("Excel geri yükleme önizlemesi")}</h3>
        <h4>{tx("Tutarlılık Uyarıları")}</h4>
        <div className="asm-scroll"><IssueList issues={preview.issues} onAccept={toggle} accepted={extras} /></div>
        <h4>{tx("Değişiklikler")}</h4>
        <div className="asm-scroll">
          {preview.changes.length === 0 && <div className="muted">{tx("Değişiklik yok.")}</div>}
          {preview.changes.map((c, i) => (
            <label key={i} className="row">
              <input type="checkbox" checked={!skip.has(i)} onChange={() => setSkip((s) => { const n = new Set(s); if (!n.delete(i)) n.add(i); return n; })} />
              {describe(c)}
            </label>
          ))}
        </div>
        {errors > 0 && <label className="row"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> {tx("{0} hataya rağmen seçilenleri uygula", fmt(errors))}</label>}
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
          <button className="btn primary" disabled={!chosen.length || (errors > 0 && !sure) || apply.isPending} onClick={() => apply.mutate()}>{tx("Uygula")}</button>
        </div>
      </div>
    </div>
  );
}
