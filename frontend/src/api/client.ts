/** Thin fetch wrapper: session cookie, JSON, Turkish error messages from FastAPI `detail`. */
import { desktop, type DesktopFileRequest } from "./desktop";
import { mobileApp } from "./mobile";

const LEGACY_TOKEN_KEY = "erp_token";
/** The server refuses unsafe requests that ride on the cookie without it (backend/app/auth.py APP_HEADER). */
export const APP_HEADERS = { "X-Requested-With": "LabERP" };

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

let signedIn = false;
export const isSignedIn = () => signedIn;
export function setSignedIn(on: boolean): void {
  signedIn = on;
}

/** Versions before 1.5.10 kept the token in localStorage. It moves into the cookie once, then it is gone from there. */
export async function adoptLegacyToken(): Promise<void> {
  let token: string | null = null;
  try {
    token = localStorage.getItem(LEGACY_TOKEN_KEY);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    return;
  }
  if (!token) return;
  await fetch("/api/auth/session", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

function detailText(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e && typeof e === "object" && "msg" in e ? String(e.msg) : String(e))).join("; ");
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  return fallback;
}

export async function request<T = unknown>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", APP_HEADERS["X-Requested-With"]);
  let payload: BodyInit | undefined;
  if (body instanceof FormData || body instanceof URLSearchParams) payload = body;
  else if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { ...init, method, headers, body: payload }).catch((e) => {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Sunucuya ulaşılamadı");
  });
  if (res.status === 401 && !path.startsWith("/auth/login")) onUnauthorized();
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, detailText(data, `İstek başarısız (${res.status})`), data);
  return data as T;
}

export const api = {
  get: <T = unknown>(p: string) => request<T>("GET", p),
  post: <T = unknown>(p: string, b?: unknown) => request<T>("POST", p, b),
  put: <T = unknown>(p: string, b?: unknown) => request<T>("PUT", p, b),
  patch: <T = unknown>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  del: <T = unknown>(p: string) => request<T>("DELETE", p),
};

/** Upload with progress (fetch has no upload progress); used for BOM, drawings and xlsx files. */
export function upload<T = unknown>(path: string, form: FormData, onProgress?: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.setRequestHeader("X-Requested-With", APP_HEADERS["X-Requested-With"]);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let data: unknown = xhr.responseText;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status === 401) onUnauthorized();
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(new ApiError(xhr.status, detailText(data, `Yükleme başarısız (${xhr.status})`), data));
    };
    xhr.onerror = () => reject(new ApiError(0, "Sunucuya ulaşılamadı"));
    xhr.send(form);
  });
}

/** The native shells fetch files outside the web view, where the cookie is out of reach: each gets a short ticket. */
export async function fileTicket(path: string): Promise<string> {
  return (await api.post<{ token: string }>("/auth/file-ticket", { path })).token;
}

/** Download a protected file (Excel export, drawing) and save it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  if (desktop()) return desktopFile({ path, filename: fallbackName, action: "save" });
  const app = mobileApp();
  if (app) return app.download(`${location.origin}/api${path}`, fallbackName, await fileTicket(path));
  const res = await fetch(`/api${path}`);
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = undefined;
    }
    throw new ApiError(res.status, detailText(body, `İndirme başarısız (${res.status})`));
  }
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Fetch a protected binary (PDF, thumbnail) as an object URL. */
export async function blobUrl(path: string): Promise<string> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new ApiError(res.status, `Dosya alınamadı (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

/** Desktop app: the Python side fetches the file and saves it ("Farklı kaydet") or opens it. */
export async function desktopFile(req: Omit<DesktopFileRequest, "token">): Promise<void> {
  const d = desktop();
  if (!d) throw new ApiError(0, "Masaüstü uygulaması bulunamadı");
  const r = await d.file_request({ ...req, token: await fileTicket(req.path) });
  if (!r.ok && !r.cancelled) throw new ApiError(r.status ?? 0, r.error || "İndirme başarısız");
}
