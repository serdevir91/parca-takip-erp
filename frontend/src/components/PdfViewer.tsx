import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ApiError, getToken } from "../api/client";
import { errText } from "./Toast";

// Bundled worker: no external resources (offline LAN).
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const STEP = 1.25;

/** Fetch a protected API file as raw bytes (JWT header). `path` is without the /api prefix. */
async function fetchBytes(path: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const token = getToken();
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal });
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "Dosya bulunamadı" : `Dosya alınamadı (${res.status})`);
  return res.arrayBuffer();
}

type Props = {
  /** API path of the PDF, e.g. `/drawings/12/file` */
  src: string;
  title: string;
  onClose: () => void;
  onDownload?: () => void;
};

/** Modal PDF viewer rendering one page at a time on a canvas with the locally bundled pdf.js. */
export default function PdfViewer({ src, title, onClose, onDownload }: Props) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [scale, setScale] = useState(1);
  const [fit, setFit] = useState(true);
  const [rendering, setRendering] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState(0);

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

  // Track available width for "fit width".
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxWidth(el.clientWidth));
    ro.observe(el);
    setBoxWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // Render the current page.
  useEffect(() => {
    if (!doc || !canvasRef.current) return;
    let cancelled = false;
    let rt: RenderTask | null = null;
    setRendering(true);
    doc.getPage(page).then((pg) => {
      if (cancelled) return;
      const base = pg.getViewport({ scale: 1 });
      let s = scale;
      if (fit && boxWidth > 0) {
        s = Math.min(MAX_SCALE, Math.max(MIN_SCALE, (boxWidth - 24) / base.width));
        if (Math.abs(s - scale) > 0.001) setScale(s);
      }
      const vp = pg.getViewport({ scale: s });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      canvas.width = Math.floor(vp.width * dpr);
      canvas.height = Math.floor(vp.height * dpr);
      canvas.style.width = `${Math.floor(vp.width)}px`;
      canvas.style.height = `${Math.floor(vp.height)}px`;
      rt = pg.render({ canvasContext: ctx, viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      rt.promise
        .then(() => { if (!cancelled) setRendering(false); })
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
    // scale is an output when fit=true; including it would re-render once more, harmless but wasteful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, page, fit, fit ? boxWidth : scale]);

  const pages = doc?.numPages ?? 0;
  const go = useCallback((n: number) => {
    if (!pages) return;
    const p = Math.min(pages, Math.max(1, n));
    setPage(p);
    setPageInput(String(p));
  }, [pages]);
  const zoom = useCallback((f: number) => {
    setFit(false);
    setScale((s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s * f)));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "PageDown") go(page + 1);
      else if (e.key === "ArrowLeft" || e.key === "PageUp") go(page - 1);
      else if (e.key === "+" || e.key === "=") zoom(STEP);
      else if (e.key === "-") zoom(1 / STEP);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, zoom, page, onClose]);

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal pdfv" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="row pdfv-bar">
          <b className="pdfv-title" title={title}>{title}</b>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="btn small" disabled={page <= 1} onClick={() => go(page - 1)} title="Önceki sayfa">‹</button>
          <input className="pdfv-page" value={pageInput} aria-label="Sayfa"
            onChange={(e) => setPageInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") go(Number(pageInput) || 1); }}
            onBlur={() => go(Number(pageInput) || page)} />
          <span className="muted">/ {pages ? pages.toLocaleString("tr-TR") : "–"}</span>
          <button className="btn small" disabled={!pages || page >= pages} onClick={() => go(page + 1)} title="Sonraki sayfa">›</button>
          <span className="muted" style={{ marginLeft: 8 }}>|</span>
          <button className="btn small" onClick={() => zoom(1 / STEP)} title="Uzaklaştır">−</button>
          <span className="muted pdfv-zoom">%{Math.round(scale * 100).toLocaleString("tr-TR")}</span>
          <button className="btn small" onClick={() => zoom(STEP)} title="Yakınlaştır">+</button>
          <button className={"btn small" + (fit ? " primary" : "")} onClick={() => setFit(true)}>Genişliğe sığdır</button>
          <button className="btn small" onClick={() => { setFit(false); setScale(1); }}>%100</button>
          {onDownload && <button className="btn small" onClick={onDownload}>İndir</button>}
          <button className="btn small" onClick={onClose} title="Kapat (Esc)">Kapat</button>
        </div>
        <div className="pdfv-body" ref={boxRef}>
          {error ? (
            <div className="error" style={{ padding: 16 }}>PDF açılamadı: {error}</div>
          ) : (
            <>
              {(!doc || rendering) && <div className="muted pdfv-loading">{doc ? "Sayfa çiziliyor…" : "PDF yükleniyor…"}</div>}
              <canvas ref={canvasRef} className="pdfv-canvas" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
