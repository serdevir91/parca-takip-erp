/** Thin fetch wrapper: JWT header, JSON, Turkish error messages from FastAPI `detail`. */
import { desktop, type DesktopFileRequest } from "./desktop";
import { mobileApp } from "./mobile";

const TOKEN_KEY = "erp_token";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
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
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
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
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
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

/** Download a protected file (Excel export, drawing) using the JWT and save it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  if (desktop()) return desktopFile({ path, token, filename: fallbackName, action: "save" });
  const app = mobileApp();
  if (app) return app.download(`${location.origin}/api${path}`, fallbackName, token ?? "");
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
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
  const token = getToken();
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `Dosya alınamadı (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

/** Desktop app: the Python side fetches the file and saves it ("Farklı kaydet") or opens it. */
export async function desktopFile(req: DesktopFileRequest): Promise<void> {
  const d = desktop();
  if (!d) throw new ApiError(0, "Masaüstü uygulaması bulunamadı");
  const r = await d.file_request(req);
  if (!r.ok && !r.cancelled) throw new ApiError(r.status ?? 0, r.error || "İndirme başarısız");
}
