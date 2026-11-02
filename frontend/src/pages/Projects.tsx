import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import { Page } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import type { Project } from "../types";

const fmt = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("tr-TR") : "—");

export default function Projects() {
  const { canEdit, isAdmin } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [form, setForm] = useState<{ id?: number; name: string; root_part_no: string; description: string } | null>(null);
  const q = useQuery({
    queryKey: ["projects", showArchived],
    queryFn: () => api.get<Project[]>(`/projects?include_archived=${showArchived}`),
  });
  const done = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const save = useMutation({
    mutationFn: (f: NonNullable<typeof form>) =>
      f.id ? api.patch<Project>(`/projects/${f.id}`, f) : api.post<Project>("/projects", f),
    onSuccess: () => { toast("Proje kaydedildi"); setForm(null); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const archive = useMutation({
    mutationFn: (p: Project) => (p.archived ? api.post(`/projects/${p.id}/restore`) : api.del(`/projects/${p.id}`)),
    onSuccess: done,
    onError: (e) => toast(errText(e), true),
  });

  return (
    <Page>
      <div className="row" style={{ marginBottom: 12 }}>
        <h1 style={{ margin: 0 }}>Projeler</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <label className="row"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Arşivdekileri göster</label>
        {canEdit && <button className="btn primary" onClick={() => setForm({ name: "", root_part_no: "", description: "" })}>Yeni proje</button>}
      </div>
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
              {canEdit && <button className="btn small" onClick={() => setForm({ id: p.id, name: p.name, root_part_no: p.root_part_no, description: p.description })}>Düzenle</button>}
              {isAdmin && (
                <button className="btn small" onClick={() => (p.archived || confirm(`“${p.name}” arşivlensin mi?`)) && archive.mutate(p)}>
                  {p.archived ? "Arşivden çıkar" : "Arşivle"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {form && (
        <div className="modal-back" onClick={() => setForm(null)}>
          <form className="modal" style={{ maxWidth: 480 }} onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
            <h2>{form.id ? "Projeyi düzenle" : "Yeni proje"}</h2>
            <div className="grid">
              <label>Proje adı<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: "100%" }} /></label>
              <label>Kök parça no (boş bırakılırsa ilk BOM'dan alınır)<input value={form.root_part_no} onChange={(e) => setForm({ ...form, root_part_no: e.target.value })} style={{ width: "100%" }} /></label>
              <label>Açıklama<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ width: "100%" }} /></label>
            </div>
            <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setForm(null)}>Vazgeç</button>
              <button className="btn primary" disabled={save.isPending}>Kaydet</button>
            </div>
          </form>
        </div>
      )}
    </Page>
  );
}
