import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Download, Maximize, RotateCw, X, ZoomIn, ZoomOut } from "lucide-react";
import { blobUrl } from "../../api/client";
import { errText } from "../Toast";
import { useGestures } from "./gestures";

const MIN = 0.05;
const MAX = 16;
const STEP = 1.3;

export type NavProps = { index: number; count: number; prev: () => void; next: () => void };

type View = { s: number; x: number; y: number };

/** Full-screen image viewer: wheel/pinch zoom around the cursor, drag to pan, double click to zoom,
 *  rotate, fit. `src` is an API path (fetched with the login token) or a blob:/data: URL. */
export default function ImageLightbox({ src, title, caption, onClose, onDownload, nav, footer, actions }: {
  src: string; title: string; caption?: string; onClose: () => void; onDownload?: () => void;
  nav?: NavProps; footer?: ReactNode; actions?: ReactNode;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [rot, setRot] = useState(0);
  const [view, setView] = useState<View>({ s: 1, x: 0, y: 0 });
  const [fitted, setFitted] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setUrl(null); setErr(null); setSize(null); setRot(0); setFitted(true);
    if (/^(blob:|data:)/.test(src)) { setUrl(src); return; }
    let alive = true;
    let u: string | null = null;
    blobUrl(src).then((x) => { u = x; if (alive) setUrl(x); else URL.revokeObjectURL(x); })
      .catch((e) => alive && setErr(errText(e)));
    return () => { alive = false; if (u) URL.revokeObjectURL(u); };
  }, [src]);

  const dims = useCallback(() => {
    if (!size) return { w: 0, h: 0 };
    return rot % 2 ? { w: size.h, h: size.w } : { w: size.w, h: size.h };
  }, [size, rot]);

  const fit = useCallback(() => {
    const box = boxRef.current;
    const d = dims();
    if (!box || !d.w) return;
    const s = Math.min(MAX, Math.min((box.clientWidth - 24) / d.w, (box.clientHeight - 24) / d.h, 1));
    setView({ s, x: (box.clientWidth - d.w * s) / 2, y: (box.clientHeight - d.h * s) / 2 });
    setFitted(true);
  }, [dims]);

  useLayoutEffect(() => { if (fitted) fit(); }, [fitted, fit]);
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const ro = new ResizeObserver(() => { if (fitted) fit(); });
    ro.observe(box);
    return () => ro.disconnect();
  }, [fitted, fit]);

  const zoomAt = useCallback((f: number, cx: number, cy: number) => {
    setFitted(false);
    setView((v) => {
      const s = Math.min(MAX, Math.max(MIN, v.s * f));
      const k = s / v.s;
      return { s, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  }, []);
  const zoomCenter = (f: number) => {
    const box = boxRef.current;
    if (box) zoomAt(f, box.clientWidth / 2, box.clientHeight / 2);
  };
  const actual = () => {
    const box = boxRef.current;
    const d = dims();
    if (!box) return;
    setFitted(false);
    setView({ s: 1, x: (box.clientWidth - d.w) / 2, y: (box.clientHeight - d.h) / 2 });
  };

  useGestures(boxRef, {
    pan: (dx, dy) => { setFitted(false); setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy })); },
    zoom: zoomAt,
    dbl: (cx, cy) => (fitted ? zoomAt(2.5, cx, cy) : setFitted(true)),
  }, !!size);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && nav) nav.next();
      else if (e.key === "ArrowLeft" && nav) nav.prev();
      else if (e.key === "+" || e.key === "=") zoomCenter(STEP);
      else if (e.key === "-") zoomCenter(1 / STEP);
      else if (e.key === "0") setFitted(true);
      else if (e.key === "r" || e.key === "R") { setRot((r) => (r + 1) % 4); setFitted(true); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  const d = dims();
  const transform = size
    ? `translate(${view.x}px, ${view.y}px) scale(${view.s}) translate(${d.w / 2}px, ${d.h / 2}px) rotate(${rot * 90}deg) translate(${-size.w / 2}px, ${-size.h / 2}px)`
    : undefined;

  return (
    <div className="modal-back viewer-back" onClick={onClose}>
      <div className="modal pdfv viewer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="row pdfv-bar">
          <div className="viewer-title">
            <b className="pdfv-title" title={title}>{title}</b>
            {caption && <span className="muted">{caption}</span>}
          </div>
          <span style={{ flex: 1 }} />
          {nav && nav.count > 1 && <>
            <button className="btn small" onClick={nav.prev} title="Önceki (←)"><ChevronLeft size={16} /></button>
            <span className="muted">{nav.index + 1} / {nav.count}</span>
            <button className="btn small" onClick={nav.next} title="Sonraki (→)"><ChevronRight size={16} /></button>
            <span className="muted">|</span>
          </>}
          <button className="btn small" onClick={() => zoomCenter(1 / STEP)} title="Uzaklaştır (−)"><ZoomOut size={16} /></button>
          <span className="muted pdfv-zoom">%{Math.round(view.s * 100).toLocaleString("tr-TR")}</span>
          <button className="btn small" onClick={() => zoomCenter(STEP)} title="Yakınlaştır (+)"><ZoomIn size={16} /></button>
          <button className={"btn small" + (fitted ? " primary" : "")} onClick={() => setFitted(true)} title="Ekrana sığdır (0)"><Maximize size={16} /></button>
          <button className="btn small" onClick={actual}>%100</button>
          <button className="btn small" onClick={() => { setRot((r) => (r + 1) % 4); setFitted(true); }} title="Döndür (R)"><RotateCw size={16} /></button>
          {actions}
          {onDownload && <button className="btn small" onClick={onDownload} title="İndir"><Download size={16} /></button>}
          <button className="btn small" onClick={onClose} title="Kapat (Esc)"><X size={16} /></button>
        </div>
        <div className="viewer-stage" ref={boxRef}>
          {err ? <div className="error" style={{ padding: 16 }}>{err}</div>
            : !url ? <div className="muted pdfv-loading">Yükleniyor…</div>
            : <img src={url} alt={title} draggable={false} className="viewer-img"
                style={{ transform, visibility: size ? "visible" : "hidden" }}
                onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                onError={() => setErr("Resim açılamadı (biçim desteklenmiyor olabilir). İndirip açabilirsiniz.")} />}
          {nav && nav.count > 1 && <>
            <button className="viewer-arrow left" onClick={nav.prev} aria-label="Önceki"><ChevronLeft size={28} /></button>
            <button className="viewer-arrow right" onClick={nav.next} aria-label="Sonraki"><ChevronRight size={28} /></button>
          </>}
          <div className="viewer-hint">Tekerlek veya iki parmak: yakınlaştır · Sürükle: kaydır · Çift tık: büyüt</div>
        </div>
        {footer}
      </div>
    </div>
  );
}
