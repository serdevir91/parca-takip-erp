import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Loading, Modal, fmtDate, fmtNum } from "./shared";
import { tx } from "../../api/i18n";

type AuditItem = {
  id: number; ts: string | null; user_id: number | null; username: string; project_id: number | null;
  entity: string; entity_id: string; field: string; old: string | null; new: string | null; action: string;
};
type AuditPage = { total: number; page: number; page_size: number; items: AuditItem[] };
type Facets = { users: string[]; actions: string[]; entities: string[] };
type Project = { id: number; name: string };

const PAGE_SIZE = 100;
const ACTION_TR: Record<string, string> = {
  create: tx("Oluşturma"), update: tx("Güncelleme"), delete: tx("Silme"), upload: tx("Yükleme"), import: tx("İçe aktarma"),
  login: tx("Oturum açma"), restore: tx("Geri yükleme"), backup: tx("Yedekleme"), password: tx("Şifre değişikliği"),
  signup: tx("Hesap isteği"), approve: tx("Onay"), reject: tx("Ret"), mail: tx("E-posta"),
};
const ENTITY_TR: Record<string, string> = {
  project: tx("Proje"), project_template: tx("Proje şablonu"), part: tx("Parça"), bom: "BOM", setting: tx("Ayar"), user: tx("Kullanıcı"), firm: tx("Firma"),
  fastener_rule: tx("Bağlantı elemanı kuralı"), tracking: tx("Takip"), drawing: tx("Teknik resim"), t35: tx("Durum listesi"),
  attendance: tx("Mesai"),
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
          <option value="">{tx("Tüm kullanıcılar")}</option>
          {facets.data?.users.map((u) => <option key={u} value={u}>{tx(u)}</option>)}
        </select>
        <select value={f.project_id} onChange={(e) => set("project_id", e.target.value)}>
          <option value="">{tx("Tüm projeler")}</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={f.action} onChange={(e) => set("action", e.target.value)}>
          <option value="">{tx("Tüm işlemler")}</option>
          {facets.data?.actions.map((a) => <option key={a} value={a}>{actionLabel(a)}</option>)}
        </select>
        <select value={f.entity} onChange={(e) => set("entity", e.target.value)}>
          <option value="">{tx("Tüm kayıt türleri")}</option>
          {facets.data?.entities.map((a) => <option key={a} value={a}>{entityLabel(a)}</option>)}
        </select>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{tx("Başlangıç")}</span>
          <input type="date" value={f.date_from} onChange={(e) => set("date_from", e.target.value)} />
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{tx("Bitiş")}</span>
          <input type="date" value={f.date_to} onChange={(e) => set("date_to", e.target.value)} />
        </label>
        <input placeholder={tx("Kayıt, alan veya değerde ara…")} value={qText} onChange={(e) => setQText(e.target.value)} />
        {anyFilter && <button className="btn small" onClick={() => { setF(EMPTY); setQText(""); }}>{tx("Filtreleri temizle")}</button>}
      </div>
      {facets.error && <Loading error={facets.error} loading={false} />}
      <Loading error={audit.error} loading={audit.isLoading} />
      {audit.data && (
        <>
          <div className="row" style={{ justifyContent: "space-between", margin: "8px 0" }}>
            <span className="muted">
              {tx("{0} kayıt", fmtNum(total))}{total > 0 && tx(" · {0}–{1} arası", fmtNum((page - 1) * PAGE_SIZE + 1), fmtNum(Math.min(page * PAGE_SIZE, total)))}
              {audit.isFetching && tx(" · yükleniyor…")}
            </span>
            <Pager page={page} pages={pages} onPage={setPage} />
          </div>
          <div className="adm-scroll">
            <table className="simple adm-audit">
              <thead>
                <tr><th>{tx("Zaman")}</th><th>{tx("Kullanıcı")}</th><th>{tx("Proje")}</th><th>{tx("İşlem")}</th><th>{tx("Kayıt")}</th><th>{tx("Alan")}</th><th>{tx("Eski → Yeni")}</th></tr>
              </thead>
              <tbody>
                {audit.data.items.map((a) => (
                  <tr key={a.id} onClick={() => setDetail(a)} style={{ cursor: "pointer" }} title={tx("Ayrıntı için tıklayın")}>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtDate(a.ts)}</td>
                    <td>{a.username}</td>
                    <td>{a.project_id != null ? projName.get(a.project_id) ?? `#${a.project_id}` : ""}</td>
                    <td><span className={`badge${a.action === "delete" ? " err" : a.action === "create" ? " new" : ""}`}>{actionLabel(a.action)}</span></td>
                    <td>{entityLabel(a.entity)}{a.entity_id && <span className="muted"> {a.entity_id}</span>}</td>
                    <td>{a.field}</td>
                    <td className="adm-change">
                      <span className="adm-old">{cut(tx(a.old)) || <i className="muted">{tx("boş")}</i>}</span>
                      <span className="muted"> → </span>
                      <span className="adm-new">{cut(tx(a.new)) || <i className="muted">{tx("boş")}</i>}</span>
                    </td>
                  </tr>
                ))}
                {!audit.data.items.length && <tr><td colSpan={7} className="muted">{tx("Kayıt bulunamadı.")}</td></tr>}
              </tbody>
            </table>
          </div>
          {pages > 1 && <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}><Pager page={page} pages={pages} onPage={setPage} /></div>}
        </>
      )}
      {detail && (
        <Modal wide title={tx("Denetim kaydı #{0}", fmtNum(detail.id))} onClose={() => setDetail(null)}>
          <div className="adm-form">
            <div><b>{tx("Zaman:")}</b> {fmtDate(detail.ts)} · <b>{tx("Kullanıcı:")}</b> {detail.username}</div>
            <div>
              <b>{tx("İşlem:")}</b> {actionLabel(detail.action)} · <b>{tx("Kayıt:")}</b> {entityLabel(detail.entity)} {detail.entity_id}
              {detail.field && <> · <b>{tx("Alan:")}</b> {detail.field}</>}
              {detail.project_id != null && <> · <b>{tx("Proje:")}</b> {projName.get(detail.project_id) ?? `#${detail.project_id}`}</>}
            </div>
            <div><b>{tx("Eski değer")}</b><pre className="adm-pre">{detail.old ?? "—"}</pre></div>
            <div><b>{tx("Yeni değer")}</b><pre className="adm-pre">{detail.new ?? "—"}</pre></div>
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
      <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>{tx("‹ Önceki")}</button>
      <span className="muted">{tx("Sayfa {0} / {1}", fmtNum(page), fmtNum(pages))}</span>
      <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>{tx("Sonraki ›")}</button>
      <button className="btn small" disabled={page >= pages} onClick={() => onPage(pages)}>»</button>
    </div>
  );
}
