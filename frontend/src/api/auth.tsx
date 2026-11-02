import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./client";

export type Role = "admin" | "designer" | "planner" | "viewer" | string;

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  role_label: string;
  active: boolean;
}

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  canEdit: boolean;
  canDesign: boolean;
  isAdmin: boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .get<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const form = new URLSearchParams({ username, password });
    const r = await api.post<{ access_token: string; user: User }>("/auth/login", form);
    setToken(r.access_token);
    setUser(r.user);
  }, []);

  const value = useMemo<AuthState>(() => {
    const role = user?.role;
    return {
      user,
      ready,
      login,
      logout,
      isAdmin: role === "admin",
      canDesign: role === "admin" || role === "designer",
      canEdit: role === "admin" || role === "designer" || role === "planner",
    };
  }, [user, ready, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
