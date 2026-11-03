import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";

type Info = { current: string; server?: string; feed?: { version: string; notes?: string; url?: string } };
type State = { info: Info; checking: boolean; available: boolean; check: (manual?: boolean) => Promise<void>; message: string };

const Ctx = createContext<State | null>(null);

/** Compare dotted versions numerically: returns >0 when a is newer than b. */
export function cmpVersion(a: string, b: string): number {
  const pa = a.split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  const pb = b.split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

export function UpdateProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<Info>({ current: __APP_VERSION__ });
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState("");

  const check = useCallback(async (manual = false) => {
    setChecking(true);
    try {
      const v = await api.get<{ version: string; update_feed_url?: string | null }>("/version");
      const next: Info = { current: __APP_VERSION__, server: v.version };
      if (v.update_feed_url) {
        try {
          const r = await fetch(v.update_feed_url, { cache: "no-store" });
          if (r.ok) next.feed = await r.json();
        } catch {
          /* feed unreachable on an offline LAN is normal */
        }
      }
      setInfo(next);
      const newer = cmpVersion(next.server ?? "0", next.current) > 0 || (next.feed && cmpVersion(next.feed.version, next.server ?? next.current) > 0);
      setMessage(newer ? "" : manual ? `Güncel sürümü kullanıyorsunuz (${next.server ?? next.current}).` : "");
    } catch (e) {
      if (manual) setMessage(`Güncelleme denetlenemedi: ${e instanceof Error ? e.message : e}`);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void check(false);
    const t = setInterval(() => void check(false), 30 * 60 * 1000);
    return () => clearInterval(t);
  }, [check]);

  const available = !!(
    (info.server && cmpVersion(info.server, info.current) > 0) ||
    (info.feed && cmpVersion(info.feed.version, info.server ?? info.current) > 0)
  );
  return <Ctx.Provider value={{ info, checking, available, check, message }}>{children}</Ctx.Provider>;
}

export const useUpdate = () => useContext(Ctx)!;

const RELOADED_KEY = "erp_update_reloaded";
const DISMISS_KEY = "erp_update_dismissed";

function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSession(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

/** Banner shown when the server (or the optional feed) has a newer version than the loaded bundle. */
export function UpdateBanner() {
  const { info, available } = useUpdate();
  const [dismissed, setDismissed] = useState(() => readSession(DISMISS_KEY));
  if (!available) return null;
  const serverNewer = info.server && cmpVersion(info.server, info.current) > 0;
  const key = `${info.current}>${serverNewer ? info.server : info.feed?.version}`;
  // Hidden for this session once dismissed, or when a reload already happened and the server still sends the
  // old page (its frontend files were not updated): reloading again would not help.
  if (dismissed === key || (serverNewer && readSession(RELOADED_KEY) === key)) return null;
  const close = () => {
    writeSession(DISMISS_KEY, key);
    setDismissed(key);
  };
  return (
    <div className="card update-banner" style={{ margin: "8px 16px 0", borderColor: "var(--accent)" }}>
      <div className="row">
        {serverNewer ? (
          <>
            <span>Sunucuda yeni sürüm var: <b>{info.server}</b> (açık olan: {info.current}).</span>
            <button
              className="btn primary small"
              onClick={() => {
                writeSession(RELOADED_KEY, key);
                location.reload();
              }}
            >
              Yenile
            </button>
          </>
        ) : (
          <>
            <span>Yeni sürüm yayımlandı: <b>{info.feed!.version}</b>. {info.feed!.notes}</span>
            {info.feed!.url && <a className="btn small" href={info.feed!.url} target="_blank" rel="noreferrer">İndir</a>}
            <span className="muted">Kurulum için README &gt; Güncelleme adımlarını izleyin.</span>
          </>
        )}
        <button className="btn small" style={{ marginLeft: "auto" }} onClick={close} aria-label="Kapat" title="Kapat">
          ✕
        </button>
      </div>
    </div>
  );
}
