// Bridge to the Windows desktop app (desktop/parca_takip_desktop.py). The app exposes its Python API as
// window.pywebview.api; in a normal browser desktop() is null and the web code paths are used.

export type DesktopFileRequest = {
  path: string; // API path without the /api prefix
  token: string | null;
  lang?: string;
  filename: string; // used when the response has no Content-Disposition name
  action: "save" | "open"; // save: "Farklı kaydet" dialog; open: temp file opened with the default program
  method?: "GET" | "POST";
  body?: unknown;
};
export type DesktopFileResult = { ok: boolean; cancelled?: boolean; status?: number; error?: string; path?: string };

type DesktopApi = { file_request(req: DesktopFileRequest): Promise<DesktopFileResult> };

export function desktop(): DesktopApi | null {
  const api = (window as unknown as { pywebview?: { api?: Partial<DesktopApi> } }).pywebview?.api;
  return api && typeof api.file_request === "function" ? (api as DesktopApi) : null;
}

export type DesktopInfo = { version: string; mode: "server" | "client"; base: string; addresses: string[]; data_dir: string; config: string; background?: boolean };
export type DesktopAction = "reload" | "settings" | "open_data" | "update" | "quit" | "restart";
type DesktopShell = {
  app_info(): Promise<DesktopInfo>;
  app_action(name: DesktopAction): Promise<{ ok: boolean; error?: string }>;
  set_theme(t: { dark: boolean; caption: string; text: string }): Promise<{ ok: boolean }>;
  notify?(title: string, body: string, link: string): Promise<{ ok: boolean }>; // desktop app 1.5.12+
};

/** Desktop app 1.5+ (themed "Uygulama" menu and title bar); older apps keep their native menu bar. */
export function desktopShell(): DesktopShell | null {
  const api = (window as unknown as { pywebview?: { api?: Partial<DesktopShell> } }).pywebview?.api;
  return api && typeof api.app_action === "function" ? (api as DesktopShell) : null;
}

/** pywebview injects its API a moment after the page loads; resolves null in a normal browser. */
export function whenDesktopShell(timeoutMs = 4000): Promise<DesktopShell | null> {
  if (desktopShell()) return Promise.resolve(desktopShell());
  return new Promise((resolve) => {
    const done = () => resolve(desktopShell());
    window.addEventListener("pywebviewready", done, { once: true });
    setTimeout(done, timeoutMs);
  });
}
