import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { saveRev } from "../api/conflict";
import { useAuth } from "../api/auth";
import { FolderKanban } from "lucide-react";
import { Page, PageHeader } from "../components/Layout";
import { Modal } from "./admin/shared";
import { errText, useToast } from "../components/Toast";
import type { Project } from "../types";

type Template = { id: number; name: string; note: string; nodes: number };

const fmt = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("tr-TR") : "—");

export default function Projects() {
  const { can, isAdmin } = useAuth();
  const canEdit = can("projects", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [form, setForm] = useState<{ id?: number; rev?: number; name: string; root_part_no: string; description: string; template_id?: number } | null>(null);
  const [asTemplate, setAsTemplate] = useState<{ project_id: number; name: string; note: string } | null>(null);
  const [dropping, setDropping] = useState(false);
  const go = useNavigate();
  const templates = useQuery({ queryKey: ["project-templates"], queryFn: () => api.get<Template[]>("/project-templates"), enabled: canEdit });
  const [purge, setPurge] = useState<Project | null>(null);
  const q = useQuery({
    queryKey: ["projects", showArchived],
    queryFn: () => api.get<Project[]>(`/projects?include_archived=${showArchived}`),
  });
  const done = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const save = useMutation({
    mutationFn: (f: NonNullable<typeof form>) =>
      f.id ? saveRev(f.rev, (rev) => api.patch<Project>(`/projects/${f.id}`, { ...f, rev })) : api.post<Project>("/projects", f),
    onSuccess: (p, f) => {
      toast("Proje kaydedildi");
      setForm(null);
      done();
      if (f.template_id) go(`/p/${p.id}/tree`);
    },
    onError: (e) => toast(errText(e), true),
  });
  const saveTemplate = useMutation({
    mutationFn: (t: NonNullable<typeof asTemplate>) => api.post("/project-templates", t),
    onSuccess: () => {
      toast("Şablon kaydedildi");
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
      <PageHeader icon={FolderKanban} title="Projeler" sub="Makine projeleri, BOM sürümleri ve parça takibi">
        <label className="row"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Arşivdekileri göster</label>
        {canEdit && <button className="btn primary" onClick={() => setForm({ name: "", root_part_no: "", description: "" })}>Yeni proje</button>}
      </PageHeader>
      {q.isLoading && <div className="muted">Yükleniyor…</div>}
      {q.error && <div className="error">{errText(q.error)}</div>}
      {q.data && q.data.length === 0 && <div className="card muted">Henüz proje yok. “Yeni proje” ile başlayın, ardından BOM Sürümleri ekranından CSV yükleyin.</div>}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {q.data?.map((p) => (
          <div key={p.id} className="card" style={{ opacity: p.archived ? 0.6 : 1 }}>
            <div className="row">
              <Link to={`/p/${p.id}`} style={{ fontSize: 16, fontWeight: 600 }}>{p.name}</Link>
              {p.archived && <span className="badge">Arşiv</span>}
              {p.pending_versions > 0 && <span className="badge warn">{p.pending_versions} onay bekleyen BOM</span>}
            </div>
            <div className="muted">{p.root_part_no || "Kök parça henüz yok"}</div>
            {p.description && <div style={{ marginTop: 6 }}>{p.description}</div>}
            <div style={{ marginTop: 8 }} className="muted">
              Takipteki parça: <b>{p.tracked_parts}</b><br />
              Aktif BOM: {p.current_version ? `#${p.current_version.seq} ${p.current_version.filename} (${fmt(p.current_version.approved_at)})` : "—"}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <Link className="btn small" to={`/p/${p.id}`}>Özet</Link>
              <Link className="btn small" to={`/p/${p.id}/parts`}>Parçalar</Link>
              {canEdit && <button className="btn small" onClick={() => setForm({ id: p.id, rev: p.rev, name: p.name, root_part_no: p.root_part_no, description: p.description })}>Düzenle</button>}
              {canEdit && <button className="btn small" onClick={() => setAsTemplate({ project_id: p.id, name: p.name, note: "" })}>Şablon yap</button>}
              {isAdmin && (
                <button className="btn small" onClick={() => (p.archived || confirm(`“${p.name}” arşivlensin mi?`)) && archive.mutate(p)}>
                  {p.archived ? "Arşivden çıkar" : "Arşivle"}
                </button>
              )}
              {isAdmin && <button className="btn small danger" onClick={() => setPurge(p)}>Sil</button>}
            </div>
          </div>
        ))}
      </div>
      {purge && <PurgeDialog project={purge} onClose={() => setPurge(null)} onDone={() => { setPurge(null); done(); }} />}
      {form && (
        <div className="modal-back" onClick={() => setForm(null)}>
          <form className="modal" style={{ maxWidth: 480 }} onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
            <h2>{form.id ? "Projeyi düzenle" : "Yeni proje"}</h2>
            <div className="grid">
              <label>Proje adı<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: "100%" }} /></label>
              <label>Kök parça no (boş bırakılırsa ilk BOM'dan alınır)<input value={form.root_part_no} onChange={(e) => setForm({ ...form, root_part_no: e.target.value })} style={{ width: "100%" }} /></label>
              <label>Açıklama<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ width: "100%" }} /></label>
              {!form.id && !!templates.data?.length && (
                <label>Şablon (ürün ağacı buradan başlar)
                  <select value={form.template_id ?? ""} style={{ width: "100%" }}
                    onChange={(e) => { setDropping(false); setForm({ ...form, template_id: e.target.value ? Number(e.target.value) : undefined }); }}>
                    <option value="">Boş proje</option>
                    {templates.data.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.nodes} parça)</option>)}
                  </select>
                </label>
              )}
              {!form.id && form.template_id && (dropping ? (
                <div className="row">
                  <span>Bu şablon silinsin mi?</span>
                  <button type="button" className="btn small danger" disabled={dropTemplate.isPending} onClick={() => dropTemplate.mutate(form.template_id!)}>Evet, sil</button>
                  <button type="button" className="btn small" onClick={() => setDropping(false)}>Hayır</button>
                </div>
              ) : (
                <div><button type="button" className="btn small" onClick={() => setDropping(true)}>Şablonu sil</button></div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setForm(null)}>Vazgeç</button>
              <button className="btn primary" disabled={save.isPending}>Kaydet</button>
            </div>
          </form>
        </div>
      )}
      {asTemplate && (
        <Modal
          title="Şablon olarak kaydet"
          onClose={() => setAsTemplate(null)}
          footer={
            <>
              <button className="btn" onClick={() => setAsTemplate(null)}>Vazgeç</button>
              <button className="btn primary" disabled={saveTemplate.isPending || !asTemplate.name.trim()} onClick={() => saveTemplate.mutate(asTemplate)}>Kaydet</button>
            </>
          }
        >
          <p className="muted">Projenin ürün ağacı kaydedilir. Yeni projeler bundan başlatılabilir.</p>
          <label>Şablon adı<input autoFocus value={asTemplate.name} maxLength={200} style={{ width: "100%" }} onChange={(e) => setAsTemplate({ ...asTemplate, name: e.target.value })} /></label>
          <label>Not<textarea rows={2} value={asTemplate.note} maxLength={1000} style={{ width: "100%" }} onChange={(e) => setAsTemplate({ ...asTemplate, note: e.target.value })} /></label>
        </Modal>
      )}
    </Page>
  );
}

type Impact = { deleted: Record<string, number>; unlinked: Record<string, number> };
const IMPACT_LABELS: Record<string, string> = {
  bom_versions: "BOM sürümü", tracked_parts: "takip satırı", work_orders: "iş emri", control_issues: "kontrol kaydı",
  purchase_orders: "satın alma siparişi", sales_orders: "satış siparişi", invoices: "fatura", stock_moves: "stok hareketi",
  time_entries: "zaman kaydı", drawings: "teknik resim",
};

function impactList(counts: Record<string, number>) {
  return Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => (
    <li key={k}><b>{n.toLocaleString("tr-TR")}</b> {IMPACT_LABELS[k] ?? k}</li>
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
  const purge = useMutation({
    mutationFn: () => api.post<{ backup: string }>(`/projects/${project.id}/purge`, {}),
    onSuccess: (r) => { toast(r.backup ? `Proje silindi. Silmeden önceki yedek: ${r.backup}` : "Proje silindi."); onDone(); },
    onError: (e) => toast(errText(e), true),
  });
  const deleted = impact.data ? impactList(impact.data.deleted) : [];
  const unlinked = impact.data ? impactList(impact.data.unlinked) : [];
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 520 }} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>“{project.name}” kalıcı olarak silinsin mi?</h3>
        {impact.error && <div className="error">{errText(impact.error)}</div>}
        {impact.isLoading && <p className="muted">Kayıtlar sayılıyor…</p>}
        {impact.data && (
          <>
            <p>Bu işlem geri alınamaz. Silinmeden önce otomatik yedek alınır; veriler yalnızca o yedekten dönebilir.</p>
            {deleted.length > 0 && <><b>Projeyle birlikte silinir:</b><ul>{deleted}</ul></>}
            {unlinked.length > 0 && <><b>Silinmez, proje bağlantısı kalkar:</b><ul>{unlinked}</ul></>}
          </>
        )}
        <p><b>Onaylıyor musunuz?</b></p>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button className="btn" onClick={onClose} disabled={purge.isPending}>Vazgeç</button>
          <button className="btn danger" onClick={() => purge.mutate()} disabled={purge.isPending || !impact.data}>
            {purge.isPending ? "Yedek alınıp siliniyor…" : "Evet, kalıcı olarak sil"}
          </button>
        </div>
      </div>
    </div>
  );
}
