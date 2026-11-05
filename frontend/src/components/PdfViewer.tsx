import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Download, Maximize, X, ZoomIn, ZoomOut } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ApiError } from "../api/client";
import { errText } from "./Toast";
import { useGestures } from "./viewer/gestures";
import type { NavProps } from "./viewer/ImageLightbox";

// Bundled worker: no external resources (offline LAN).
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const STEP = 1.25;

/** Fetch a protected API file as raw bytes. `path` is without the /api prefix. */
async function fetchBytes(path: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const res = await fetch(`/api${path}`, { signal });
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "Dosya bulunamadı" : `Dosya alınamadı (${res.status})`);
  return res.arrayBuffer();
}

type Props = {
  /** API path of the PDF, e.g. `/drawings/12/file` */
  src: string;
  title: string;
  onClose: () => void;
  onDownload?: () => void;
  /** Previous/next file when opened from a gallery */
  nav?: NavProps;
  footer?: ReactNode;
  actions?: ReactNode;
};

/** Modal PDF viewer with the locally bundled pdf.js. Wheel or pinch zooms around the cursor, dragging
 *  pans, double click toggles fit/zoom. Zooming first stretches the current bitmap (instant), then
 *  re-renders sharply off screen so the page never flashes blank. */
export default function PdfViewer({ src, title, onClose, onDownload, nav, footer, actions }: Props) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [scale, setScale] = useState(1);
  const [renderScale, setRenderScale] = useState(0);
  const [fit, setFit] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [base, setBase] = useState<{ w: number; h: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  // Page point (PDF units) that must stay under the cursor (cx, cy) after the next zoom
  const anchor = useRef<{ px: number; py: number; cx: number; cy: number } | null>(null);
  const scaleRef = useRef(scale);
  scaleRef.current = scale;

  // Load the document; destroy it on close / source change.
  useEffect(() => {
    const ctl = new AbortController();
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    let loaded: PDFDocumentProxy | null = null;
    setDoc(null);
    setError(null);
    setPage(1);
    setPageInput("1");
    setFit(true);
    setBase(null);
    fetchBytes(src, ctl.signal)
      .then((buf) => {
        if (ctl.signal.aborted) return;
        task = pdfjs.getDocument({ data: new Uint8Array(buf), isEvalSupported: false });
        return task.promise.then((d) => {
          if (ctl.signal.aborted) {
            void d.destroy();
            return;
          }
          loaded = d;
          setDoc(d);
        });
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        const name = e && typeof e === "object" && "name" in e ? String((e as { name: unknown }).name) : "";
        setError(name === "InvalidPDFException" ? "Dosya geçerli bir PDF değil." : errText(e));
      });
    return () => {
      ctl.abort();
      if (loaded) void loaded.destroy();
      else if (task) void task.destroy();
    };
  }, [src]);

  // Track the available area for "fit".
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Page size at scale 1.
  useEffect(() => {
    if (!doc) return;
    let alive = true;
    doc.getPage(page).then((pg) => {
      if (!alive) return;
      const v = pg.getViewport({ scale: 1 });
      setBase({ w: v.width, h: v.height });
    }).catch((e: unknown) => alive && setError(errText(e)));
    return () => { alive = false; };
  }, [doc, page]);

  // Fit the whole page (drawings are usually landscape sheets: fit both sides, not only the width).
  useEffect(() => {
    if (!fit || !base || box.w <= 0) return;
    const s = Math.min((box.w - 24) / base.w, (box.h - 24) / base.h);
    setScale(Math.min(MAX_SCALE, Math.max(MIN_SCALE, s)));
  }, [fit, base, box]);

  // Show the new size at once (CSS stretch) and keep the anchor point under the cursor.
  useLayoutEffect(() => {
    const c = canvasRef.current;
    const el = boxRef.current;
    if (!c || !el || !base) return;
    c.style.width = `${Math.floor(base.w * scale)}px`;
    c.style.height = `${Math.floor(base.h * scale)}px`;
    const a = anchor.current;
    anchor.current = null;
    if (a) {
      const cr = c.getBoundingClientRect();
      const br = el.getBoundingClientRect();
      el.scrollLeft += cr.left - br.left + a.px * scale - a.cx;
      el.scrollTop += cr.top - br.top + a.py * scale - a.cy;
    }
  }, [scale, base]);

  // Sharp re-render a moment after zooming stops.
  useEffect(() => {
    const t = setTimeout(() => setRenderScale(scale), 160);
    return () => clearTimeout(t);
  }, [scale]);

  useEffect(() => {
    if (!doc || !renderScale || !canvasRef.current) return;
    let cancelled = false;
    let rt: RenderTask | null = null;
    setRendering(true);
    doc.getPage(page).then((pg) => {
      if (cancelled) return;
      const vp = pg.getViewport({ scale: renderScale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      // Browsers refuse very large canvases; cap the bitmap, CSS still shows the requested size
      const k = Math.min(1, 12000 / Math.max(vp.width * dpr, vp.height * dpr));
      const off = document.createElement("canvas");
      off.width = Math.floor(vp.width * dpr * k);
      off.height = Math.floor(vp.height * dpr * k);
      const octx = off.getContext("2d");
      if (!octx) return;
      const t = dpr * k;
      rt = pg.render({ canvasContext: octx, viewport: vp, transform: t !== 1 ? [t, 0, 0, t, 0, 0] : undefined });
      rt.promise
        .then(() => {
          const c = canvasRef.current;
          if (cancelled || !c) return;
          c.width = off.width;
          c.height = off.height;
          c.getContext("2d")?.drawImage(off, 0, 0);
          setRendering(false);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          const name = e && typeof e === "object" && "name" in e ? String((e as { name: unknown }).name) : "";
          if (name !== "RenderingCancelledException") setError(errText(e));
          setRendering(false);
        });
    }).catch((e: unknown) => { if (!cancelled) { setError(errText(e)); setRendering(false); } });
    return () => {
      cancelled = true;
      rt?.cancel();
    };
  }, [doc, page, renderScale]);

  const pages = doc?.numPages ?? 0;
  const go = useCallback((n: number) => {
    if (!pages) return;
    const p = Math.min(pages, Math.max(1, n));
    setPage(p);
    setPageInput(String(p));
  }, [pages]);

  const zoomAt = useCallback((f: number, cx: number, cy: number) => {
    const c = canvasRef.current;
    const el = boxRef.current;
    if (!c || !el) return;
    const s = scaleRef.current;
    const s2 = Math.min(MAX_SCALE, Math.max(MIN_SCALE, s * f));
    if (Math.abs(s2 - s) < 1e-4) return;
    const cr = c.getBoundingClientRect();
    const br = el.getBoundingClientRect();
    anchor.current = { px: (cx - (cr.left - br.left)) / s, py: (cy - (cr.top - br.top)) / s, cx, cy };
    setFit(false);
    setScale(s2);
  }, []);
  const zoom = useCallback((f: number) => {
    const el = boxRef.current;
    if (el) zoomAt(f, el.clientWidth / 2, el.clientHeight / 2);
  }, [zoomAt]);

  useGestures(boxRef, {
    pan: (dx, dy) => { const el = boxRef.current; if (el) { el.scrollLeft -= dx; el.scrollTop -= dy; } },
    zoom: zoomAt,
    dbl: (cx, cy) => (fit ? zoomAt(2.5, cx, cy) : setFit(true)),
  }, !!doc);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "PageDown") {
        if (page < pages || !nav) go(page + 1); else nav.next();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        if (page > 1 || !nav) go(page - 1); else nav.prev();
      } else if (e.key === "+" || e.key === "=") zoom(STEP);
      else if (e.key === "-") zoom(1 / STEP);
      else if (e.key === "0") setFit(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, zoom, page, pages, nav, onClose]);

  return (
    <div className="modal-back viewer-back" onClick={onClose}>
      <div className="modal pdfv viewer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="row pdfv-bar">
          <b className="pdfv-title" title={title}>{title}</b>
          <span className="spacer" style={{ flex: 1 }} />
          {nav && nav.count > 1 && <>
            <button className="btn small" onClick={nav.prev} title="Önceki dosya"><ChevronLeft size={16} /></button>
            <span className="muted">Dosya {nav.index + 1} / {nav.count}</span>
            <button className="btn small" onClick={nav.next} title="Sonraki dosya"><ChevronRight size={16} /></button>
            <span className="muted">|</span>
          </>}
          {pages > 1 && <>
            <button className="btn small" disabled={page <= 1} onClick={() => go(page - 1)} title="Önceki sayfa">‹</button>
            <input className="pdfv-page" value={pageInput} aria-label="Sayfa"
              onChange={(e) => setPageInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") go(Number(pageInput) || 1); }}
              onBlur={() => go(Number(pageInput) || page)} />
            <span className="muted">/ {pages.toLocaleString("tr-TR")}</span>
            <button className="btn small" disabled={page >= pages} onClick={() => go(page + 1)} title="Sonraki sayfa">›</button>
            <span className="muted">|</span>
          </>}
          <button className="btn small" onClick={() => zoom(1 / STEP)} title="Uzaklaştır (−)"><ZoomOut size={16} /></button>
          <span className="muted pdfv-zoom">%{Math.round(scale * 100).toLocaleString("tr-TR")}</span>
          <button className="btn small" onClick={() => zoom(STEP)} title="Yakınlaştır (+)"><ZoomIn size={16} /></button>
          <button className={"btn small" + (fit ? " primary" : "")} onClick={() => setFit(true)} title="Sayfayı sığdır (0)"><Maximize size={16} /></button>
          <button className="btn small" onClick={() => { const el = boxRef.current; if (el) zoomAt(1 / scaleRef.current, el.clientWidth / 2, el.clientHeight / 2); }}>%100</button>
          {actions}
          {onDownload && <button className="btn small" onClick={onDownload} title="İndir"><Download size={16} /></button>}
          <button className="btn small" onClick={onClose} title="Kapat (Esc)"><X size={16} /></button>
        </div>
        <div className="viewer-wrap">
        <div className="pdfv-body pan-zoom" ref={boxRef}>
          {error ? (
            <div className="error" style={{ padding: 16 }}>PDF açılamadı: {error}</div>
          ) : (
            <>
              {(!doc || rendering) && <div className="muted pdfv-loading">{doc ? "Sayfa çiziliyor…" : "PDF yükleniyor…"}</div>}
              <canvas ref={canvasRef} className="pdfv-canvas" />
            </>
          )}
        </div>
          {nav && nav.count > 1 && <>
            <button className="viewer-arrow left" onClick={nav.prev} aria-label="Önceki"><ChevronLeft size={28} /></button>
            <button className="viewer-arrow right" onClick={nav.next} aria-label="Sonraki"><ChevronRight size={28} /></button>
          </>}
        </div>
        {footer}
      </div>
    </div>
  );
}
