import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, download, upload } from "../api/client";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";

// ---------- types (backend/app/api/bom.py version_out, services/bomimport.py) ----------
type BomStats = {
  root_part_no?: string; rows?: number; non_fastener_rows?: number; fastener_rows?: number;
  fastener_unique?: number; fastener_total?: number; in_purchased_rows?: number; parts?: number;
  assemblies?: number; nonstandard?: number; parse_warnings?: string[];
};
type CompareSummary = {
  added: number; removed: number; rev_changed: number; qty_changed: number;
  fastener_changes: number; warnings: number; first: boolean;
};
type FieldChange = { part_no: string; old: string | number | null; new: string | number | null };
type FastenerChange = { key: string; desc: string; std: string; size: string; old: number; new: number; delta: number };
type AliasSuggestion = { removed: string; added: string; base: string };
type BomWarning = { part_no: string; kind: string; severity: "error" | "warning" | string; message: string };
type CompareJson = {
  first?: boolean; is_empty?: boolean; added?: string[]; removed?: string[];
  rev_changed?: FieldChange[]; material_changed?: FieldChange[]; procurement_changed?: FieldChange[];
  qty_changed?: FieldChange[]; fastener_changes?: FastenerChange[];
  fastener_total_old?: number; fastener_total_new?: number; fastener_big_drop?: boolean;
  alias_suggestions?: AliasSuggestion[]; warnings?: BomWarning[];
};
type BomVersion = {
  id: number; seq: number; filename: string; status: string;
  uploaded_by: string; uploaded_at: string | null; approved_by: string; approved_at: string | null;
  note: string; previous_version_id: number | null; is_current: boolean; can_undo: boolean;
  stats: BomStats; summary: CompareSummary;
};
type BomVersionDetail = BomVersion & { compare: CompareJson; alias_suggestions: AliasSuggestion[]; warnings: BomWarning[] };
type TreeRow = {
  id: number; seq: number; level: string; depth: number; part_no: string; file_name: string; ext: string;
  qty: number; total_qty: number; material: string; rev: string; procurement: string; coating: string;
  main_group: string; parent_part_no: string; row_type: string; status: string; status_color: string;
  nonstandard: boolean; in_purchased: boolean;
};
type RowsResp = { version: BomVersion; count: number; rows: TreeRow[] };
type Alias = { id: number; alias: string; part_no: string; created_by: string; created_at: string | null; state_moved?: boolean };

// ---------- labels / helpers ----------
const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "Onay bekliyor", cls: "badge warn" },
  approved: { label: "Onaylandı", cls: "badge bomv-ok" },
  rejected: { label: "Reddedildi", cls: "badge err" },
  undone: { label: "Geri alındı", cls: "badge" },
  superseded: { label: "Eski sürüm", cls: "badge" },
};
const WARN_KIND: Record<string, string> = {
  removed_with_progress: "Üretildi/ilerleme kaydı olan parça BOM'dan kalktı",
  rev_after_done: "Tamamlanmış parçada revizyon değişti (eski revizyonla üretilmiş olabilir)",
  fastener_big_drop: "Bağlantı elemanı toplam adedinde büyük düşüş",
  root_mismatch: "Dosyanın ana montajı proje ile uyuşmuyor",
};
const nf = (v: number | null | undefined) => Number(v ?? 0).toLocaleString("tr-TR");
const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("tr-TR") : "—");
const shown = (v: unknown) => (v === null || v === undefined || v === "" ? "(boş)" : String(v));
const lc = (s: string) => s.toLocaleLowerCase("tr-TR");
const pairKey = (a: AliasSuggestion) => `${a.removed}\u0000${a.added}`;

function StatusBadge({ v }: { v: Pick<BomVersion, "status" | "is_current"> }) {
  const s = STATUS[v.status] ?? { label: v.status, cls: "badge" };
  return (
    <span className="row" style={{ gap: 4, display: "inline-flex" }}>
      <span className={s.cls}>{s.label}</span>
      {v.is_current && <span className="badge new">Güncel</span>}
    </span>
  );
}

function Confirm(p: { title: string; children: ReactNode; okText: string; danger?: boolean; busy?: boolean; onOk: () => void; onClose: () => void }) {
  return (
    <div className="modal-back" onClick={p.onClose}>
      <div className="modal" style={{ maxWidth: 640 }} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 style={{ marginTop: 0 }}>{p.title}</h3>
        <div>{p.children}</div>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button className="btn" onClick={p.onClose} disabled={p.busy}>Vazgeç</button>
          <button className={p.danger ? "btn danger" : "btn primary"} onClick={p.onOk} disabled={p.busy}>
            {p.busy ? "İşleniyor…" : p.okText}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- page ----------
export default function BomVersions() {
  const { pid, project } = useProject();
  const canDesign = useAuth().can("projects", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);

  const versions = useQuery({
    queryKey: ["bom-versions", pid],
    queryFn: () => api.get<BomVersion[]>(`/projects/${pid}/bom/versions`),
    enabled: !!pid,
  });

  // Default selection: first pending, else current, else newest
  useEffect(() => {
    const list = versions.data;
    if (!list?.length) return;
    if (selected !== null && list.some((v) => v.id === selected)) return;
    const pick = list.find((v) => v.status === "pending") ?? list.find((v) => v.is_current) ?? list[0];
    setSelected(pick.id);
  }, [versions.data, selected]);

  // Approval / undo change tracking, parts, dashboard etc.: refresh everything
  const refreshAll = () => qc.invalidateQueries();

  return (
    <Page>
      <div className="row" style={{ alignItems: "baseline", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>BOM Sürümleri</h2>
        {project && <span className="muted">{project.name} · {project.root_part_no}</span>}
      </div>

      {canDesign && !project?.archived && (
        <UploadCard pid={pid} onDone={(v) => {
          qc.invalidateQueries({ queryKey: ["bom-versions", pid] });
          qc.invalidateQueries({ queryKey: ["project", pid] });
          setSelected(v.id);
        }} />
      )}

      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Sürüm geçmişi</h3>
        {versions.isLoading && <div className="muted">Yükleniyor…</div>}
        {versions.error && <div className="badge err">{errText(versions.error)}</div>}
        {versions.data && versions.data.length === 0 && <div className="muted">Henüz BOM yüklenmedi.</div>}
        {versions.data && versions.data.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table className="simple bomv-table">
              <thead>
                <tr>
                  <th>Sürüm</th><th>Dosya</th><th>Durum</th><th>Yükleyen</th><th>Yükleme</th>
                  <th>Onaylayan</th><th>Onay</th><th>Değişiklik</th><th>Not</th>
                </tr>
              </thead>
              <tbody>
                {versions.data.map((v) => (
                  <tr key={v.id} className={v.id === selected ? "bomv-sel" : ""} onClick={() => setSelected(v.id)} style={{ cursor: "pointer" }}>
                    <td><b>#{v.seq}</b></td>
                    <td>{v.filename}</td>
                    <td><StatusBadge v={v} /></td>
                    <td>{v.uploaded_by || "—"}</td>
                    <td>{fmtDate(v.uploaded_at)}</td>
                    <td>{v.approved_by || "—"}</td>
                    <td>{fmtDate(v.approved_at)}</td>
                    <td>
                      {v.summary.first ? <span className="muted">İlk sürüm</span> : (
                        <span className="bomv-chips">
                          <span title="Eklenen">+{nf(v.summary.added)}</span>
                          <span title="Kaldırılan">−{nf(v.summary.removed)}</span>
                          <span title="Revizyon değişen">Rev {nf(v.summary.rev_changed)}</span>
                          <span title="Adet değişen">Adet {nf(v.summary.qty_changed)}</span>
                          {v.summary.warnings > 0 && <span className="badge warn">{nf(v.summary.warnings)} uyarı</span>}
                        </span>
                      )}
                    </td>
                    <td className="muted">{v.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected !== null && <VersionDetail pid={pid} vid={selected} canDesign={canDesign} refreshAll={refreshAll}
        onUndone={(cur) => setSelected(cur)} toast={toast} />}

      <AliasCard pid={pid} canDesign={canDesign} />
    </Page>
  );
}

// ---------- upload ----------
function UploadCard({ pid, onDone }: { pid: number; onDone: (v: BomVersion) => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [pct, setPct] = useState<number | null>(null);

  const m = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file as File);
      fd.append("note", note);
      setPct(0);
      return upload<BomVersionDetail>(`/projects/${pid}/bom/upload`, fd, setPct);
    },
    onSuccess: (v) => {
      toast(`Sürüm #${v.seq} yüklendi; karşılaştırmayı inceleyip onaylayın.`);
      setFile(null);
      setNote("");
      if (fileRef.current) fileRef.current.value = "";
      onDone(v);
    },
    onError: (e) => toast(errText(e), true),
    onSettled: () => setPct(null),
  });

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <h3 style={{ marginTop: 0 }}>Yeni BOM yükle</h3>
      <div className="row" style={{ alignItems: "center" }}>
        <input ref={fileRef} type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={m.isPending} />
        <input placeholder="Not (isteğe bağlı)" value={note} onChange={(e) => setNote(e.target.value)} style={{ minWidth: 240 }} disabled={m.isPending} />
        <button className="btn primary" disabled={!file || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? "Yükleniyor…" : "Yükle"}
        </button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        SolidWorks BOM dışa aktarımı (.csv, ayraç “;”). Yüklenen sürüm onaylanana kadar takip listesini değiştirmez.
      </div>
      {pct !== null && (
        <div style={{ marginTop: 8 }}>
          <div className="progress"><div style={{ width: `${pct}%` }} /></div>
          <div className="muted" style={{ fontSize: 12 }}>{pct < 100 ? `%${pct} gönderildi` : "Sunucuda işleniyor ve karşılaştırılıyor…"}</div>
        </div>
      )}
    </div>
  );
}

// ---------- version detail ----------
type DetailProps = {
  pid: number; vid: number; canDesign: boolean; refreshAll: () => Promise<unknown>;
  onUndone: (currentId: number) => void; toast: (t: string, err?: boolean) => void;
};

function VersionDetail({ pid, vid, canDesign, refreshAll, onUndone, toast }: DetailProps) {
  const [tab, setTab] = useState<"compare" | "rows">("compare");
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<"approve" | "reject" | "undo" | null>(null);

  const q = useQuery({
    queryKey: ["bom-version", pid, vid],
    queryFn: () => api.get<BomVersionDetail>(`/projects/${pid}/bom/versions/${vid}`),
  });
  const v = q.data;
  useEffect(() => setAccepted(new Set()), [vid]);

  const approve = useMutation({
    mutationFn: () => {
      const pairs = (v?.alias_suggestions ?? []).filter((a) => accepted.has(pairKey(a))).map(({ removed, added }) => ({ removed, added }));
      return api.post<BomVersionDetail>(`/projects/${pid}/bom/versions/${vid}/approve`, { alias_accept: pairs });
    },
    onSuccess: (r) => { toast(`Sürüm #${r.seq} onaylandı; güncel sürüm oldu.`); setModal(null); refreshAll(); },
    onError: (e) => toast(errText(e), true),
  });
  const reject = useMutation({
    mutationFn: () => api.post<BomVersion>(`/projects/${pid}/bom/versions/${vid}/reject`),
    onSuccess: (r) => { toast(`Sürüm #${r.seq} reddedildi.`); setModal(null); refreshAll(); },
    onError: (e) => toast(errText(e), true),
  });
  const undo = useMutation({
    mutationFn: () => api.post<{ undone: BomVersion; current: BomVersion | null }>(`/projects/${pid}/bom/undo`),
    onSuccess: (r) => {
      toast(`Sürüm #${r.undone.seq} onayı geri alındı.${r.current ? ` Güncel sürüm: #${r.current.seq}` : ""}`);
      setModal(null);
      if (r.current) onUndone(r.current.id);
      refreshAll();
    },
    onError: (e) => toast(errText(e), true),
  });
  const dl = useMutation({
    mutationFn: () => download(`/projects/${pid}/bom/versions/${vid}/file`, v?.filename || "bom.csv"),
    onError: (e) => toast(errText(e), true),
  });

  if (q.isLoading) return <div className="card" style={{ marginBottom: 12 }}><span className="muted">Sürüm yükleniyor…</span></div>;
  if (q.error || !v) return <div className="card" style={{ marginBottom: 12 }}><span className="badge err">{errText(q.error)}</span></div>;

  const cj = v.compare ?? {};
  const warnings = v.warnings ?? [];
  const errors = warnings.filter((w) => w.severity === "error");
  const pending = v.status === "pending";
  const s = v.stats ?? {};
  const acceptedCount = (v.alias_suggestions ?? []).filter((a) => accepted.has(pairKey(a))).length;

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="row" style={{ alignItems: "center", marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Sürüm #{v.seq} · {v.filename}</h3>
        <StatusBadge v={v} />
        <span style={{ flex: 1 }} />
        <button className="btn small" onClick={() => dl.mutate()} disabled={dl.isPending}>Orijinal dosyayı indir</button>
        {canDesign && pending && (
          <>
            <button className="btn small primary" onClick={() => setModal("approve")}>Onayla</button>
            <button className="btn small danger" onClick={() => setModal("reject")}>Reddet</button>
          </>
        )}
        {canDesign && v.can_undo && <button className="btn small danger" onClick={() => setModal("undo")}>Son onayı geri al</button>}
      </div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
        Yükleyen: {v.uploaded_by || "—"} · {fmtDate(v.uploaded_at)}
        {v.approved_by && <> · Onaylayan: {v.approved_by} · {fmtDate(v.approved_at)}</>}
        {s.root_part_no && <> · Ana montaj: {s.root_part_no}</>}
        {v.note && <> · Not: {v.note}</>}
      </div>

      <div className="grid kpis" style={{ marginBottom: 12 }}>
        <Kpi label="BOM satırı" value={s.rows} />
        <Kpi label="Parça (benzersiz)" value={s.parts} />
        <Kpi label="Montaj" value={s.assemblies} />
        <Kpi label="Bağlantı elemanı satırı" value={s.fastener_rows} />
        <Kpi label="Bağlantı elemanı kalemi" value={s.fastener_unique} />
        <Kpi label="Bağlantı elemanı toplam adet" value={s.fastener_total} />
        <Kpi label="Satın alınan montaj içi satır" value={s.in_purchased_rows} />
        <Kpi label="Standart dışı isim" value={s.nonstandard} />
      </div>
      {!!s.parse_warnings?.length && (
        <Collapsible title="Dosya okuma uyarıları" count={s.parse_warnings.length}>
          <ul className="bomv-list">{s.parse_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </Collapsible>
      )}

      <div className="tabs">
        <button className={tab === "compare" ? "active" : ""} onClick={() => setTab("compare")}>Karşılaştırma</button>
        <button className={tab === "rows" ? "active" : ""} onClick={() => setTab("rows")}>Ağaç satırları</button>
      </div>

      {tab === "compare" ? (
        <>
          {warnings.length > 0 && (
            <div className="bomv-warns">
              {warnings.map((w, i) => (
                <div key={i} className={w.severity === "error" ? "bomv-warn err" : "bomv-warn"}>
                  <b>{WARN_KIND[w.kind] ?? w.kind}</b>
                  <div>{w.message}</div>
                </div>
              ))}
            </div>
          )}
          <AliasSuggestions items={v.alias_suggestions ?? []} accepted={accepted} setAccepted={setAccepted}
            editable={canDesign && pending} status={v.status} />
          <CompareView cj={cj} warnings={warnings} />
        </>
      ) : (
        <TreeRows pid={pid} vid={vid} />
      )}

      {modal === "approve" && (
        <Confirm title={`Sürüm #${v.seq} onaylansın mı?`} okText="Onayla" busy={approve.isPending}
          onOk={() => approve.mutate()} onClose={() => setModal(null)}>
          <p>Onaylandığında bu sürüm projenin <b>güncel BOM'u</b> olur:</p>
          <ul>
            {cj.first ? <li>İlk sürüm: tüm parçalar varsayılan durumla takip listesine eklenir.</li> : (
              <>
                <li><b>{nf(cj.added?.length)}</b> yeni parça varsayılan durumla eklenir ve “Yeni” etiketi alır.</li>
                <li><b>{nf(cj.removed?.length)}</b> parça listeden çıkar (veritabanında arşivlenir, geçmiş sürümde görülebilir).</li>
                <li>Revizyon: {nf(cj.rev_changed?.length)}, adet: {nf(cj.qty_changed?.length)}, malzeme: {nf(cj.material_changed?.length)}, temin: {nf(cj.procurement_changed?.length)} değişiklik bilgi olarak işlenir.</li>
                <li>Bağlantı elemanı toplam adedi {nf(cj.fastener_total_old)} → {nf(cj.fastener_total_new)}.</li>
              </>
            )}
            <li>Mevcut parçaların takip bilgileri (ilerleme, temin değişikliği, notlar, eksik satırları) korunur.</li>
            {acceptedCount > 0 && <li><b>{nf(acceptedCount)}</b> eşleştirme önerisi kabul edildi: eski numaraların durumu yeni numaraya taşınır ve takma ad oluşturulur.</li>}
          </ul>
          {warnings.length > 0 && (
            <div className={errors.length ? "bomv-warn err" : "bomv-warn"}>
              <b>{nf(warnings.length)} uyarı var{errors.length ? ` (${nf(errors.length)} kritik)` : ""}.</b> Onaylamadan önce karşılaştırmayı inceleyin.
            </div>
          )}
          <p className="muted" style={{ fontSize: 12 }}>Gerekirse “Son onayı geri al” ile bu işlem geri alınabilir.</p>
        </Confirm>
      )}
      {modal === "reject" && (
        <Confirm title={`Sürüm #${v.seq} reddedilsin mi?`} okText="Reddet" danger busy={reject.isPending}
          onOk={() => reject.mutate()} onClose={() => setModal(null)}>
          <p>Sürüm “Reddedildi” olarak işaretlenir ve geçmişte kalır. Takip listesi ve güncel sürüm <b>değişmez</b>.</p>
        </Confirm>
      )}
      {modal === "undo" && (
        <Confirm title="Son onay geri alınsın mı?" okText="Geri al" danger busy={undo.isPending}
          onOk={() => undo.mutate()} onClose={() => setModal(null)}>
          <p>Sürüm #{v.seq} onayı geri alınır; önceki onaylı sürüm yeniden güncel olur.</p>
          <ul>
            <li>Onayla eklenen parçalar ve kabul edilen eşleştirmeler kaldırılır, kaldırılan parçalar geri gelir.</li>
            <li><b>Bu onaydan sonra yapılan takip değişiklikleri (ilerleme, notlar vb.) kaybolur.</b></li>
          </ul>
        </Confirm>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{nf(value)}</div>
    </div>
  );
}

function Collapsible({ title, count, children, defaultOpen, tone }: { title: string; count: number; children: ReactNode; defaultOpen?: boolean; tone?: "err" | "warn" }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="bomv-sec">
      <button className="bomv-sec-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span>{open ? "▾" : "▸"}</span> {title}
        <span className={tone ? `badge ${tone}` : "badge"}>{nf(count)}</span>
      </button>
      {open && <div className="bomv-sec-body">{children}</div>}
    </div>
  );
}

// ---------- alias suggestions ----------
function AliasSuggestions(p: { items: AliasSuggestion[]; accepted: Set<string>; setAccepted: (s: Set<string>) => void; editable: boolean; status: string }) {
  if (!p.items.length) return null;
  const toggle = (k: string) => {
    const n = new Set(p.accepted);
    if (n.has(k)) n.delete(k); else n.add(k);
    p.setAccepted(n);
  };
  const all = p.items.every((a) => p.accepted.has(pairKey(a)));
  return (
    <div className="card bomv-alias-sug" style={{ marginBottom: 12 }}>
      <b>Olası eşleştirmeler: aynı parça mı?</b>
      <div className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>
        Kaldırılan ve yeni gelen numara arasında sadece son ek farkı var. İşaretlediğiniz çiftler onayda takma ad olur ve takip bilgisi yeni numaraya taşınır; işaretlenmeyenler ayrı parça kalır.
        {!p.editable && p.status !== "pending" && " (Bu sürüm artık bekleyen sürüm değil.)"}
      </div>
      <table className="simple">
        <thead>
          <tr>
            <th style={{ width: 32 }}>
              {p.editable && <input type="checkbox" aria-label="Tümünü seç" checked={all}
                onChange={() => p.setAccepted(all ? new Set() : new Set(p.items.map(pairKey)))} />}
            </th>
            <th>Kaldırılan numara</th><th>Yeni numara</th><th>Ortak kök</th>
          </tr>
        </thead>
        <tbody>
          {p.items.map((a) => {
            const k = pairKey(a);
            return (
              <tr key={k} onClick={() => p.editable && toggle(k)} style={{ cursor: p.editable ? "pointer" : undefined }}>
                <td><input type="checkbox" aria-label="Aynı parça" checked={p.accepted.has(k)} disabled={!p.editable}
                  onClick={(e) => e.stopPropagation()} onChange={() => toggle(k)} /></td>
                <td>{a.removed}</td><td>{a.added}</td><td className="muted">{a.base}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------- compare ----------
const LIST_CAP = 300;

function CappedList<T>({ items, render }: { items: T[]; render: (it: T, i: number) => ReactNode }) {
  const [all, setAll] = useState(false);
  const vis = all ? items : items.slice(0, LIST_CAP);
  return (
    <>
      {vis.map(render)}
      {!all && items.length > LIST_CAP && (
        <button className="btn small" style={{ marginTop: 6 }} onClick={() => setAll(true)}>
          Tümünü göster ({nf(items.length - LIST_CAP)} daha)
        </button>
      )}
    </>
  );
}

function CompareView({ cj, warnings }: { cj: CompareJson; warnings: BomWarning[] }) {
  const [term, setTerm] = useState("");
  const t = lc(term.trim());
  const flagged = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const w of warnings) {
      if (!w.part_no) continue;
      if (!m.has(w.kind)) m.set(w.kind, new Set());
      m.get(w.kind)!.add(w.part_no);
    }
    return m;
  }, [warnings]);

  const f = useMemo(() => {
    const ms = (s: string) => !t || lc(s).includes(t);
    const fc = (l?: FieldChange[]) => (l ?? []).filter((c) => ms(c.part_no));
    return {
      added: (cj.added ?? []).filter(ms),
      removed: (cj.removed ?? []).filter(ms),
      rev: fc(cj.rev_changed), qty: fc(cj.qty_changed), mat: fc(cj.material_changed), proc: fc(cj.procurement_changed),
      fast: (cj.fastener_changes ?? []).filter((c) => ms(`${c.key} ${c.desc} ${c.std} ${c.size}`)),
    };
  }, [cj, t]);

  if (cj.first) return <div className="muted">İlk sürüm: karşılaştırılacak önceki onaylı sürüm yok.</div>;
  if (cj.is_empty) return <div className="muted">Önceki sürümle parça numarası, revizyon, adet, malzeme, temin ve bağlantı elemanı farkı yok.</div>;

  const removedProg = flagged.get("removed_with_progress");
  const revDone = flagged.get("rev_after_done");
  const fOld = cj.fastener_total_old ?? 0, fNew = cj.fastener_total_new ?? 0;
  const changeTable = (rows: FieldChange[], hl?: Set<string>) => (
    <table className="simple">
      <thead><tr><th>Parça No</th><th>Eski</th><th>Yeni</th></tr></thead>
      <tbody>
        <CappedList items={rows} render={(c, i) => (
          <tr key={i} className={hl?.has(c.part_no) ? "bomv-hl" : ""}>
            <td>{c.part_no}</td><td>{shown(c.old)}</td><td>{shown(c.new)}</td>
          </tr>
        )} />
      </tbody>
    </table>
  );

  return (
    <div>
      <div className="row" style={{ alignItems: "center", marginBottom: 8 }}>
        <input placeholder="Parça no / bağlantı elemanı ara…" value={term} onChange={(e) => setTerm(e.target.value)} style={{ minWidth: 260 }} />
        <span className="muted" style={{ fontSize: 12 }}>
          Ağırlık farkları dikkate alınmaz. Bağlantı elemanı toplamı: {nf(fOld)} → {nf(fNew)}
          {cj.fastener_big_drop && <span className="badge warn" style={{ marginLeft: 6 }}>Büyük düşüş</span>}
        </span>
      </div>
      <Collapsible title="Yeni eklenen parçalar" count={f.added.length} defaultOpen={!!t}>
        <ul className="bomv-list cols"><CappedList items={f.added} render={(p) => <li key={p} className="bomv-add">{p}</li>} /></ul>
      </Collapsible>
      <Collapsible title="Kaldırılan parçalar" count={f.removed.length} tone={removedProg?.size ? "err" : undefined} defaultOpen={!!t || !!removedProg?.size}>
        <ul className="bomv-list cols">
          <CappedList items={f.removed} render={(p) => (
            <li key={p} className={removedProg?.has(p) ? "bomv-hl" : "bomv-rem"} title={removedProg?.has(p) ? "İlerleme kaydı olan parça BOM'dan kalktı" : undefined}>
              {p}{removedProg?.has(p) && " ⚠"}
            </li>
          )} />
        </ul>
      </Collapsible>
      <Collapsible title="Revizyonu değişen parçalar" count={f.rev.length} tone={revDone?.size ? "warn" : undefined} defaultOpen={!!t}>
        {changeTable(f.rev, revDone)}
      </Collapsible>
      <Collapsible title="Adet değişiklikleri (toplam adet)" count={f.qty.length} defaultOpen={!!t}>{changeTable(f.qty)}</Collapsible>
      <Collapsible title="Malzeme değişiklikleri" count={f.mat.length} defaultOpen={!!t}>{changeTable(f.mat)}</Collapsible>
      <Collapsible title="Temin şekli değişiklikleri" count={f.proc.length} defaultOpen={!!t}>{changeTable(f.proc)}</Collapsible>
      <Collapsible title="Bağlantı elemanı kalem/adet değişiklikleri" count={f.fast.length} tone={cj.fastener_big_drop ? "warn" : undefined} defaultOpen={!!t}>
        <table className="simple">
          <thead><tr><th>Kalem</th><th>Standart</th><th>Ölçü</th><th>Eski adet</th><th>Yeni adet</th><th>Fark</th></tr></thead>
          <tbody>
            <CappedList items={f.fast} render={(c) => (
              <tr key={c.key}>
                <td>{c.desc || c.key}</td><td>{c.std}</td><td>{c.size}</td>
                <td>{nf(c.old)}</td><td>{nf(c.new)}</td>
                <td className={c.delta < 0 ? "bomv-neg" : "bomv-pos"}>{c.delta > 0 ? "+" : ""}{nf(c.delta)}</td>
              </tr>
            )} />
          </tbody>
        </table>
      </Collapsible>
    </div>
  );
}

// ---------- raw tree rows ----------
function TreeRows({ pid, vid }: { pid: number; vid: number }) {
  const q = useQuery({
    queryKey: ["bom-rows", pid, vid],
    queryFn: () => api.get<RowsResp>(`/projects/${pid}/bom/versions/${vid}/rows`),
    staleTime: 60_000,
  });
  const columns = useMemo<GridColumn<TreeRow>[]>(() => [
    {
      accessorKey: "level", header: "Seviye", size: 170,
      cell: ({ row }) => <span style={{ paddingLeft: Math.max(0, row.original.depth) * 14 }}>{row.original.level || "0"}</span>,
    },
    { accessorKey: "part_no", header: "Parça No", size: 200 },
    { accessorKey: "row_type", header: "Tip", size: 150 },
    { accessorKey: "qty", header: "Adet", size: 70, cell: ({ getValue }) => nf(getValue() as number) },
    { accessorKey: "total_qty", header: "Toplam Adet", size: 95, cell: ({ getValue }) => nf(getValue() as number) },
    { accessorKey: "material", header: "Malzeme", size: 140 },
    { accessorKey: "rev", header: "Rev", size: 60 },
    { accessorKey: "procurement", header: "Temin Şekli", size: 120 },
    { accessorKey: "coating", header: "Kaplama", size: 110 },
    { accessorKey: "main_group", header: "Ana Grup", size: 150 },
    { accessorKey: "parent_part_no", header: "Üst Montaj", size: 160 },
    { accessorKey: "status", header: "Durum", size: 150, cellStyle: (r) => statusStyle(r.status_color) },
    { accessorKey: "file_name", header: "Dosya Adı", size: 220 },
  ], []);

  if (q.isLoading) return <div className="muted">Satırlar yükleniyor…</div>;
  if (q.error) return <div className="badge err">{errText(q.error)}</div>;
  return (
    <div className="bomv-grid">
      <DataGrid exportName="BOM satırları" data={q.data?.rows ?? []} columns={columns} getRowId={(r) => String(r.id)}
        toolbar={<span className="muted">BOM sırasıyla tüm satırlar (girinti = seviye derinliği)</span>}
        emptyText="Satır yok" />
    </div>
  );
}

// ---------- aliases ----------
function AliasCard({ pid, canDesign }: { pid: number; canDesign: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [all, setAll] = useState(false);
  const [term, setTerm] = useState("");
  const [oldNo, setOldNo] = useState("");
  const [newNo, setNewNo] = useState("");
  const [moveState, setMoveState] = useState(true);
  const [del, setDel] = useState<Alias | null>(null);

  const q = useQuery({
    queryKey: ["aliases", pid, all],
    queryFn: () => api.get<Alias[]>(`/projects/${pid}/aliases${all ? "?all=true" : ""}`),
    enabled: !!pid,
  });
  const done = () => {
    qc.invalidateQueries({ queryKey: ["aliases", pid] });
    // Moving state touches tracking: refresh other project views too
    qc.invalidateQueries({ predicate: (x) => x.queryKey.includes(pid) && x.queryKey[0] !== "aliases" });
  };
  const add = useMutation({
    mutationFn: () => api.post<Alias>(`/projects/${pid}/aliases`, { alias: oldNo.trim(), part_no: newNo.trim(), move_state: moveState }),
    onSuccess: (a) => {
      toast(`Eşleştirme eklendi: ${a.alias} → ${a.part_no}${a.state_moved ? " (takip bilgisi taşındı)" : ""}`);
      setOldNo(""); setNewNo("");
      done();
    },
    onError: (e) => toast(errText(e), true),
  });
  const remove = useMutation({
    mutationFn: (a: Alias) => api.del(`/projects/${pid}/aliases/${a.id}`),
    onSuccess: () => { toast("Eşleştirme silindi."); setDel(null); done(); },
    onError: (e) => toast(errText(e), true),
  });

  const list = useMemo(() => {
    const t = lc(term.trim());
    return (q.data ?? []).filter((a) => !t || lc(a.alias).includes(t) || lc(a.part_no).includes(t));
  }, [q.data, term]);

  return (
    <div className="card">
      <div className="row" style={{ alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Parça numarası eşleştirmeleri (takma adlar)</h3>
        <span style={{ flex: 1 }} />
        <input placeholder="Ara…" value={term} onChange={(e) => setTerm(e.target.value)} />
        <label className="row" style={{ gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Tüm projeler
        </label>
      </div>
      {canDesign && (
        <form className="row" style={{ alignItems: "center", marginBottom: 10 }}
          onSubmit={(e) => { e.preventDefault(); if (oldNo.trim() && newNo.trim()) add.mutate(); }}>
          <input placeholder="Eski / farklı numara" value={oldNo} onChange={(e) => setOldNo(e.target.value)} maxLength={200} />
          <span>→</span>
          <input placeholder="Geçerli parça numarası" value={newNo} onChange={(e) => setNewNo(e.target.value)} maxLength={200} />
          <label className="row" style={{ gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={moveState} onChange={(e) => setMoveState(e.target.checked)} /> Takip bilgisini yeni numaraya taşı
          </label>
          <button className="btn primary" type="submit" disabled={!oldNo.trim() || !newNo.trim() || add.isPending}>
            {add.isPending ? "Ekleniyor…" : "Eşleştirme ekle"}
          </button>
        </form>
      )}
      {q.isLoading && <div className="muted">Yükleniyor…</div>}
      {q.error && <div className="badge err">{errText(q.error)}</div>}
      {q.data && list.length === 0 && <div className="muted">{q.data.length ? "Aramaya uyan eşleştirme yok." : "Eşleştirme yok."}</div>}
      {list.length > 0 && (
        <div style={{ maxHeight: 360, overflow: "auto" }}>
          <table className="simple">
            <thead><tr><th>Eski numara</th><th>Geçerli numara</th><th>Oluşturan</th><th>Tarih</th>{canDesign && <th />}</tr></thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td>{a.alias}</td><td><b>{a.part_no}</b></td><td>{a.created_by || "—"}</td><td>{fmtDate(a.created_at)}</td>
                  {canDesign && <td style={{ textAlign: "right" }}><button className="btn small danger" onClick={() => setDel(a)}>Sil</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {del && (
        <Confirm title="Eşleştirme silinsin mi?" okText="Sil" danger busy={remove.isPending}
          onOk={() => remove.mutate(del)} onClose={() => setDel(null)}>
          <p><b>{del.alias}</b> → <b>{del.part_no}</b> eşleştirmesi silinir.</p>
          <p className="muted">Sadece eşleştirme kaldırılır; geçerli numaraya taşınmış takip bilgisi orada kalır.</p>
        </Confirm>
      )}
    </div>
  );
}
