import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, download, upload } from "../api/client";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { LOCALE, tx } from "../api/i18n";

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
  pending: { label: tx("Onay bekliyor"), cls: "badge warn" },
  approved: { label: tx("Onaylandı"), cls: "badge bomv-ok" },
  rejected: { label: tx("Reddedildi"), cls: "badge err" },
  undone: { label: tx("Geri alındı"), cls: "badge" },
  superseded: { label: tx("Eski sürüm"), cls: "badge" },
};
const WARN_KIND: Record<string, string> = {
  removed_with_progress: tx("Üretildi/ilerleme kaydı olan parça BOM'dan kalktı"),
  rev_after_done: tx("Tamamlanmış parçada revizyon değişti (eski revizyonla üretilmiş olabilir)"),
  fastener_big_drop: tx("Bağlantı elemanı toplam adedinde büyük düşüş"),
  root_mismatch: tx("Dosyanın ana montajı proje ile uyuşmuyor"),
};
const nf = (v: number | null | undefined) => Number(v ?? 0).toLocaleString(LOCALE);
const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString(LOCALE) : "—");
const shown = (v: unknown) => (v === null || v === undefined || v === "" ? tx("(boş)") : String(v));
const lc = (s: string) => s.toLocaleLowerCase(LOCALE);
const pairKey = (a: AliasSuggestion) => `${a.removed}\u0000${a.added}`;

function StatusBadge({ v }: { v: Pick<BomVersion, "status" | "is_current"> }) {
  const s = STATUS[v.status] ?? { label: v.status, cls: "badge" };
  return (
    <span className="row" style={{ gap: 4, display: "inline-flex" }}>
      <span className={s.cls}>{s.label}</span>
      {v.is_current && <span className="badge new">{tx("Güncel")}</span>}
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
          <button className="btn" onClick={p.onClose} disabled={p.busy}>{tx("Vazgeç")}</button>
          <button className={p.danger ? "btn danger" : "btn primary"} onClick={p.onOk} disabled={p.busy}>
            {p.busy ? tx("İşleniyor…") : p.okText}
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
    if (!list) return;
    if (selected !== null && list.some((v) => v.id === selected)) return;
    const pick = list.find((v) => v.status === "pending") ?? list.find((v) => v.is_current) ?? list[0];
    setSelected(pick?.id ?? null);
  }, [versions.data, selected]);

  // Approval / undo change tracking, parts, dashboard etc.: refresh everything
  const refreshAll = () => qc.invalidateQueries();

  return (
    <Page>
      <div className="row" style={{ alignItems: "baseline", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{tx("BOM Sürümleri")}</h2>
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
        <h3 style={{ marginTop: 0 }}>{tx("Sürüm geçmişi")}</h3>
        {versions.isLoading && <div className="muted">{tx("Yükleniyor…")}</div>}
        {versions.error && <div className="badge err">{errText(versions.error)}</div>}
        {versions.data && versions.data.length === 0 && <div className="muted">{tx("Henüz BOM yüklenmedi.")}</div>}
        {versions.data && versions.data.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table className="simple bomv-table">
              <thead>
                <tr>
                  <th>{tx("Sürüm")}</th><th>{tx("Dosya")}</th><th>{tx("Durum")}</th><th>{tx("Yükleyen")}</th><th>{tx("Yükleme")}</th>
                  <th>{tx("Onaylayan")}</th><th>{tx("Onay")}</th><th>{tx("Değişiklik")}</th><th>{tx("Not")}</th>
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
                      {v.summary.first ? <span className="muted">{tx("İlk sürüm")}</span> : (
                        <span className="bomv-chips">
                          <span title={tx("Eklenen")}>+{nf(v.summary.added)}</span>
                          <span title={tx("Kaldırılan")}>−{nf(v.summary.removed)}</span>
                          <span title={tx("Revizyon değişen")}>{tx("Rev {0}", nf(v.summary.rev_changed))}</span>
                          <span title={tx("Adet değişen")}>{tx("Adet {0}", nf(v.summary.qty_changed))}</span>
                          {v.summary.warnings > 0 && <span className="badge warn">{tx("{0} uyarı", nf(v.summary.warnings))}</span>}
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
        onUndone={(cur) => setSelected(cur)} onDeleted={(id) => {
          qc.setQueryData<BomVersion[]>(["bom-versions", pid], (l) => l?.filter((x) => x.id !== id));
          setSelected(null);
        }} toast={toast} />}

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
      toast(tx("Sürüm #{0} yüklendi; karşılaştırmayı inceleyip onaylayın.", v.seq));
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
      <h3 style={{ marginTop: 0 }}>{tx("Yeni BOM yükle")}</h3>
      <div className="row" style={{ alignItems: "center" }}>
        <input ref={fileRef} type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={m.isPending} />
        <input placeholder={tx("Not (isteğe bağlı)")} value={note} onChange={(e) => setNote(e.target.value)} style={{ minWidth: 240 }} disabled={m.isPending} />
        <button className="btn primary" disabled={!file || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? tx("Yükleniyor…") : tx("Yükle")}
        </button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        {tx("SolidWorks BOM dışa aktarımı (.csv, ayraç “;”). Yüklenen sürüm onaylanana kadar takip listesini değiştirmez. Dosyanız yoksa")}{" "}<Link to={`/p/${pid}/tree`}>{tx("ürün ağacını elle oluşturun")}</Link>.
      </div>
      {pct !== null && (
        <div style={{ marginTop: 8 }}>
          <div className="progress"><div style={{ width: `${pct}%` }} /></div>
          <div className="muted" style={{ fontSize: 12 }}>{pct < 100 ? tx("%{0} gönderildi", pct) : tx("Sunucuda işleniyor ve karşılaştırılıyor…")}</div>
        </div>
      )}
    </div>
  );
}

// ---------- version detail ----------
type DetailProps = {
  pid: number; vid: number; canDesign: boolean; refreshAll: () => Promise<unknown>;
  onUndone: (currentId: number) => void; onDeleted: (id: number) => void; toast: (t: string, err?: boolean) => void;
};

function VersionDetail({ pid, vid, canDesign, refreshAll, onUndone, onDeleted, toast }: DetailProps) {
  const [tab, setTab] = useState<"compare" | "rows">("compare");
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [modal, setModal] = useState<"approve" | "reject" | "undo" | "delete" | null>(null);

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
    onSuccess: (r) => { toast(tx("Sürüm #{0} onaylandı; güncel sürüm oldu.", r.seq)); setModal(null); refreshAll(); },
    onError: (e) => toast(errText(e), true),
  });
  const reject = useMutation({
    mutationFn: () => api.post<BomVersion>(`/projects/${pid}/bom/versions/${vid}/reject`),
    onSuccess: (r) => { toast(tx("Sürüm #{0} reddedildi.", r.seq)); setModal(null); refreshAll(); },
    onError: (e) => toast(errText(e), true),
  });
  const undo = useMutation({
    mutationFn: () => api.post<{ undone: BomVersion; current: BomVersion | null }>(`/projects/${pid}/bom/undo`),
    onSuccess: (r) => {
      toast(tx("Sürüm #{0} onayı geri alındı.{1}", r.undone.seq, r.current ? tx(" Güncel sürüm: #{0}", r.current.seq) : ""));
      setModal(null);
      if (r.current) onUndone(r.current.id);
      refreshAll();
    },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/projects/${pid}/bom/versions/${vid}`),
    onSuccess: () => { toast(tx("Sürüm #{0} silindi.", v?.seq)); setModal(null); onDeleted(vid); refreshAll(); },
    onError: (e) => toast(errText(e), true),
  });
  const dl = useMutation({
    mutationFn: () => download(`/projects/${pid}/bom/versions/${vid}/file`, v?.filename || "bom.csv"),
    onError: (e) => toast(errText(e), true),
  });

  if (q.isLoading) return <div className="card" style={{ marginBottom: 12 }}><span className="muted">{tx("Sürüm yükleniyor…")}</span></div>;
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
        <h3 style={{ margin: 0 }}>{tx("Sürüm #{0} · {1}", v.seq, v.filename)}</h3>
        <StatusBadge v={v} />
        <span style={{ flex: 1 }} />
        <button className="btn small" onClick={() => dl.mutate()} disabled={dl.isPending}>{tx("Orijinal dosyayı indir")}</button>
        {canDesign && pending && (
          <>
            <button className="btn small primary" onClick={() => setModal("approve")}>{tx("Onayla")}</button>
            <button className="btn small danger" onClick={() => setModal("reject")}>{tx("Reddet")}</button>
          </>
        )}
        {canDesign && v.can_undo && <button className="btn small danger" onClick={() => setModal("undo")}>{tx("Son onayı geri al")}</button>}
        {canDesign && (v.status === "rejected" || v.status === "undone") && (
          <button className="btn small danger" onClick={() => setModal("delete")}>{tx("Sürümü sil")}</button>
        )}
      </div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
        {tx("Yükleyen:")}{" "}{v.uploaded_by || "—"} · {fmtDate(v.uploaded_at)}
        {v.approved_by && <>{" "}{tx("· Onaylayan: {0} · {1}", v.approved_by, fmtDate(v.approved_at))}</>}
        {s.root_part_no && <>{" "}{tx("· Ana montaj: {0}", s.root_part_no)}</>}
        {v.note && <>{" "}{tx("· Not: {0}", v.note)}</>}
      </div>

      <div className="grid kpis" style={{ marginBottom: 12 }}>
        <Kpi label={tx("BOM satırı")} value={s.rows} />
        <Kpi label={tx("Parça (benzersiz)")} value={s.parts} />
        <Kpi label={tx("Montaj")} value={s.assemblies} />
        <Kpi label={tx("Bağlantı elemanı satırı")} value={s.fastener_rows} />
        <Kpi label={tx("Bağlantı elemanı kalemi")} value={s.fastener_unique} />
        <Kpi label={tx("Bağlantı elemanı toplam adet")} value={s.fastener_total} />
        <Kpi label={tx("Satın alınan montaj içi satır")} value={s.in_purchased_rows} />
        <Kpi label={tx("Standart dışı isim")} value={s.nonstandard} />
      </div>
      {!!s.parse_warnings?.length && (
        <Collapsible title={tx("Dosya okuma uyarıları")} count={s.parse_warnings.length}>
          <ul className="bomv-list">{s.parse_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </Collapsible>
      )}

      <div className="tabs">
        <button className={tab === "compare" ? "active" : ""} onClick={() => setTab("compare")}>{tx("Karşılaştırma")}</button>
        <button className={tab === "rows" ? "active" : ""} onClick={() => setTab("rows")}>{tx("Ağaç satırları")}</button>
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
        <Confirm title={tx("Sürüm #{0} onaylansın mı?", v.seq)} okText={tx("Onayla")} busy={approve.isPending}
          onOk={() => approve.mutate()} onClose={() => setModal(null)}>
          <p>{tx("Onaylandığında bu sürüm projenin")}{" "}<b>{tx("güncel BOM'u")}</b>{" "}{tx("olur:")}</p>
          <ul>
            {cj.first ? <li>{tx("İlk sürüm: tüm parçalar varsayılan durumla takip listesine eklenir.")}</li> : (
              <>
                <li><b>{nf(cj.added?.length)}</b>{" "}{tx("yeni parça varsayılan durumla eklenir ve “Yeni” etiketi alır.")}</li>
                <li><b>{nf(cj.removed?.length)}</b>{" "}{tx("parça listeden çıkar (veritabanında arşivlenir, geçmiş sürümde görülebilir).")}</li>
                <li>{tx("Revizyon: {0}, adet: {1}, malzeme: {2}, temin: {3} değişiklik bilgi olarak işlenir.", nf(cj.rev_changed?.length), nf(cj.qty_changed?.length), nf(cj.material_changed?.length), nf(cj.procurement_changed?.length))}</li>
                <li>{tx("Bağlantı elemanı toplam adedi {0} → {1}.", nf(cj.fastener_total_old), nf(cj.fastener_total_new))}</li>
              </>
            )}
            <li>{tx("Mevcut parçaların takip bilgileri (ilerleme, temin değişikliği, notlar, eksik satırları) korunur.")}</li>
            {acceptedCount > 0 && <li><b>{nf(acceptedCount)}</b>{" "}{tx("eşleştirme önerisi kabul edildi: eski numaraların durumu yeni numaraya taşınır ve takma ad oluşturulur.")}</li>}
          </ul>
          {warnings.length > 0 && (
            <div className={errors.length ? "bomv-warn err" : "bomv-warn"}>
              <b>{tx("{0} uyarı var", nf(warnings.length))}{errors.length ? tx(" ({0} kritik)", nf(errors.length)) : ""}.</b>{" "}{tx("Onaylamadan önce karşılaştırmayı inceleyin.")}
            </div>
          )}
          <p className="muted" style={{ fontSize: 12 }}>{tx("Gerekirse “Son onayı geri al” ile bu işlem geri alınabilir.")}</p>
        </Confirm>
      )}
      {modal === "reject" && (
        <Confirm title={tx("Sürüm #{0} reddedilsin mi?", v.seq)} okText={tx("Reddet")} danger busy={reject.isPending}
          onOk={() => reject.mutate()} onClose={() => setModal(null)}>
          <p>{tx("Sürüm “Reddedildi” olarak işaretlenir ve geçmişte kalır; isterseniz sonra silebilirsiniz. Takip listesi ve güncel sürüm")}{" "}<b>{tx("değişmez")}</b>.</p>
        </Confirm>
      )}
      {modal === "delete" && (
        <Confirm title={tx("Sürüm #{0} silinsin mi?", v.seq)} okText={tx("Kalıcı olarak sil")} danger busy={del.isPending}
          onOk={() => del.mutate()} onClose={() => setModal(null)}>
          <p>{tx("“{0}” dosyası ve sürümün satırları", v.filename)}{" "}<b>{tx("kalıcı olarak")}</b>{" "}{tx("silinir, geri alınamaz. Takip listesi ve güncel sürüm değişmez.")}</p>
        </Confirm>
      )}
      {modal === "undo" && (
        <Confirm title={tx("Son onay geri alınsın mı?")} okText={tx("Geri al")} danger busy={undo.isPending}
          onOk={() => undo.mutate()} onClose={() => setModal(null)}>
          <p>{tx("Sürüm #{0} onayı geri alınır; önceki onaylı sürüm yeniden güncel olur.", v.seq)}</p>
          <ul>
            <li>{tx("Onayla eklenen parçalar ve kabul edilen eşleştirmeler kaldırılır, kaldırılan parçalar geri gelir.")}</li>
            <li><b>{tx("Bu onaydan sonra yapılan takip değişiklikleri (ilerleme, notlar vb.) kaybolur.")}</b></li>
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
      <b>{tx("Olası eşleştirmeler: aynı parça mı?")}</b>
      <div className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>
        {tx("Kaldırılan ve yeni gelen numara arasında sadece son ek farkı var. İşaretlediğiniz çiftler onayda takma ad olur ve takip bilgisi yeni numaraya taşınır; işaretlenmeyenler ayrı parça kalır.")}
        {!p.editable && p.status !== "pending" && tx(" (Bu sürüm artık bekleyen sürüm değil.)")}
      </div>
      <table className="simple">
        <thead>
          <tr>
            <th style={{ width: 32 }}>
              {p.editable && <input type="checkbox" aria-label={tx("Tümünü seç")} checked={all}
                onChange={() => p.setAccepted(all ? new Set() : new Set(p.items.map(pairKey)))} />}
            </th>
            <th>{tx("Kaldırılan numara")}</th><th>{tx("Yeni numara")}</th><th>{tx("Ortak kök")}</th>
          </tr>
        </thead>
        <tbody>
          {p.items.map((a) => {
            const k = pairKey(a);
            return (
              <tr key={k} onClick={() => p.editable && toggle(k)} style={{ cursor: p.editable ? "pointer" : undefined }}>
                <td><input type="checkbox" aria-label={tx("Aynı parça")} checked={p.accepted.has(k)} disabled={!p.editable}
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
          {tx("Tümünü göster ({0} daha)", nf(items.length - LIST_CAP))}
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

  if (cj.first) return <div className="muted">{tx("İlk sürüm: karşılaştırılacak önceki onaylı sürüm yok.")}</div>;
  if (cj.is_empty) return <div className="muted">{tx("Önceki sürümle parça numarası, revizyon, adet, malzeme, temin ve bağlantı elemanı farkı yok.")}</div>;

  const removedProg = flagged.get("removed_with_progress");
  const revDone = flagged.get("rev_after_done");
  const fOld = cj.fastener_total_old ?? 0, fNew = cj.fastener_total_new ?? 0;
  const changeTable = (rows: FieldChange[], hl?: Set<string>) => (
    <table className="simple">
      <thead><tr><th>{tx("Parça No")}</th><th>{tx("Eski")}</th><th>{tx("Yeni")}</th></tr></thead>
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
        <input placeholder={tx("Parça no / bağlantı elemanı ara…")} value={term} onChange={(e) => setTerm(e.target.value)} style={{ minWidth: 260 }} />
        <span className="muted" style={{ fontSize: 12 }}>
          {tx("Ağırlık farkları dikkate alınmaz. Bağlantı elemanı toplamı: {0} → {1}", nf(fOld), nf(fNew))}
          {cj.fastener_big_drop && <span className="badge warn" style={{ marginLeft: 6 }}>{tx("Büyük düşüş")}</span>}
        </span>
      </div>
      <Collapsible title={tx("Yeni eklenen parçalar")} count={f.added.length} defaultOpen={!!t}>
        <ul className="bomv-list cols"><CappedList items={f.added} render={(p) => <li key={p} className="bomv-add">{p}</li>} /></ul>
      </Collapsible>
      <Collapsible title={tx("Kaldırılan parçalar")} count={f.removed.length} tone={removedProg?.size ? "err" : undefined} defaultOpen={!!t || !!removedProg?.size}>
        <ul className="bomv-list cols">
          <CappedList items={f.removed} render={(p) => (
            <li key={p} className={removedProg?.has(p) ? "bomv-hl" : "bomv-rem"} title={removedProg?.has(p) ? tx("İlerleme kaydı olan parça BOM'dan kalktı") : undefined}>
              {p}{removedProg?.has(p) && " ⚠"}
            </li>
          )} />
        </ul>
      </Collapsible>
      <Collapsible title={tx("Revizyonu değişen parçalar")} count={f.rev.length} tone={revDone?.size ? "warn" : undefined} defaultOpen={!!t}>
        {changeTable(f.rev, revDone)}
      </Collapsible>
      <Collapsible title={tx("Adet değişiklikleri (toplam adet)")} count={f.qty.length} defaultOpen={!!t}>{changeTable(f.qty)}</Collapsible>
      <Collapsible title={tx("Malzeme değişiklikleri")} count={f.mat.length} defaultOpen={!!t}>{changeTable(f.mat)}</Collapsible>
      <Collapsible title={tx("Temin şekli değişiklikleri")} count={f.proc.length} defaultOpen={!!t}>{changeTable(f.proc)}</Collapsible>
      <Collapsible title={tx("Bağlantı elemanı kalem/adet değişiklikleri")} count={f.fast.length} tone={cj.fastener_big_drop ? "warn" : undefined} defaultOpen={!!t}>
        <table className="simple">
          <thead><tr><th>{tx("Kalem")}</th><th>{tx("Standart")}</th><th>{tx("Ölçü")}</th><th>{tx("Eski adet")}</th><th>{tx("Yeni adet")}</th><th>{tx("Fark")}</th></tr></thead>
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
      accessorKey: "level", header: tx("Seviye"), size: 170,
      cell: ({ row }) => <span style={{ paddingLeft: Math.max(0, row.original.depth) * 14 }}>{row.original.level || "0"}</span>,
    },
    { accessorKey: "part_no", header: tx("Parça No"), size: 200 },
    { accessorKey: "row_type", header: tx("Tip"), size: 150 },
    { accessorKey: "qty", header: tx("Adet"), size: 70, cell: ({ getValue }) => nf(getValue() as number) },
    { accessorKey: "total_qty", header: tx("Toplam Adet"), size: 95, cell: ({ getValue }) => nf(getValue() as number) },
    { accessorKey: "material", header: tx("Malzeme"), size: 140 },
    { accessorKey: "rev", header: tx("Rev"), size: 60 },
    { accessorKey: "procurement", header: tx("Temin Şekli"), size: 120 },
    { accessorKey: "coating", header: tx("Kaplama"), size: 110 },
    { accessorKey: "main_group", header: tx("Ana Grup"), size: 150 },
    { accessorKey: "parent_part_no", header: tx("Üst Montaj"), size: 160 },
    { accessorKey: "status", header: tx("Durum"), size: 150, cellStyle: (r) => statusStyle(r.status_color) },
    { accessorKey: "file_name", header: tx("Dosya Adı"), size: 220 },
  ], []);

  if (q.isLoading) return <div className="muted">{tx("Satırlar yükleniyor…")}</div>;
  if (q.error) return <div className="badge err">{errText(q.error)}</div>;
  return (
    <div className="bomv-grid">
      <DataGrid stateKey="BOM satırları" exportName={tx("BOM satırları")} data={q.data?.rows ?? []} columns={columns} getRowId={(r) => String(r.id)}
        toolbar={<span className="muted">{tx("BOM sırasıyla tüm satırlar (girinti = seviye derinliği)")}</span>}
        emptyText={tx("Satır yok")} />
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
      toast(tx("Eşleştirme eklendi: {0} → {1}{2}", a.alias, a.part_no, a.state_moved ? tx(" (takip bilgisi taşındı)") : ""));
      setOldNo(""); setNewNo("");
      done();
    },
    onError: (e) => toast(errText(e), true),
  });
  const remove = useMutation({
    mutationFn: (a: Alias) => api.del(`/projects/${pid}/aliases/${a.id}`),
    onSuccess: () => { toast(tx("Eşleştirme silindi.")); setDel(null); done(); },
    onError: (e) => toast(errText(e), true),
  });

  const list = useMemo(() => {
    const t = lc(term.trim());
    return (q.data ?? []).filter((a) => !t || lc(a.alias).includes(t) || lc(a.part_no).includes(t));
  }, [q.data, term]);

  return (
    <div className="card">
      <div className="row" style={{ alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>{tx("Parça numarası eşleştirmeleri (takma adlar)")}</h3>
        <span style={{ flex: 1 }} />
        <input placeholder={tx("Ara…")} value={term} onChange={(e) => setTerm(e.target.value)} />
        <label className="row" style={{ gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{" "}{tx("Tüm projeler")}
        </label>
      </div>
      {canDesign && (
        <form className="row" style={{ alignItems: "center", marginBottom: 10 }}
          onSubmit={(e) => { e.preventDefault(); if (oldNo.trim() && newNo.trim()) add.mutate(); }}>
          <input placeholder={tx("Eski / farklı numara")} value={oldNo} onChange={(e) => setOldNo(e.target.value)} maxLength={200} />
          <span>→</span>
          <input placeholder={tx("Geçerli parça numarası")} value={newNo} onChange={(e) => setNewNo(e.target.value)} maxLength={200} />
          <label className="row" style={{ gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={moveState} onChange={(e) => setMoveState(e.target.checked)} />{" "}{tx("Takip bilgisini yeni numaraya taşı")}
          </label>
          <button className="btn primary" type="submit" disabled={!oldNo.trim() || !newNo.trim() || add.isPending}>
            {add.isPending ? tx("Ekleniyor…") : tx("Eşleştirme ekle")}
          </button>
        </form>
      )}
      {q.isLoading && <div className="muted">{tx("Yükleniyor…")}</div>}
      {q.error && <div className="badge err">{errText(q.error)}</div>}
      {q.data && list.length === 0 && <div className="muted">{q.data.length ? tx("Aramaya uyan eşleştirme yok.") : tx("Eşleştirme yok.")}</div>}
      {list.length > 0 && (
        <div style={{ maxHeight: 360, overflow: "auto" }}>
          <table className="simple">
            <thead><tr><th>{tx("Eski numara")}</th><th>{tx("Geçerli numara")}</th><th>{tx("Oluşturan")}</th><th>{tx("Tarih")}</th>{canDesign && <th />}</tr></thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td>{a.alias}</td><td><b>{a.part_no}</b></td><td>{a.created_by || "—"}</td><td>{fmtDate(a.created_at)}</td>
                  {canDesign && <td style={{ textAlign: "right" }}><button className="btn small danger" onClick={() => setDel(a)}>{tx("Sil")}</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {del && (
        <Confirm title={tx("Eşleştirme silinsin mi?")} okText={tx("Sil")} danger busy={remove.isPending}
          onOk={() => remove.mutate(del)} onClose={() => setDel(null)}>
          <p><b>{del.alias}</b> → <b>{del.part_no}</b>{" "}{tx("eşleştirmesi silinir.")}</p>
          <p className="muted">{tx("Sadece eşleştirme kaldırılır; geçerli numaraya taşınmış takip bilgisi orada kalır.")}</p>
        </Confirm>
      )}
    </div>
  );
}
