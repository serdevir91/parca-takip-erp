import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes, Calculator, ClipboardCheck, Clock, Contact, Factory, FileText, FolderKanban, GitCompare, House, Layers,
  ListTree, LogOut, Menu, Moon, RefreshCw, Settings, ShoppingCart, Sun, TrendingUp, Wallet, Wrench, type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth, type Module } from "../api/auth";
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

type Item = { to: string; label: string; icon: LucideIcon; module?: Module; end?: boolean };
type Group = { title: string; items: Item[] };

const GROUPS: Group[] = [
  { title: "", items: [{ to: "/", label: "Ana sayfa", icon: House, end: true }] },
  { title: "Mühendislik", items: [{ to: "/projects", label: "Projeler", icon: FolderKanban, module: "projects" }] },
  {
    title: "Planlama ve üretim", items: [
      { to: "/purchasing", label: "Satın alma", icon: ShoppingCart, module: "purchasing" },
      { to: "/work-orders", label: "İş emirleri", icon: Factory, module: "workorders" },
      { to: "/stock", label: "Stok", icon: Boxes, module: "stock" },
      { to: "/hr", label: "Personel ve zaman", icon: Clock, module: "hr" },
    ],
  },
  {
    title: "Ticari", items: [
      { to: "/contacts", label: "Cari kartlar", icon: Contact, module: "contacts" },
      { to: "/sales", label: "Satış ve teklif", icon: TrendingUp, module: "sales" },
      { to: "/finance", label: "Fatura ve ödeme", icon: Wallet, module: "finance" },
    ],
  },
  { title: "Sistem", items: [{ to: "/admin", label: "Yönetim", icon: Settings, module: "admin" }] },
];

const PROJECT_ITEMS: Item[] = [
  { to: "", label: "Proje özeti", icon: Layers, module: "projects", end: true },
  { to: "/parts", label: "Parça listesi", icon: ListTree, module: "parts" },
  { to: "/fasteners", label: "Bağlantı elemanları", icon: Wrench, module: "fasteners" },
  { to: "/bom", label: "BOM sürümleri", icon: GitCompare, module: "projects" },
  { to: "/drawings", label: "Teknik resimler", icon: FileText, module: "drawings" },
  { to: "/control", label: "Kontrol listesi", icon: ClipboardCheck, module: "control" },
  { to: "/planning", label: "İhtiyaç ve maliyet", icon: Calculator, module: "planning" },
  { to: "/purchasing", label: "Satın alma", icon: ShoppingCart, module: "purchasing" },
  { to: "/work-orders", label: "İş emirleri", icon: Factory, module: "workorders" },
];

const COLLAPSE_KEY = "erp_sidebar_collapsed";
const readCollapsed = () => {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
};

/** Polls the server's write counter; when another computer (or this one) saved something, every open
 *  screen refetches. Also re-reads the user so permission changes apply without logging out. */
function useLiveSync() {
  const qc = useQueryClient();
  const { reloadUser } = useAuth();
  const last = useRef<number | null>(null);
  const q = useQuery({
    queryKey: ["sync"],
    queryFn: () => api.get<{ rev: number }>("/sync"),
    refetchInterval: 4000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const rev = q.data?.rev;
  useEffect(() => {
    if (rev == null) return;
    if (last.current !== null && rev !== last.current) {
      void qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "sync" && x.queryKey[0] !== "version" });
      reloadUser();
    }
    last.current = rev;
  }, [rev, qc, reloadUser]);
  return { online: !q.isError && q.data != null, lastSync: q.dataUpdatedAt };
}

const THEME_NEXT: Record<ThemeMode, ThemeMode> = { light: "dark", dark: "amoled", amoled: "light" };

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { mode, setMode } = useTheme();
  const upd = useUpdate();
  const nav = useNavigate();
  const { pid } = useParams();
  const { project } = useProject();
  const live = useLiveSync();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };
  const visible = (i: Item) => !i.module || can(i.module);
  const link = (i: Item, to = i.to) => (
    <NavLink key={to} to={to} end={i.end} title={collapsed ? i.label : undefined}>
      <i.icon size={17} strokeWidth={1.9} aria-hidden />
      <span className="nav-label">{i.label}</span>
    </NavLink>
  );
  const ThemeIcon = mode === "light" ? Sun : Moon;

  return (
    <div className={collapsed ? "app collapsed" : "app"}>
      <aside className="sidebar">
        <div className="brand">
          <button className="icon-btn" onClick={toggle} aria-label={collapsed ? "Menüyü aç" : "Menüyü daralt"}>
            <Menu size={18} />
          </button>
          <span className="brand-logo">P</span>
          <span className="nav-label brand-name">Parça Takip <b>ERP</b></span>
        </div>
        <nav>
          {GROUPS.map((g) => {
            const items = g.items.filter(visible);
            if (!items.length) return null;
            return (
              <div key={g.title || "home"} className="nav-group">
                {g.title && <div className="section">{g.title}</div>}
                {items.map((i) => link(i))}
                {g.title === "Mühendislik" && pid && (
                  <div className="nav-project">
                    <div className="section project-name" title={project?.name}>{project?.name ?? "Proje"}</div>
                    {PROJECT_ITEMS.filter(visible).map((i) => link(i, `/p/${pid}${i.to}`))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className={live.online ? "live on" : "live off"}
            title={live.online ? "Sunucuya bağlı. Diğer bilgisayarlardaki değişiklikler birkaç saniye içinde görünür."
              : "Sunucuya ulaşılamıyor. Ağ bağlantısını kontrol edin."}>
            <span className="dot" />{live.online ? "Canlı" : "Bağlantı yok"}
          </span>
          <span className="spacer" />
          <button className="icon-btn" title={`Tema: ${THEME_LABELS[mode]} (değiştirmek için tıklayın)`}
            aria-label="Temayı değiştir" onClick={() => setMode(THEME_NEXT[mode])}>
            <ThemeIcon size={17} />
            <span className="icon-btn-text">{THEME_LABELS[mode]}</span>
          </button>
          <button className="icon-btn" disabled={upd.checking} onClick={() => void upd.check(true)}
            title={upd.message || `Sürüm ${upd.info.current}`} aria-label="Güncellemeleri denetle">
            <RefreshCw size={17} className={upd.checking ? "spin" : undefined} />
          </button>
          <div className="user-chip" title={ROLE_LABELS[user?.role ?? ""] ?? user?.role}>
            <span className="avatar">{(user?.full_name || user?.username || "?").slice(0, 1).toLocaleUpperCase("tr-TR")}</span>
            <span className="user-text">
              <b>{user?.full_name || user?.username}</b>
              <small>{ROLE_LABELS[user?.role ?? ""] ?? user?.role}</small>
            </span>
          </div>
          <button className="icon-btn" title="Çıkış" aria-label="Çıkış" onClick={() => { logout(); nav("/login"); }}>
            <LogOut size={17} />
          </button>
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

/** Page title row: icon, title, optional subtitle and actions on the right. */
export function PageHeader({ icon: Icon, title, sub, children }: {
  icon?: LucideIcon; title: string; sub?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      {Icon && <span className="page-icon"><Icon size={20} /></span>}
      <div className="page-title">
        <h1>{title}</h1>
        {sub && <div className="muted">{sub}</div>}
      </div>
      <div className="page-actions">{children}</div>
    </div>
  );
}
