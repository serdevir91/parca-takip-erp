import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeMode = "light" | "dark" | "amoled";
export const THEME_LABELS: Record<ThemeMode, string> = { light: "Açık", dark: "Koyu", amoled: "Siyah (AMOLED)" };
const KEY = "erp_theme";

function initial(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "amoled") return v;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const Ctx = createContext<{ mode: ThemeMode; setMode: (m: ThemeMode) => void }>({ mode: "light", setMode: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* storage unavailable */
    }
  }, [mode]);
  return <Ctx.Provider value={{ mode, setMode }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** Status colours come from the backend as Excel-style hex (no #). Dark themes get a dimmed tint. */
export function statusStyle(hex?: string | null): React.CSSProperties | undefined {
  if (!hex) return undefined;
  return { background: `color-mix(in srgb, #${hex} var(--status-mix), var(--bg))`, color: "var(--status-fg)" };
}
