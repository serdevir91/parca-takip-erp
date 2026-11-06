import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api, upload } from "../api/client";
import { makeThumb } from "../api/images";
import { saveRev } from "../api/conflict";
import { useAuth } from "../api/auth";
import { FolderKanban } from "lucide-react";
import { Page, PageHeader } from "../components/Layout";
import { Modal } from "./admin/shared";
import Thumb, { forgetThumb } from "../components/viewer/Thumb";
import { errText, useToast } from "../components/Toast";
import { exportSheet } from "../api/exportFile";
import type { Project } from "../types";
import { LOCALE, tx } from "../api/i18n";

type Template = { id: number; name: string; note: string; nodes: number };

const fmt = (s: string | null | undefined) => (s ? new Date(s).toLocaleString(LOCALE) : "—");

export default function Projects() {
  const { can, isAdmin } = useAuth();
  const canEdit = can("projects", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [form, setForm] = useState<{ id?: number; rev?: number; name: string; root_part_no: string; description: string; template_id?: number } | null>(null);
  const [asTemplate, setAsTemplate] = useState<{ project_id: number; name: string; note: string } | null>(null);
  const [dropping, setDropping] = useState(false);
  const [picture, setPicture] = useState<File | null | undefined>(undefined);   // undefined: no change, null: remove
  const go = useNavigate();
  const templates = useQuery({ queryKey: ["project-templates"], queryFn: () => api.get<Template[]>("/project-templates"), enabled: canEdit });
  const [purge, setPurge] = useState<Project | null>(null);
  const q = useQuery({
    queryKey: ["projects", showArchived],
    queryFn: () => api.get<Project[]>(`/projects?include_archived=${showArchived}`),
  });
  const done = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const current = q.data?.find((p) => p.id === form?.id);
  const preview = useMemo(() => (picture ? URL.createObjectURL(picture) : null), [picture]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const openForm = (f: NonNullable<typeof form>) => { setPicture(undefined); setForm(f); };
  const savePicture = async (p: Project) => {
    if (picture === undefined) return;
    if (p.photo_id) forgetThumb(`/photos/${p.photo_id}/thumb`);
    if (picture === null) {
      if (p.photo_id) await api.del(`/photos/${p.photo_id}`);
      return;
    }
    const data = new FormData();
    data.append("entity", "project");
    data.append("key", String(p.id));
    data.append("file", picture);
    const t = await makeThumb(picture, 960);
    if (t) data.append("thumb", t, "t.jpg");
    await upload("/photos", data);
  };
  const save = useMutation({
    mutationFn: (f: NonNullable<typeof form>) =>
      f.id ? saveRev(f.rev, (rev) => api.patch<Project>(`/projects/${f.id}`, { ...f, rev })) : api.post<Project>("/projects", f),
    onSuccess: async (p, f) => {
      toast(tx("Proje kaydedildi"));
      setForm(null);
      try {
        await savePicture(p);
      } catch (e) {
        toast(errText(e), true);
      }
      done();
      if (f.template_id) go(`/p/${p.id}/tree`);
    },
    onError: (e) => toast(errText(e), true),
  });
  const saveTemplate = useMutation({
    mutationFn: (t: NonNullable<typeof asTemplate>) => api.post("/project-templates", t),
    onSuccess: () => {
      toast(tx("Şablon kaydedildi"));
      setAsTemplate(null);
      void qc.invalidateQueries({ queryKey: ["project-templates"] });
    },
    onError: (e) => toast(errText(e), true),
  });
  const dropTemplate = useMutation({
    mutationFn: (id: number) => api.del(`/project-templates/${id}`),
    onSuccess: () => {
      setDropping(false);
      setForm((f) => f && { ...f, template_id: undefined });
      void qc.invalidateQueries({ queryKey: ["project-templates"] });
    },
    onError: (e) => toast(errText(e), true),
  });
  const archive = useMutation({
    mutationFn: (p: Project) => (p.archived ? api.post(`/projects/${p.id}/restore`) : api.del(`/projects/${p.id}`)),
    onSuccess: done,
    onError: (e) => toast(errText(e), true),
  });

  return (
    <Page>
      <PageHeader icon={FolderKanban} title={tx("Projeler")} sub={tx("Makine projeleri, BOM sürümleri ve parça takibi")}>
        <label className="row"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />{" "}{tx("Arşivdekileri göster")}</label>
        <button className="btn" disabled={!q.data?.length} onClick={() => exportSheet(tx("Projeler"),
          [tx("Proje"), tx("Kök parça"), tx("Açıklama"), tx("Takip edilen parça"), tx("Oluşturma"), tx("Arşivde")],
          (q.data ?? []).map((p) => [p.name, p.root_part_no, p.description, p.tracked_parts, p.created_at?.slice(0, 10) ?? "", p.archived ? tx("Evet") : tx("Hayır")]),
        ).catch((e) => toast(errText(e), true))}>{tx("Excel'e aktar")}</button>
        {canEdit && <button className="btn primary" onClick={() => openForm({ name: "", root_part_no: "", description: "" })}>{tx("Yeni proje")}</button>}
      </PageHeader>
      {q.isLoading && <div className="muted">{tx("Yükleniyor…")}</div>}
      {q.error && <div className="error">{errText(q.error)}</div>}
      {q.data && q.data.length === 0 && <div className="card muted">{tx("Henüz proje yok. “Yeni proje” ile başlayın, ardından BOM Sürümleri ekranından CSV yükleyin.")}</div>}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {q.data?.map((p) => (
          <div key={p.id} className="card" style={{ opacity: p.archived ? 0.6 : 1 }}>
            {p.photo_id != null && <Link to={`/p/${p.id}`} tabIndex={-1}><Thumb path={`/photos/${p.photo_id}/thumb`} label={p.name} className="project-photo" /></Link>}
            <div className="row">
              <Link to={`/p/${p.id}`} style={{ fontSize: 16, fontWeight: 600 }}>{p.name}</Link>
              {p.archived && <span className="badge">{tx("Arşiv")}</span>}
              {p.pending_versions > 0 && <span className="badge warn">{tx("{0} onay bekleyen BOM", p.pending_versions)}</span>}
            </div>
            <div className="muted">{p.root_part_no || tx("Kök parça henüz yok")}</div>
            {p.description && <div style={{ marginTop: 6 }}>{p.description}</div>}
            <div style={{ marginTop: 8 }} className="muted">
              {tx("Takipteki parça:")}{" "}<b>{p.tracked_parts}</b><br />
              {tx("Aktif BOM:")}{" "}{p.current_version ? `#${p.current_version.seq} ${p.current_version.filename} (${fmt(p.current_version.approved_at)})` : "—"}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <Link className="btn small" to={`/p/${p.id}`}>{tx("Özet")}</Link>
              <Link className="btn small" to={`/p/${p.id}/parts`}>{tx("Parçalar")}</Link>
              {canEdit && <button className="btn small" onClick={() => openForm({ id: p.id, rev: p.rev, name: p.name, root_part_no: p.root_part_no, description: p.description })}>{tx("Düzenle")}</button>}
              {canEdit && <button className="btn small" onClick={() => setAsTemplate({ project_id: p.id, name: p.name, note: "" })}>{tx("Şablon yap")}</button>}
              {isAdmin && (
                <button className="btn small" onClick={() => (p.archived || confirm(tx("“{0}” arşivlensin mi?", p.name))) && archive.mutate(p)}>
                  {p.archived ? tx("Arşivden çıkar") : tx("Arşivle")}
                </button>
              )}
              {isAdmin && <button className="btn small danger" onClick={() => setPurge(p)}>{tx("Sil")}</button>}
            </div>
          </div>
        ))}
      </div>
      {purge && <PurgeDialog project={purge} onClose={() => setPurge(null)} onDone={() => { setPurge(null); done(); }} />}
      {form && (
        <div className="modal-back" onClick={() => setForm(null)}>
          <form className="modal" style={{ maxWidth: 480 }} onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
            <h2>{form.id ? tx("Projeyi düzenle") : tx("Yeni proje")}</h2>
            <div className="grid">
              <label>{tx("Proje adı")}<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: "100%" }} /></label>
              <label>{tx("Kök parça no (boş bırakılırsa ilk BOM'dan alınır)")}<input value={form.root_part_no} onChange={(e) => setForm({ ...form, root_part_no: e.target.value })} style={{ width: "100%" }} /></label>
              <label>{tx("Açıklama")}<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ width: "100%" }} /></label>
              <div>
                {tx("Proje resmi")}
                <div className="row" style={{ marginTop: 4 }}>
                  {preview ? <img className="project-photo-pick" src={preview} alt="" />
                    : picture === undefined && current?.photo_id != null && <Thumb path={`/photos/${current.photo_id}/thumb`} label={current.name} className="project-photo-pick" />}
                  <label className="btn small">
                    {tx("Resim seç")}
                    <input type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) setPicture(f); e.target.value = ""; }} />
                  </label>
                  {(picture || (picture === undefined && current?.photo_id != null)) && <button type="button" className="btn small" onClick={() => setPicture(null)}>{tx("Resmi kaldır")}</button>}
                </div>
              </div>
              {!form.id && !!templates.data?.length && (
                <label>{tx("Şablon (ürün ağacı buradan başlar)")}
                  <select value={form.template_id ?? ""} style={{ width: "100%" }}
                    onChange={(e) => { setDropping(false); setForm({ ...form, template_id: e.target.value ? Number(e.target.value) : undefined }); }}>
                    <option value="">{tx("Boş proje")}</option>
                    {templates.data.map((t) => <option key={t.id} value={t.id}>{tx("{0} ({1} parça)", t.name, t.nodes)}</option>)}
                  </select>
                </label>
              )}
              {!form.id && form.template_id && (dropping ? (
                <div className="row">
                  <span>{tx("Bu şablon silinsin mi?")}</span>
                  <button type="button" className="btn small danger" disabled={dropTemplate.isPending} onClick={() => dropTemplate.mutate(form.template_id!)}>{tx("Evet, sil")}</button>
                  <button type="button" className="btn small" onClick={() => setDropping(false)}>{tx("Hayır")}</button>
                </div>
              ) : (
                <div><button type="button" className="btn small" onClick={() => setDropping(true)}>{tx("Şablonu sil")}</button></div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setForm(null)}>{tx("Vazgeç")}</button>
              <button className="btn primary" disabled={save.isPending}>{tx("Kaydet")}</button>
            </div>
          </form>
        </div>
      )}
      {asTemplate && (
        <Modal
          title={tx("Şablon olarak kaydet")}
          onClose={() => setAsTemplate(null)}
          footer={
            <>
              <button className="btn" onClick={() => setAsTemplate(null)}>{tx("Vazgeç")}</button>
              <button className="btn primary" disabled={saveTemplate.isPending || !asTemplate.name.trim()} onClick={() => saveTemplate.mutate(asTemplate)}>{tx("Kaydet")}</button>
            </>
          }
        >
          <p className="muted">{tx("Projenin ürün ağacı kaydedilir. Yeni projeler bundan başlatılabilir.")}</p>
          <label>{tx("Şablon adı")}<input autoFocus value={asTemplate.name} maxLength={200} style={{ width: "100%" }} onChange={(e) => setAsTemplate({ ...asTemplate, name: e.target.value })} /></label>
          <label>{tx("Not")}<textarea rows={2} value={asTemplate.note} maxLength={1000} style={{ width: "100%" }} onChange={(e) => setAsTemplate({ ...asTemplate, note: e.target.value })} /></label>
        </Modal>
      )}
    </Page>
  );
}

type Impact = { deleted: Record<string, number>; unlinked: Record<string, number> };
const IMPACT_LABELS: Record<string, string> = {
  bom_versions: tx("BOM sürümü"), tracked_parts: tx("takip satırı"), work_orders: tx("iş emri"), control_issues: tx("kontrol kaydı"),
  purchase_orders: tx("satın alma siparişi"), sales_orders: tx("satış siparişi"), invoices: "fatura", stock_moves: tx("stok hareketi"),
  time_entries: tx("zaman kaydı"), drawings: tx("teknik resim"),
};

function impactList(counts: Record<string, number>) {
  return Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => (
    <li key={k}><b>{n.toLocaleString(LOCALE)}</b> {IMPACT_LABELS[k] ?? k}</li>
  ));
}

/** Permanent delete: shows what goes and what stays, then asks for a yes. */
function PurgeDialog({ project, onClose, onDone }: { project: Project; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const impact = useQuery({
    queryKey: ["project-delete-impact", project.id],
    queryFn: () => api.get<Impact>(`/projects/${project.id}/delete-impact`),
    gcTime: 0,
  });
  const [backupError, setBackupError] = useState("");
  const purge = useMutation({
    mutationFn: (skip_backup: boolean) => api.post<{ backup: string }>(`/projects/${project.id}/purge`, { skip_backup }),
    onSuccess: (r) => { toast(r.backup ? tx("Proje silindi. Silmeden önceki yedek: {0}", r.backup) : tx("Proje yedeksiz silindi.")); onDone(); },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 424) setBackupError(errText(e));
      else toast(errText(e), true);
    },
  });
  const deleted = impact.data ? impactList(impact.data.deleted) : [];
  const unlinked = impact.data ? impactList(impact.data.unlinked) : [];
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 520 }} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{tx("“{0}” kalıcı olarak silinsin mi?", project.name)}</h3>
        {impact.error && <div className="error">{errText(impact.error)}</div>}
        {impact.isLoading && <p className="muted">{tx("Kayıtlar sayılıyor…")}</p>}
        {impact.data && (
          <>
            <p>{tx("Bu işlem geri alınamaz. Silinmeden önce otomatik yedek alınır; veriler yalnızca o yedekten dönebilir.")}</p>
            {deleted.length > 0 && <><b>{tx("Projeyle birlikte silinir:")}</b><ul>{deleted}</ul></>}
            {unlinked.length > 0 && <><b>{tx("Silinmez, proje bağlantısı kalkar:")}</b><ul>{unlinked}</ul></>}
          </>
        )}
        {backupError
          ? <div className="error">{backupError}<br />{tx("Yine de silerseniz veriler geri getirilemez.")}</div>
          : <p><b>{tx("Onaylıyor musunuz?")}</b></p>}
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button className="btn" onClick={onClose} disabled={purge.isPending}>{tx("Vazgeç")}</button>
          <button className="btn danger" onClick={() => purge.mutate(!!backupError)} disabled={purge.isPending || !impact.data}>
            {purge.isPending ? tx("Siliniyor…") : backupError ? tx("Yedeksiz kalıcı olarak sil") : tx("Evet, kalıcı olarak sil")}
          </button>
        </div>
      </div>
    </div>
  );
}
