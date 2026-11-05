import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setSys, type SystemDefaults } from "./system";
import { adoptLegacyToken, api, isSignedIn, setSignedIn, setUnauthorizedHandler } from "./client";
import { loadPrefs } from "./prefs";

export type Role = "admin" | "designer" | "planner" | "viewer" | string;
export type Level = "none" | "view" | "edit";
/** Permission modules (backend/app/permissions.py MODULES). */
export type Module =
  | "projects" | "parts" | "fasteners" | "drawings" | "control" | "planning" | "purchasing"
  | "workorders" | "stock" | "hr" | "attendance" | "contacts" | "sales" | "finance" | "chat" | "mail" | "admin";
const RANK: Record<Level, number> = { none: 0, view: 1, edit: 2 };

export interface User {
  id: number;
  username: string;
  full_name: string;
  email?: string;
  role: Role;
  role_label: string;
  active: boolean;
  system?: SystemDefaults;
  default_password?: boolean;
  /** Effective level per module: role defaults plus the admin's per-user overrides. */
  permissions?: Partial<Record<Module, Level>>;
}

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  /** Re-read /auth/me (role or permissions changed by an admin). */
  reloadUser: () => void;
  /** True when the user has at least `level` on `module`. */
  can: (module: Module, level?: Level) => boolean;
  canEdit: boolean;
  canDesign: boolean;
  isAdmin: boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const receive = useCallback((u: User) => {
    setSys(u.system);
    setUser(u);
  }, []);

  const forget = useCallback(() => {
    setSignedIn(false);
    setUser(null);
  }, []);

  const logout = useCallback(() => {
    void api.post("/auth/logout").catch(() => undefined);
    forget();
  }, [forget]);

  useEffect(() => {
    setUnauthorizedHandler(forget);
    // The cookie cannot be read from here, so only the server can say whether there is a session.
    adoptLegacyToken()
      .then(() => api.get<User>("/auth/me"))
      .then(async (u) => {
        setSignedIn(true);
        await loadPrefs();
        receive(u);
      })
      .catch(() => setSignedIn(false))
      .finally(() => setReady(true));
  }, [forget, receive]);

  const reloadUser = useCallback(() => {
    if (isSignedIn()) api.get<User>("/auth/me").then(receive).catch(() => undefined);
  }, [receive]);

  const login = useCallback(async (username: string, password: string) => {
    const form = new URLSearchParams({ username, password });
    const r = await api.post<{ user: User }>("/auth/login", form);
    setSignedIn(true);
    await loadPrefs();
    receive(r.user);
  }, [receive]);

  const value = useMemo<AuthState>(() => {
    const role = user?.role;
    const can = (module: Module, level: Level = "view") =>
      RANK[user?.permissions?.[module] ?? "none"] >= RANK[level];
    return {
      user,
      ready,
      login,
      logout,
      reloadUser,
      can,
      isAdmin: role === "admin",
      canDesign: role === "admin" || role === "designer",
      canEdit: role === "admin" || role === "designer" || role === "planner",
    };
  }, [user, ready, login, logout, reloadUser]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
