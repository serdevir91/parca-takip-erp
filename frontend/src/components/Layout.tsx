import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import { THEME_LABELS, useTheme, type ThemeMode } from "../theme/theme";
import { UpdateBanner, useUpdate } from "./UpdateCheck";
import type { Project } from "../types";

export function useProject() {
  const { pid } = useParams();
  const id = Number(pid);
  const q = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`), enabled: !!id });
  return { pid: id, project: q.data, ...q };
}

const ROLE_LABELS: Record<string, string> = { admin: "Admin", designer: "Tasarımcı", planner: "Planlama/Satın alma", viewer: "İzleyici" };

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const { mode, setMode } = useTheme();
  const upd = useUpdate();
  const nav = useNavigate();
  const { pid } = useParams();
  const { project } = useProject();
  const p = pid ? `/p/${pid}` : null;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Parça Takip ERP</div>
        <nav>
          <NavLink to="/" end>Projeler</NavLink>
          {p && (
            <>
              <div className="section" title={project?.name}>{project?.name ?? "Proje"}</div>
              <NavLink to={`${p}`} end>Proje Özeti</NavLink>
              <NavLink to={`${p}/parts`}>Parça Listesi</NavLink>
              <NavLink to={`${p}/fasteners`}>Bağlantı Elemanları</NavLink>
              <NavLink to={`${p}/bom`}>BOM Sürümleri</NavLink>
              <NavLink to={`${p}/drawings`}>Teknik Resimler</NavLink>
              <NavLink to={`${p}/control`}>Kontrol Listesi</NavLink>
              <NavLink to={`${p}/planning`}>İhtiyaç & Maliyet</NavLink>
              <NavLink to={`${p}/purchasing`}>Satın Alma</NavLink>
              <NavLink to={`${p}/work-orders`}>İş Emirleri</NavLink>
            </>
          )}
          <div className="section">ERP</div>
          <NavLink to="/purchasing">Satın Alma</NavLink>
          <NavLink to="/work-orders">İş Emirleri</NavLink>
          <NavLink to="/stock">Stok</NavLink>
          {isAdmin && (
            <>
              <div className="section">Sistem</div>
              <NavLink to="/admin">Yönetim</NavLink>
            </>
          )}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="spacer" />
          <label className="row muted" title="Tema">
            Tema
            <select value={mode} onChange={(e) => setMode(e.target.value as ThemeMode)}>
              {(Object.keys(THEME_LABELS) as ThemeMode[]).map((m) => (
                <option key={m} value={m}>{THEME_LABELS[m]}</option>
              ))}
            </select>
          </label>
          <button className="btn small" disabled={upd.checking} onClick={() => void upd.check(true)} title={upd.message || `Sürüm ${upd.info.current}`}>
            {upd.checking ? "Denetleniyor…" : "Güncellemeleri denetle"}
          </button>
          <span className="muted">{user?.full_name || user?.username} · {ROLE_LABELS[user?.role ?? ""] ?? user?.role}</span>
          <button className="btn small" onClick={() => { logout(); nav("/login"); }}>Çıkış</button>
        </header>
        {upd.message && <div className="muted" style={{ padding: "4px 16px" }}>{upd.message}</div>}
        <UpdateBanner />
        <Outlet />
      </div>
    </div>
  );
}

/** Standard scrolling page body. Pages that need the full height (data grids) use <Page full>. */
export function Page({ children, full }: { children: React.ReactNode; full?: boolean }) {
  return <div className={full ? "content full" : "content"}>{children}</div>;
}
