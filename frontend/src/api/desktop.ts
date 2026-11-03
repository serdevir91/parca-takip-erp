// Bridge to the Windows desktop app (desktop/parca_takip_desktop.py). The app exposes its Python API as
// window.pywebview.api; in a normal browser desktop() is null and the web code paths are used.

export type DesktopFileRequest = {
  path: string; // API path without the /api prefix
  token: string | null;
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
