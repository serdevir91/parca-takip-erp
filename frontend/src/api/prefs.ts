// Screen settings (saved views, column layouts, theme) live in localStorage for speed and are mirrored to the
// server, so they follow the user to another device. On sign-in the server's copy wins.
import { api, getToken } from "./client";

const SYNCED = /^(dg\.|parts\.|erp_theme$)/;
const WAIT_MS = 800;
const timers = new Map<string, number>();

function localKeys(): string[] {
  try {
    return Object.keys(localStorage).filter((k) => SYNCED.test(k));
  } catch {
    return [];
  }
}

/** Call after writing `key` to localStorage. Dragging a column writes many times; one request goes out. */
export function savePref(key: string): void {
  if (!SYNCED.test(key)) return;
  window.clearTimeout(timers.get(key));
  timers.set(key, window.setTimeout(() => {
    timers.delete(key);
    let value: string | null = null;
    try {
      value = localStorage.getItem(key);
    } catch {
      /* storage unavailable */
    }
    if (!getToken()) return;
    const path = `/me/prefs/${encodeURIComponent(key)}`;
    void (value === null ? api.del(path) : api.put(path, { value })).catch(() => undefined);
  }, WAIT_MS));
}

/** Before the first screen opens, because grids read their layout once when they mount. */
export async function loadPrefs(): Promise<void> {
  let server: Record<string, string>;
  try {
    server = await api.get<Record<string, string>>("/me/prefs");
  } catch {
    return; // this device's own copy keeps working
  }
  if (!Object.keys(server).length) {
    localKeys().forEach(savePref); // first sign-in since the server keeps them
    return;
  }
  try {
    for (const k of localKeys()) if (!(k in server)) localStorage.removeItem(k);
    for (const [k, v] of Object.entries(server)) localStorage.setItem(k, v);
  } catch {
    return;
  }
  window.dispatchEvent(new Event("erp-prefs"));
}
