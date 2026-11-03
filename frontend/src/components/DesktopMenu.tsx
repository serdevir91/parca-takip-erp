import { AppWindow } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { desktopShell, whenDesktopShell, type DesktopAction, type DesktopInfo } from "../api/desktop";
import { useTheme } from "../theme/theme";

/** "Uygulama" menu of the Windows desktop app, drawn in the app theme (replaces the white native menu bar).
 *  Also paints the window title bar in the theme colours. Renders nothing in a browser or on the phone. */
export function DesktopMenu() {
  const [ready, setReady] = useState(() => !!desktopShell());
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<DesktopInfo | null>(null);
  const [note, setNote] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const { mode } = useTheme();

  useEffect(() => {
    let live = true;
    void whenDesktopShell().then((s) => live && setReady(!!s));
    return () => { live = false; };
  }, []);

  useEffect(() => {
    const s = desktopShell();
    if (!ready || !s) return;
    const css = getComputedStyle(document.documentElement);
    const hex = (v: string) => (/^#[0-9a-f]{6}$/i.test(v.trim()) ? v.trim() : "");
    void s.set_theme({ dark: mode !== "light", caption: hex(css.getPropertyValue("--surface")), text: hex(css.getPropertyValue("--fg")) })
      .catch(() => undefined);
  }, [ready, mode]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!ready) return null;
  const s = desktopShell()!;
  const toggle = () => {
    setNote("");
    if (!open) void s.app_info().then(setInfo).catch(() => setInfo(null));
    setOpen(!open);
  };
  // In server mode the app itself asks before closing (the server stops with it)
  const run = (name: DesktopAction) => {
    void s.app_action(name).then((r) => (r.ok ? setOpen(false) : setNote(r.error ?? "İşlem yapılamadı")));
  };
  return (
    <div className="dg-menu-wrap desk-menu" ref={wrap}>
      <button className="icon-btn" onClick={toggle} aria-haspopup="menu" aria-expanded={open} title="Uygulama menüsü">
        <AppWindow size={17} />
        <span className="icon-btn-text">Uygulama</span>
      </button>
      {open && (
        <div className="dg-menu card desk-menu-pop" role="menu">
          <button role="menuitem" className="btn small" onClick={() => run("reload")}>Yeniden yükle</button>
          <button role="menuitem" className="btn small" onClick={() => run("settings")}>Bağlantı ayarları…</button>
          {info?.mode === "server" && (
            <button role="menuitem" className="btn small" onClick={() => run("open_data")}>Veri klasörünü aç</button>
          )}
          <button role="menuitem" className="btn small" onClick={() => run("update")}>Uygulama güncellemesini denetle</button>
          <div className="desk-menu-info muted">
            {info ? (
              <>
                <div>LAB ERP masaüstü {info.version}</div>
                <div>{info.mode === "server" ? "Sunucu (veriler bu bilgisayarda)" : `İstemci: ${info.base || "-"}`}</div>
                {info.mode === "server" && (
                  <div>Diğer cihazlar: {info.addresses.length ? info.addresses.join(", ") : "(ağ bağlantısı yok)"}</div>
                )}
              </>
            ) : "…"}
          </div>
          {note && <div className="error">{note}</div>}
          <button role="menuitem" className="btn small danger" onClick={() => run("quit")}>Uygulamayı kapat</button>
        </div>
      )}
    </div>
  );
}
