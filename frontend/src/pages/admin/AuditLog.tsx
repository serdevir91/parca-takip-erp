import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Loading, Modal, fmtDate, fmtNum } from "./shared";

type AuditItem = {
  id: number; ts: string | null; user_id: number | null; username: string; project_id: number | null;
  entity: string; entity_id: string; field: string; old: string | null; new: string | null; action: string;
};
type AuditPage = { total: number; page: number; page_size: number; items: AuditItem[] };
type Facets = { users: string[]; actions: string[]; entities: string[] };
type Project = { id: number; name: string };

const PAGE_SIZE = 100;
const ACTION_TR: Record<string, string> = {
  create: "Oluşturma", update: "Güncelleme", delete: "Silme", upload: "Yükleme", import: "İçe aktarma",
  login: "Giriş", restore: "Geri yükleme", backup: "Yedekleme", password: "Şifre değişikliği",
};
const ENTITY_TR: Record<string, string> = {
  project: "Proje", part: "Parça", bom: "BOM", setting: "Ayar", user: "Kullanıcı", firm: "Firma",
  fastener_rule: "Bağlantı elemanı kuralı", tracking: "Takip", drawing: "Teknik resim", t35: "T-35",
};
const actionLabel = (a: string) => ACTION_TR[a] ?? a;
const entityLabel = (e: string) => ENTITY_TR[e] ?? e;
const SHORT = 80;
const cut = (s: string | null) => (s == null ? "" : s.length > SHORT ? `${s.slice(0, SHORT)}…` : s);

type Filters = { user: string; project_id: string; action: string; entity: string; date_from: string; date_to: string; q: string };
const EMPTY: Filters = { user: "", project_id: "", action: "", entity: "", date_from: "", date_to: "", q: "" };

export default function AuditLogTab() {
  const [f, setF] = useState<Filters>(EMPTY);
  const [qText, setQText] = useState("");
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<AuditItem | null>(null);

  // Debounce free-text search so typing does not fire a request per key.
  useEffect(() => {
    const t = setTimeout(() => setF((x) => (x.q === qText.trim() ? x : { ...x, q: qText.trim() })), 350);
    return () => clearTimeout(t);
  }, [qText]);
  useEffect(() => setPage(1), [f]);

  const facets = useQuery({ queryKey: ["admin", "audit-facets"], queryFn: () => api.get<Facets>("/admin/audit/facets") });
  const projects = useQuery({ queryKey: ["projects", true], queryFn: () => api.get<Project[]>("/projects?include_archived=true") });
  const projName = useMemo(() => new Map((projects.data ?? []).map((p) => [p.id, p.name])), [projects.data]);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
    p.set("page", String(page));
    p.set("page_size", String(PAGE_SIZE));
    return p.toString();
  }, [f, page]);
  const audit = useQuery({
    queryKey: ["admin", "audit", params],
    queryFn: () => api.get<AuditPage>(`/admin/audit?${params}`),
    placeholderData: keepPreviousData,
  });

  const total = audit.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const set = (k: keyof Filters, v: string) => setF((x) => ({ ...x, [k]: v }));
  const anyFilter = Object.values(f).some(Boolean) || !!qText;

  return (
    <div className="card">
      <div className="row adm-filters">
        <select value={f.user} onChange={(e) => set("user", e.target.value)}>
          <option value="">Tüm kullanıcılar</option>
          {facets.data?.users.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
        <select value={f.project_id} onChange={(e) => set("project_id", e.target.value)}>
          <option value="">Tüm projeler</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={f.action} onChange={(e) => set("action", e.target.value)}>
          <option value="">Tüm işlemler</option>
          {facets.data?.actions.map((a) => <option key={a} value={a}>{actionLabel(a)}</option>)}
        </select>
        <select value={f.entity} onChange={(e) => set("entity", e.target.value)}>
          <option value="">Tüm kayıt türleri</option>
          {facets.data?.entities.map((a) => <option key={a} value={a}>{entityLabel(a)}</option>)}
        </select>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">Başlangıç</span>
          <input type="date" value={f.date_from} onChange={(e) => set("date_from", e.target.value)} />
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">Bitiş</span>
          <input type="date" value={f.date_to} onChange={(e) => set("date_to", e.target.value)} />
        </label>
        <input placeholder="Kayıt, alan veya değerde ara…" value={qText} onChange={(e) => setQText(e.target.value)} />
        {anyFilter && <button className="btn small" onClick={() => { setF(EMPTY); setQText(""); }}>Filtreleri temizle</button>}
      </div>
      {facets.error && <Loading error={facets.error} loading={false} />}
      <Loading error={audit.error} loading={audit.isLoading} />
      {audit.data && (
        <>
          <div className="row" style={{ justifyContent: "space-between", margin: "8px 0" }}>
            <span className="muted">
              {fmtNum(total)} kayıt{total > 0 && ` · ${fmtNum((page - 1) * PAGE_SIZE + 1)}–${fmtNum(Math.min(page * PAGE_SIZE, total))} arası`}
              {audit.isFetching && " · yükleniyor…"}
            </span>
            <Pager page={page} pages={pages} onPage={setPage} />
          </div>
          <div className="adm-scroll">
            <table className="simple adm-audit">
              <thead>
                <tr><th>Zaman</th><th>Kullanıcı</th><th>Proje</th><th>İşlem</th><th>Kayıt</th><th>Alan</th><th>Eski → Yeni</th></tr>
              </thead>
              <tbody>
                {audit.data.items.map((a) => (
                  <tr key={a.id} onClick={() => setDetail(a)} style={{ cursor: "pointer" }} title="Ayrıntı için tıklayın">
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(a.ts)}</td>
                    <td>{a.username}</td>
                    <td>{a.project_id != null ? projName.get(a.project_id) ?? `#${a.project_id}` : ""}</td>
                    <td><span className={`badge${a.action === "delete" ? " err" : a.action === "create" ? " new" : ""}`}>{actionLabel(a.action)}</span></td>
                    <td>{entityLabel(a.entity)}{a.entity_id && <span className="muted"> {a.entity_id}</span>}</td>
                    <td>{a.field}</td>
                    <td className="adm-change">
                      <span className="adm-old">{cut(a.old) || <i className="muted">boş</i>}</span>
                      <span className="muted"> → </span>
                      <span className="adm-new">{cut(a.new) || <i className="muted">boş</i>}</span>
                    </td>
                  </tr>
                ))}
                {!audit.data.items.length && <tr><td colSpan={7} className="muted">Kayıt bulunamadı.</td></tr>}
              </tbody>
            </table>
          </div>
          {pages > 1 && <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}><Pager page={page} pages={pages} onPage={setPage} /></div>}
        </>
      )}
      {detail && (
        <Modal wide title={`Denetim kaydı #${fmtNum(detail.id)}`} onClose={() => setDetail(null)}>
          <div className="adm-form">
            <div><b>Zaman:</b> {fmtDate(detail.ts)} · <b>Kullanıcı:</b> {detail.username}</div>
            <div>
              <b>İşlem:</b> {actionLabel(detail.action)} · <b>Kayıt:</b> {entityLabel(detail.entity)} {detail.entity_id}
              {detail.field && <> · <b>Alan:</b> {detail.field}</>}
              {detail.project_id != null && <> · <b>Proje:</b> {projName.get(detail.project_id) ?? `#${detail.project_id}`}</>}
            </div>
            <div><b>Eski değer</b><pre className="adm-pre">{detail.old ?? "—"}</pre></div>
            <div><b>Yeni değer</b><pre className="adm-pre">{detail.new ?? "—"}</pre></div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  return (
    <div className="row" style={{ gap: 4 }}>
      <button className="btn small" disabled={page <= 1} onClick={() => onPage(1)}>«</button>
      <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Önceki</button>
      <span className="muted">Sayfa {fmtNum(page)} / {fmtNum(pages)}</span>
      <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>Sonraki ›</button>
      <button className="btn small" disabled={page >= pages} onClick={() => onPage(pages)}>»</button>
    </div>
  );
}
