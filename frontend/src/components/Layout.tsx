import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes, Calculator, ClipboardCheck, Clock, Contact, Factory, FileText, FolderKanban, GitCompare, House, IdCard, Layers,
  ListTree, LogOut, Menu, MessageCircle, Moon, Network, RefreshCw, ScanLine, Server, Settings, ShoppingCart, Sun, TrendingUp, Timer, Wallet, Wrench, type LucideIcon,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { mobileApp, onBack } from "../api/mobile";
import { useAuth, type Module } from "../api/auth";
import { THEME_LABELS, useTheme, type ThemeMode } from "../theme/theme";
import { DesktopMenu } from "./DesktopMenu";
import Profile from "./Profile";
import Notifications from "./Notifications";
import { UpdateBanner, useUpdate } from "./UpdateCheck";
import type { Project } from "../types";
import type { ChatState } from "../pages/Chat";
import { useToast } from "./Toast";
import BrandMark from "./BrandMark";
import { sys, useBrand } from "../api/system";

export function useProject() {
  const { pid } = useParams();
  const id = Number(pid);
  const q = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/projects/${id}`), enabled: !!id });
  return { pid: id, project: q.data, ...q };
}

const ROLE_LABELS: Record<string, string> = { admin: "Admin", designer: "Tasarımcı", planner: "Planlama/Satın alma", viewer: "İzleyici" };

// unless: hidden for users who have that module (they get the full screen instead)
// off: open to everyone, hidden only when that module is switched off for the company
// any: shown to users of at least one of these modules
type Item = { to: string; label: string; icon: LucideIcon; module?: Module; any?: Module[]; unless?: Module; off?: Module; end?: boolean };
type Group = { title: string; items: Item[] };

const GROUPS: Group[] = [
  { title: "", items: [{ to: "/", label: "Ana sayfa", icon: House, end: true }] },
  { title: "Mühendislik", items: [{ to: "/projects", label: "Projeler", icon: FolderKanban, module: "projects" }] },
  {
    title: "Planlama ve üretim", items: [
      { to: "/purchasing", label: "Satın alma", icon: ShoppingCart, module: "purchasing" },
      { to: "/work-orders", label: "İş emirleri", icon: Factory, module: "workorders" },
      { to: "/stock", label: "Stok", icon: Boxes, module: "stock" },
      { to: "/scan", label: "Barkod okut", icon: ScanLine, any: ["stock", "purchasing", "workorders"] },
      { to: "/hr", label: "Personel ve zaman", icon: Clock, module: "hr", end: true },
      { to: "/hr/me", label: "Personel kartım", icon: IdCard, unless: "hr" },
      { to: "/attendance", label: "Mesai takibi", icon: Timer, off: "attendance" },
    ],
  },
  {
    title: "Ticari", items: [
      { to: "/contacts", label: "Cari kartlar", icon: Contact, module: "contacts" },
      { to: "/sales", label: "Satış ve teklif", icon: TrendingUp, module: "sales" },
      { to: "/finance", label: "Fatura ve ödeme", icon: Wallet, module: "finance" },
    ],
  },
  {
    title: "Sistem", items: [
      { to: "/chat", label: "Sohbet", icon: MessageCircle, module: "chat" },
      { to: "/admin", label: "Yönetim", icon: Settings, module: "admin" },
    ],
  },
];

const PROJECT_ITEMS: Item[] = [
  { to: "", label: "Proje özeti", icon: Layers, module: "projects", end: true },
  { to: "/parts", label: "Parça listesi", icon: ListTree, module: "parts" },
  { to: "/fasteners", label: "Bağlantı elemanları", icon: Wrench, module: "fasteners" },
  { to: "/tree", label: "Ürün ağacı", icon: Network, module: "projects" },
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
  return { online: !q.isError && q.data != null && q.fetchStatus !== "paused", lastSync: q.dataUpdatedAt };
}

/** Chat has its own poll (chat writes do not bump the global rev): unread badge, "(n)" in the tab title,
 *  a toast for new messages outside the chat screen, and a refetch of open chat screens. */
function useChatPoll(enabled: boolean) {
  const qc = useQueryClient();
  const toast = useToast();
  const onChat = useLocation().pathname.startsWith("/chat");
  const last = useRef<ChatState | null>(null);
  const q = useQuery({
    queryKey: ["chat", "state"],
    queryFn: () => api.get<ChatState>("/chat/state"),
    refetchInterval: 4000,
    refetchIntervalInBackground: true,
    retry: false,
    enabled,
  });
  const st = q.data;
  useEffect(() => {
    if (!st) return;
    const prev = last.current;
    if (prev && prev.key !== st.key) {
      void qc.invalidateQueries({ predicate: (x) => x.queryKey[0] === "chat" && x.queryKey[1] !== "state" });
      if (!onChat && st.last_id > prev.last_id && st.unread > prev.unread) {
        toast(`Yeni mesaj · ${st.unread} okunmamış (Sohbet)`);
      }
    }
    last.current = st;
  }, [st, qc, onChat, toast]);
  const unread = enabled ? st?.unread ?? 0 : 0;
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\+?\) /, "");
    document.title = unread ? `(${unread > 99 ? "99+" : unread}) ${base}` : base;
  }, [unread]);
  return unread;
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
  const unread = useChatPoll(can("chat"));
  const signups = useQuery({
    queryKey: ["admin", "signups"],
    queryFn: () => api.get<{ pending: number }>("/admin/signups/count"),
    refetchInterval: 60_000,
    retry: false,
    enabled: user?.role === "admin",
  }).data?.pending ?? 0;
  const [collapsed, setCollapsed] = useState(readCollapsed);
  // Phones: the sidebar is an off-canvas menu opened from the top bar.
  const [navOpen, setNavOpen] = useState(false);
  const path = useLocation().pathname;
  useEffect(() => setNavOpen(false), [path]);
  useEffect(() => (navOpen ? onBack(() => (setNavOpen(false), true)) : undefined), [navOpen]);
  const app = mobileApp();
  const [profile, setProfile] = useState(false);
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
  const visible = (i: Item) => (!i.module || can(i.module)) && (!i.any || i.any.some((m) => can(m))) && !(i.unless && (can(i.unless) || sys.modules_off.includes(i.unless)))
    && !(i.off && sys.modules_off.includes(i.off));
  const brand = useBrand();
  const brandWords = brand.name.split(" ");
  const brandTail = brandWords.pop();
  const brandHead = brandWords.join(" ");
  const link = (i: Item, to = i.to) => (
    <NavLink key={to} to={to} end={i.end} title={collapsed ? i.label : undefined}>
      <i.icon size={17} strokeWidth={1.9} aria-hidden />
      <span className="nav-label">{i.label}</span>
      {i.to === "/chat" && unread > 0 && <span className="nav-badge">{unread > 99 ? "99+" : unread}</span>}
      {i.to === "/admin" && signups > 0 && <span className="nav-badge" title="Onay bekleyen hesap istekleri">{signups}</span>}
    </NavLink>
  );
  const ThemeIcon = mode === "light" ? Sun : Moon;

  return (
    <div className={`app${collapsed ? " collapsed" : ""}${navOpen ? " nav-open" : ""}`}>
      {navOpen && <div className="nav-backdrop" onClick={() => setNavOpen(false)} />}
      <aside className="sidebar">
        <div className="brand">
          <button className="icon-btn desk-only" onClick={toggle} aria-label={collapsed ? "Menüyü aç" : "Menüyü daralt"}>
            <Menu size={18} />
          </button>
          <button className="icon-btn mobile-only" onClick={() => setNavOpen(false)} aria-label="Menüyü kapat">
            <X size={18} />
          </button>
          <span className="brand-logo"><BrandMark logo={brand.logo} /></span>
          <span className="nav-label brand-name">{brandHead} <b>{brandTail}</b></span>
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
          <button className="icon-btn mobile-only nav-toggle" onClick={() => setNavOpen(true)} aria-label="Menü">
            <Menu size={20} />
            {unread > 0 && <span className="nav-dot" />}
          </button>
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
          <Notifications />
          <DesktopMenu />
          {app && (
            <button className="icon-btn" title="Sunucuyu değiştir" aria-label="Sunucuyu değiştir" onClick={() => app.changeServer()}>
              <Server size={17} />
            </button>
          )}
          <button className="icon-btn" disabled={upd.checking}
            onClick={() => { void upd.check(true); app?.checkUpdate(true); }}
            title={upd.message || `Sürüm ${upd.info.current}`} aria-label="Güncellemeleri denetle">
            <RefreshCw size={17} className={upd.checking ? "spin" : undefined} />
          </button>
          <button className="user-chip" title="Profilim: ad ve şifre" onClick={() => setProfile(true)}>
            <span className="avatar">{(user?.full_name || user?.username || "?").slice(0, 1).toLocaleUpperCase("tr-TR")}</span>
            <span className="user-text">
              <b>{user?.full_name || user?.username}</b>
              <small>{ROLE_LABELS[user?.role ?? ""] ?? user?.role}</small>
            </span>
          </button>
          <button className="icon-btn" title="Çıkış" aria-label="Çıkış" onClick={() => { logout(); nav("/login"); }}>
            <LogOut size={17} />
          </button>
        </header>
        {upd.message && <div className="muted" style={{ padding: "4px 16px" }}>{upd.message}</div>}
        <UpdateBanner />
        {user?.default_password && (
          <div className="card alerts" style={{ margin: "8px 16px" }}>
            <b>Yönetici şifresi hâlâ varsayılan (admin).</b> Ağdaki herkes yönetici olarak girebilir.{" "}
            <button className="btn sm" onClick={() => setProfile(true)}>Şifreyi değiştir</button>
          </div>
        )}
        <Outlet />
        {profile && <Profile onClose={() => setProfile(false)} />}
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
