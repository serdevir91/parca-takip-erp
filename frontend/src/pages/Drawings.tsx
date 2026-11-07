import { useSearchParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { Page, useProject } from "../components/Layout";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import PrintMenu from "../components/PrintMenu";
import PreviewThumb from "../components/viewer/Thumb";
import Viewer, { type ViewItem } from "../components/viewer/Viewer";
import { errText, useToast } from "../components/Toast";
import { api, ApiError, APP_HEADERS, blobUrl, desktopFile, download, upload } from "../api/client";
import { desktop } from "../api/desktop";
import { useAuth } from "../api/auth";
import { LayoutGrid, List } from "lucide-react";
import { LOCALE, tx } from "../api/i18n";

// ---------- API types (backend/app/services/drawings.py drawing_out / project_listing / _result) ----------
type Suggestion = { part_no: string; score: number };
type DrawingOut = {
  id: number; filename: string; base_name: string; ext: string; rev: string | null;
  part_no: string | null; match_via: string | null; current_version: number; version_count: number;
  size: number | null; uploaded_by: string; uploaded_at: string | null; bom_rev: string | null;
  rev_mismatch: boolean; inline: boolean; has_thumb: boolean;
  suggestions?: Suggestion[];
};
type VersionOut = { id: number; version_no: number; size: number; sha256: string; uploaded_by: string; uploaded_at: string | null };
type DrawingDetail = DrawingOut & { versions: VersionOut[] };
type Listing = {
  items: DrawingOut[];
  unmatched: DrawingOut[];
  no_drawing: string[];
  counts: { matched: number; parts_with_drawing: number; unmatched: number; rev_mismatch: number; no_drawing: number };
};
type UploadResult = {
  filename: string; status: "created" | "new_version" | "unchanged" | "rejected"; error?: string; zip?: string;
  drawing_id?: number; version_no?: number; part_no?: string | null; via?: string | null; rev?: string | null;
  bom_rev?: string | null; rev_mismatch?: boolean; suggestions?: Suggestion[];
};
type UploadResponse = { results: UploadResult[] };
type PartLite = { part_no: string; rev: string | null; main_group: string | null; is_assembly: boolean };

// ---------- grid row ----------
type Kind = "matched" | "unmatched" | "no_drawing";
type Row = {
  key: string; kind: Kind; d: DrawingOut | null;
  part_no: string; filename: string; ext: string; rev: string; bom_rev: string; rev_state: string;
  versions: number | null; uploaded_by: string; uploaded_at: string; main_group: string; via: string; suggestion: string;
};
type Filter = "all" | "matched" | "unmatched" | "rev" | "no_drawing";
type Opened = { items: ViewItem[]; start: number };

const IMAGE_EXTS_OR_PDF = new Set(["pdf", "png", "jpg", "jpeg"]);
const dwItem = (d: DrawingOut): ViewItem => ({
  key: d.id, name: d.filename, path: `/drawings/${d.id}/file`, thumb: d.has_thumb ? `/drawings/${d.id}/thumb` : undefined,
  kind: d.ext === "pdf" ? "pdf" : "image",
  caption: [d.part_no, d.rev ? tx("Rev {0}", d.rev) : ""].filter(Boolean).join(" · "),
});
const VIA_LABELS: Record<string, string> = { exact: tx("Otomatik"), normalized: tx("Otomatik (normalize)"), alias: tx("Alias"), manual: tx("Elle") };
const STATUS_LABELS: Record<UploadResult["status"], string> = {
  created: tx("Yeni"), new_version: tx("Yeni sürüm"), unchanged: tx("Değişmedi"), rejected: tx("Reddedildi"),
};
const ZIP_MODES = [
  { v: "pdf", l: tx("Sadece PDF") }, { v: "pdf_dwg", l: tx("PDF + DWG") }, { v: "all", l: tx("Tüm dosyalar") },
];
const UPLOAD_CONCURRENCY = 3;
const THUMB_CONCURRENCY = 4;
const ROW_H = 44;

const fmtDate = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" }) : "");
function fmtSize(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${n.toLocaleString(LOCALE)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 })} KB`;
  return `${(n / 1024 / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 })} MB`;
}
const viaLabel = (v: string | null | undefined) => (v ? VIA_LABELS[v] ?? v : "");

/** POST that returns a file (zip); `download()` only does GET. */
async function postDownload(path: string, body: unknown, fallbackName: string): Promise<void> {
  if (desktop()) return desktopFile({ path, filename: fallbackName, action: "save", method: "POST", body });
  const headers: Record<string, string> = { "Content-Type": "application/json", ...APP_HEADERS };
  const res = await fetch(`/api${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) {
    let msg = tx("İndirme başarısız ({0})", res.status);
    try {
      const j = await res.json();
      if (j && typeof j.detail === "string") msg = j.detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = m ? decodeURIComponent(m[1]) : fallbackName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ---------- thumbnail cache: object URLs shared by rows, limited fetch concurrency, revoked on page unmount ----------
class ThumbCache {
  private urls = new Map<string, string | null>();
  private pending = new Map<string, Promise<string | null>>();
  private queue: (() => void)[] = [];
  private active = 0;
  private disposed = false;

  peek(key: string): string | null | undefined {
    return this.urls.get(key);
  }

  get(key: string, path: string): Promise<string | null> {
    if (this.urls.has(key)) return Promise.resolve(this.urls.get(key)!);
    const p0 = this.pending.get(key);
    if (p0) return p0;
    const p = new Promise<string | null>((resolve) => {
      const run = () => {
        this.active++;
        blobUrl(path)
          .then((u) => {
            if (this.disposed) { URL.revokeObjectURL(u); resolve(null); return; }
            this.urls.set(key, u);
            resolve(u);
          })
          .catch(() => resolve(null))   // not remembered: the row asks again the next time it is shown
          .finally(() => {
            this.active--;
            this.pending.delete(key);
            this.queue.shift()?.();
          });
      };
      if (this.active < THUMB_CONCURRENCY) run();
      else this.queue.push(run);
    });
    this.pending.set(key, p);
    return p;
  }

  dispose(): void {
    this.disposed = true;
    this.queue = [];
    for (const u of this.urls.values()) if (u) URL.revokeObjectURL(u);
    this.urls.clear();
  }
}

function Thumb({ d, cache, onOpen }: { d: DrawingOut; cache: ThumbCache; onOpen: () => void }) {
  const key = `${d.id}:${d.current_version}`;
  const [url, setUrl] = useState<string | null | undefined>(() => cache.peek(key));
  useEffect(() => {
    if (url !== undefined) return;
    let alive = true;
    // Small delay so fast scrolling does not fire a request for every row passing by.
    const t = setTimeout(() => {
      void cache.get(key, `/drawings/${d.id}/thumb`).then((u) => { if (alive) setUrl(u); });
    }, 120);
    return () => { alive = false; clearTimeout(t); };
  }, [key, d.id, cache, url]);
  if (!url) return <span className="dw-thumb dw-thumb-empty">{url === null ? "—" : "…"}</span>;
  return (
    <img className="dw-thumb" src={url} alt="" loading="lazy"
      onClick={(e) => { e.stopPropagation(); onOpen(); }} title={tx("Önizleme – açmak için tıklayın")} />
  );
}

// ---------- upload queue ----------
type QItem = { id: number; file: File; pct: number; state: "waiting" | "uploading" | "done" | "error"; error?: string; results?: UploadResult[] };
let qSeq = 0;

const fileKey = (f: File) => `${f.webkitRelativePath || f.name}|${f.size}|${f.lastModified}`;
const isJunk = (name: string) => name.startsWith(".") || /^(thumbs\.db|desktop\.ini)$/i.test(name);

/** Collect files from a drop, recursing into dropped folders when the browser supports it. */
async function filesFromDrop(dt: DataTransfer): Promise<File[]> {
  const entries = [...dt.items].map((it) => (it.kind === "file" ? it.webkitGetAsEntry?.() ?? null : null));
  if (!entries.some((e) => e?.isDirectory)) return [...dt.files];
  const out: File[] = [];
  const walk = async (e: FileSystemEntry): Promise<void> => {
    if (e.isFile) {
      const f = await new Promise<File>((res, rej) => (e as FileSystemFileEntry).file(res, rej));
      if (!isJunk(f.name)) out.push(f);
    } else if (e.isDirectory) {
      const reader = (e as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const c of batch) await walk(c);
      }
    }
  };
  for (const e of entries) if (e) await walk(e);
  return out;
}

function UploadPanel({ pid, onFinished }: { pid: number; onFinished: () => void }) {
  const toast = useToast();
  const [queue, setQueue] = useState<QItem[]>([]);
  const [staged, setStaged] = useState<File[]>([]);
  const [skipped, setSkipped] = useState<Set<File>>(new Set());
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const lastStaged = useRef<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  useEffect(() => {
    // `webkitdirectory` is not in React's typings.
    dirRef.current?.setAttribute("webkitdirectory", "");
  }, []);

  const patch = (id: number, p: Partial<QItem>) => {
    if (mounted.current) setQueue((q) => q.map((x) => (x.id === id ? { ...x, ...p } : x)));
  };

  const stage = (files: File[]) => {
    const list = files.filter((f) => !isJunk(f.name));
    if (!list.length) return;
    setQueue([]);
    setStaged((cur) => {
      const seen = new Set(cur.map(fileKey));
      return [...cur, ...list.filter((f) => !seen.has(fileKey(f)))];
    });
  };
  const toggleStaged = (i: number, shift: boolean) => {
    const on = skipped.has(staged[i]);
    const from = shift && lastStaged.current !== null ? Math.min(lastStaged.current, i) : i;
    const to = shift && lastStaged.current !== null ? Math.max(lastStaged.current, i) : i;
    lastStaged.current = i;
    const next = new Set(skipped);
    for (const f of staged.slice(from, to + 1)) {
      if (on) next.delete(f); else next.add(f);
    }
    setSkipped(next);
  };
  const clearStaged = () => { setStaged([]); setSkipped(new Set()); lastStaged.current = null; };
  const pickedCount = staged.length - skipped.size;

  const start = useCallback(async (list: File[]) => {
    if (!list.length) return;
    const items: QItem[] = list.map((file) => ({ id: ++qSeq, file, pct: 0, state: "waiting" }));
    setQueue(items);
    setBusy(true);
    let next = 0;
    const worker = async () => {
      while (next < items.length) {
        const it = items[next++];
        patch(it.id, { state: "uploading" });
        const fd = new FormData();
        fd.append("files", it.file, it.file.name);
        try {
          const r = await upload<UploadResponse>(`/projects/${pid}/drawings`, fd, (pct) => patch(it.id, { pct }));
          patch(it.id, { state: "done", pct: 100, results: r.results });
        } catch (e) {
          patch(it.id, { state: "error", error: errText(e) });
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, items.length) }, worker));
    if (mounted.current) setBusy(false);
    toast(tx("{0} dosyanın yüklemesi tamamlandı", items.length.toLocaleString(LOCALE)));
    onFinished();
  }, [pid, onFinished, toast]);

  const results = useMemo(() => queue.flatMap((q) => q.results ?? []), [queue]);
  const sum = useMemo(() => {
    const ok = results.filter((r) => r.status !== "rejected");
    return {
      stored: ok.filter((r) => r.status === "created" || r.status === "new_version").length,
      unchanged: ok.filter((r) => r.status === "unchanged").length,
      matched: ok.filter((r) => r.part_no).length,
      unmatched: ok.filter((r) => !r.part_no).length,
      rev: ok.filter((r) => r.rev_mismatch).length,
      rejected: results.length - ok.length + queue.filter((q) => q.state === "error").length,
    };
  }, [results, queue]);
  // Problems first; cap rendered rows (a zip may contain thousands of files).
  const shownResults = useMemo(() => {
    const rank = (r: UploadResult) => (r.status === "rejected" ? 0 : !r.part_no ? 1 : r.rev_mismatch ? 2 : 3);
    return [...results].sort((a, b) => rank(a) - rank(b)).slice(0, 1000);
  }, [results]);
  const done = queue.filter((q) => q.state === "done" || q.state === "error").length;
  const totalPct = queue.length ? Math.round(queue.reduce((s, q) => s + (q.state === "done" || q.state === "error" ? 100 : q.pct), 0) / queue.length) : 0;

  return (
    <div className="card dw-upload">
      <div
        className={"dw-drop" + (drag ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (busy) return;
          void filesFromDrop(e.dataTransfer).then(stage).catch((er) => toast(errText(er), true));
        }}
      >
        <div><b>{tx("Teknik resimleri buraya sürükleyip bırakın")}</b></div>
        <div className="muted">{tx("PDF, DWG, DXF, SLDDRW, SLDPRT, SLDASM, STEP/STP, PNG/JPG veya .zip · klasör de bırakılabilir")}</div>
        <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
          <button className="btn primary" disabled={busy} onClick={() => fileRef.current?.click()}>{tx("Dosya seç")}</button>
          <button className="btn" disabled={busy} onClick={() => dirRef.current?.click()}>{tx("Klasör seç")}</button>
        </div>
        <input ref={fileRef} type="file" multiple hidden
          accept=".pdf,.dwg,.dxf,.slddrw,.sldprt,.sldasm,.step,.stp,.png,.jpg,.jpeg,.zip"
          onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; stage(f); }} />
        <input ref={dirRef} type="file" multiple hidden
          onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; stage(f); }} />
      </div>

      {staged.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="row">
            <label className="dw-pick-all">
              <input type="checkbox" checked={pickedCount === staged.length}
                ref={(el) => { if (el) el.indeterminate = pickedCount > 0 && pickedCount < staged.length; }}
                onChange={() => setSkipped(pickedCount === staged.length ? new Set(staged) : new Set())} />
              {tx("Tümünü seç")}{" "}<span className="muted">({staged.length.toLocaleString(LOCALE)})</span>
            </label>
            <span className="spacer" style={{ flex: 1 }} />
            <button className="btn small" onClick={clearStaged}>{tx("Vazgeç")}</button>
            <button className="btn small primary" disabled={!pickedCount}
              onClick={() => { const list = staged.filter((f) => !skipped.has(f)); clearStaged(); void start(list); }}>
              {tx("Seçilenleri yükle ({0})", pickedCount.toLocaleString(LOCALE))}
            </button>
          </div>
          <div className="dw-queue">
            {staged.map((f, i) => (
              <label key={fileKey(f)} className="dw-qrow">
                <input type="checkbox" checked={!skipped.has(f)} onChange={() => {}}
                  onClick={(e) => toggleStaged(i, e.shiftKey)} />
                <span className="dw-qname" title={f.name}>{f.name}</span>
                <span className="muted">{fmtSize(f.size)}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {queue.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="row">
            <b>{busy ? tx("Yükleniyor") : tx("Yükleme tamamlandı")}</b>
            <span className="muted">{tx("{0} / {1} dosya", done.toLocaleString(LOCALE), queue.length.toLocaleString(LOCALE))}</span>
            <div className="progress" style={{ flex: 1, minWidth: 120 }}><div style={{ width: `${totalPct}%` }} /></div>
            {!busy && <button className="btn small" onClick={() => setQueue([])}>{tx("Temizle")}</button>}
          </div>
          <div className="dw-queue">
            {queue.map((q) => (
              <div key={q.id} className="dw-qrow">
                <span className="dw-qname" title={q.file.name}>{q.file.name}</span>
                <span className="muted">{fmtSize(q.file.size)}</span>
                {q.state === "error" ? (
                  <span className="badge err" title={q.error}>{tx("Hata: {0}", q.error)}</span>
                ) : q.state === "waiting" ? (
                  <span className="muted">{tx("Sırada")}</span>
                ) : (
                  <div className="progress" style={{ width: 120 }}><div style={{ width: `${q.pct}%` }} /></div>
                )}
              </div>
            ))}
          </div>
          {results.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 10 }}>
                <span className="badge">{tx("Kaydedilen: {0}", sum.stored.toLocaleString(LOCALE))}</span>
                <span className="badge">{tx("Değişmeyen: {0}", sum.unchanged.toLocaleString(LOCALE))}</span>
                <span className="badge new">{tx("Eşleşen: {0}", sum.matched.toLocaleString(LOCALE))}</span>
                <span className={"badge" + (sum.unmatched ? " warn" : "")}>{tx("Eşleşmeyen: {0}", sum.unmatched.toLocaleString(LOCALE))}</span>
                <span className={"badge" + (sum.rev ? " warn" : "")}>{tx("Revizyon uyumsuz: {0}", sum.rev.toLocaleString(LOCALE))}</span>
                <span className={"badge" + (sum.rejected ? " err" : "")}>{tx("Reddedilen: {0}", sum.rejected.toLocaleString(LOCALE))}</span>
              </div>
              <div className="dw-results">
                <table className="simple">
                  <thead>
                    <tr><th>{tx("Dosya")}</th><th>{tx("Durum")}</th><th>{tx("Parça No")}</th><th>{tx("Rev (resim / BOM)")}</th><th>{tx("Not")}</th></tr>
                  </thead>
                  <tbody>
                    {shownResults.map((r, i) => (
                      <tr key={i}>
                        <td>{r.filename}{r.zip && <span className="muted"> ({r.zip})</span>}</td>
                        <td>
                          <span className={"badge" + (r.status === "rejected" ? " err" : r.status === "unchanged" ? "" : " new")}>{STATUS_LABELS[r.status] ?? r.status}</span>
                        </td>
                        <td>{r.part_no ?? (r.status !== "rejected" && <span className="badge warn">{tx("Eşleşmedi")}</span>)}</td>
                        <td>
                          {r.status !== "rejected" && <>{r.rev || "—"} / {r.bom_rev || "—"}</>}
                          {r.rev_mismatch && <span className="badge warn" style={{ marginLeft: 6 }}>{tx("Uyumsuz")}</span>}
                        </td>
                        <td className="muted">
                          {r.error || (r.suggestions?.length ? tx("Öneri: {0}", r.suggestions.slice(0, 3).map((s) => s.part_no).join(", ")) : viaLabel(r.via))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {results.length > shownResults.length && (
                  <div className="muted" style={{ padding: 6 }}>
                    {tx("İlk {0} sonuç gösteriliyor (toplam {1}).", shownResults.length.toLocaleString(LOCALE), results.length.toLocaleString(LOCALE))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------- image modal ----------
// ---------- detail drawer ----------
function DetailDrawer({ d0, partNos, canDesign, onClose, onOpen, onChanged }: {
  d0: DrawingOut; partNos: string[]; canDesign: boolean; onClose: () => void;
  onOpen: (d: DrawingOut, version?: VersionOut) => void; onChanged: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["drawing", d0.id], queryFn: () => api.get<DrawingDetail>(`/drawings/${d0.id}`) });
  const d = q.data ?? d0;
  const [pno, setPno] = useState(d0.part_no ?? "");
  useEffect(() => { setPno(q.data?.part_no ?? d0.part_no ?? ""); }, [q.data?.part_no, d0.part_no]);

  const assign = useMutation({
    mutationFn: (part_no: string | null) => api.post<DrawingDetail>(`/drawings/${d0.id}/assign`, { part_no }),
    onSuccess: (r) => {
      qc.setQueryData(["drawing", d0.id], r);
      toast(r.part_no ? tx("Resim {0} parçasına eşleştirildi", r.part_no) : tx("Eşleşme kaldırıldı"));
      onChanged();
    },
    onError: (e) => toast(errText(e), true),
  });
  const delVersion = useMutation({
    mutationFn: (vid: number) => api.del<{ deleted: boolean; drawing: DrawingDetail | null }>(`/drawings/versions/${vid}`),
    onSuccess: (r) => {
      toast(tx("Sürüm silindi"));
      onChanged();
      if (r.drawing) qc.setQueryData(["drawing", d0.id], r.drawing);
      else onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const delDrawing = useMutation({
    mutationFn: () => api.del(`/drawings/${d0.id}`),
    onSuccess: () => { toast(tx("Resim silindi")); onChanged(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const busy = assign.isPending || delVersion.isPending || delDrawing.isPending;
  const sugg = d0.suggestions ?? [];

  return (
    <div className="drawer" role="dialog" aria-label={d.filename}>
      <div className="row">
        <h2 style={{ margin: 0, flex: 1, wordBreak: "break-all" }}>{d.filename}</h2>
        <button className="btn small" onClick={onClose}>{tx("Kapat")}</button>
      </div>
      {q.isError && <div className="error">{errText(q.error)}</div>}
      <table className="simple" style={{ marginTop: 10 }}>
        <tbody>
          <tr><th>{tx("Parça No")}</th><td>{d.part_no ?? <span className="badge warn">{tx("Eşleşmedi")}</span>}</td></tr>
          <tr><th>{tx("Eşleşme")}</th><td>{viaLabel(d.match_via) || "—"}</td></tr>
          <tr><th>{tx("Tür")}</th><td>{d.ext.toUpperCase()}</td></tr>
          <tr><th>{tx("Revizyon")}</th><td>
            {d.rev || "—"}{d0.bom_rev != null && <>{" "}{tx("· BOM:")}{" "}{d0.bom_rev || "—"}</>}
            {d0.rev_mismatch && <span className="badge warn" style={{ marginLeft: 6 }}>{tx("Revizyon uyumsuz")}</span>}
          </td></tr>
          <tr><th>{tx("Güncel sürüm")}</th><td>{tx("v{0} · {1}", d.current_version, fmtSize(d.size))}</td></tr>
          <tr><th>{tx("Yükleyen")}</th><td>{d.uploaded_by || "—"} · {fmtDate(d.uploaded_at)}</td></tr>
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={() => onOpen(d)}>{d.inline ? tx("Aç") : tx("İndir")}</button>
        {d.inline && <button className="btn" onClick={() => void download(`/drawings/${d.id}/file`, d.filename).catch((e) => toast(errText(e), true))}>{tx("İndir")}</button>}
      </div>

      {canDesign && (
        <>
          <h2>{tx("Elle eşleştir")}</h2>
          <div className="row">
            <input list="dw-part-nos" value={pno} onChange={(e) => setPno(e.target.value)} placeholder={tx("Parça numarası…")} style={{ flex: 1, minWidth: 180 }}
              onKeyDown={(e) => { if (e.key === "Enter" && pno.trim()) assign.mutate(pno.trim()); }} />
            <button className="btn primary" disabled={busy || !pno.trim() || pno.trim() === d.part_no} onClick={() => assign.mutate(pno.trim())}>{tx("Eşleştir")}</button>
            {d.part_no && <button className="btn" disabled={busy} onClick={() => assign.mutate(null)}>{tx("Eşleşmeyi kaldır")}</button>}
          </div>
          {partNos.length === 0 && <div className="muted">{tx("Parça listesi yüklenemedi; numarayı elle yazabilirsiniz.")}</div>}
          {!d.part_no && sugg.length > 0 && (
            <div className="row" style={{ marginTop: 6 }}>
              <span className="muted">{tx("Öneriler:")}</span>
              {sugg.slice(0, 6).map((s) => (
                <button key={s.part_no} className="btn small" disabled={busy} onClick={() => assign.mutate(s.part_no)}
                  title={tx("Benzerlik %{0}", Math.round(s.score * (s.score <= 1 ? 100 : 1)))}>{s.part_no}</button>
              ))}
            </div>
          )}
        </>
      )}

      <h2>{tx("Sürüm geçmişi")}</h2>
      {q.isLoading ? <div className="muted">{tx("Yükleniyor…")}</div> : (
        <table className="simple">
          <thead><tr><th>{tx("Sürüm")}</th><th>{tx("Boyut")}</th><th>{tx("Yükleyen")}</th><th>{tx("Tarih")}</th><th /></tr></thead>
          <tbody>
            {(q.data?.versions ?? []).map((v) => (
              <tr key={v.id}>
                <td>{tx("v{0}", v.version_no)}{v.version_no === d.current_version && <span className="badge new" style={{ marginLeft: 6 }}>{tx("Güncel")}</span>}</td>
                <td>{fmtSize(v.size)}</td>
                <td>{v.uploaded_by || "—"}</td>
                <td>{fmtDate(v.uploaded_at)}</td>
                <td>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn small" onClick={() => onOpen(d, v)}>{d.inline ? tx("Aç") : tx("İndir")}</button>
                    {canDesign && (
                      <button className="btn small danger" disabled={busy}
                        onClick={() => {
                          const last = (q.data?.versions.length ?? 0) <= 1;
                          const msg = last
                            ? tx("v{0} bu resmin son sürümü. Silinirse resim tamamen kaldırılır. Devam edilsin mi?", v.version_no)
                            : tx("{0} dosyasının v{1} sürümü silinsin mi?", d.filename, v.version_no);
                          if (window.confirm(msg)) delVersion.mutate(v.id);
                        }}>{tx("Sil")}</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canDesign && (
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn danger" disabled={busy}
            onClick={() => { if (window.confirm(tx("{0} ve tüm sürümleri silinsin mi? Bu işlem geri alınamaz.", d.filename))) delDrawing.mutate(); }}>
            {tx("Resmi tüm sürümleriyle sil")}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------- page ----------
export default function Drawings() {
  const { pid } = useProject();
  const canDesign = useAuth().can("drawings", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [selected, setSelected] = useState<DrawingOut | null>(null);
  const [viewer, setViewer] = useState<Opened | null>(null);
  const [mode, setMode] = useState<"list" | "gallery">(() => {
    try { return localStorage.getItem("erp_dw_view") === "gallery" ? "gallery" : "list"; } catch { return "list"; }
  });
  const setView = (m: "list" | "gallery") => {
    setMode(m);
    try { localStorage.setItem("erp_dw_view", m); } catch { /* private mode */ }
  };
  const [showUpload, setShowUpload] = useState(false);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [visible, setVisible] = useState<Row[]>([]);
  const [zipMode, setZipMode] = useState("pdf");
  const [zipBusy, setZipBusy] = useState(false);
  const [askDelete, setAskDelete] = useState(false);

  const cacheRef = useRef<ThumbCache | null>(null);
  if (!cacheRef.current) cacheRef.current = new ThumbCache();
  const cache = cacheRef.current;
  useEffect(() => () => cache.dispose(), [cache]);

  const listQ = useQuery({
    queryKey: ["drawings", pid],
    queryFn: () => api.get<Listing>(`/projects/${pid}/drawings`),
    enabled: !!pid,
  });
  const partsQ = useQuery({
    queryKey: ["drawings-parts", pid],
    queryFn: () => api.get<{ rows: PartLite[] }>(`/projects/${pid}/parts?view=flat`),
    enabled: !!pid,
    staleTime: 60_000,
  });

  const partMap = useMemo(() => {
    const m = new Map<string, PartLite>();
    for (const p of partsQ.data?.rows ?? []) if (!m.has(p.part_no)) m.set(p.part_no, p);
    return m;
  }, [partsQ.data]);
  const partNos = useMemo(() => [...partMap.keys()].sort((a, b) => a.localeCompare(b, LOCALE, { numeric: true })), [partMap]);

  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["drawings", pid] });
    void qc.invalidateQueries({ queryKey: ["drawing"] });
    // Part list "Teknik Resim" column, dashboard "resmi olmayan" KPI and control list depend on drawings.
    void qc.invalidateQueries({ predicate: (q) => q.queryKey[1] === pid && q.queryKey[0] !== "drawings" && q.queryKey[0] !== "drawings-parts" });
  }, [qc, pid]);

  const allRows = useMemo<Row[]>(() => {
    const L = listQ.data;
    if (!L) return [];
    const mk = (d: DrawingOut, kind: Kind): Row => {
      const p = d.part_no ? partMap.get(d.part_no) : undefined;
      return {
        key: `d${d.id}`, kind, d,
        part_no: d.part_no ?? "", filename: d.filename, ext: d.ext.toUpperCase(), rev: d.rev ?? "",
        bom_rev: kind === "matched" ? d.bom_rev ?? p?.rev ?? "" : "",
        rev_state: kind !== "matched" ? "" : d.rev_mismatch ? tx("Uyumsuz") : tx("Uyumlu"),
        versions: d.version_count, uploaded_by: d.uploaded_by, uploaded_at: d.uploaded_at ?? "",
        main_group: p?.main_group ?? "", via: viaLabel(d.match_via), suggestion: d.suggestions?.[0]?.part_no ?? "",
      };
    };
    return [
      ...L.items.map((d) => mk(d, "matched")),
      ...L.unmatched.map((d) => mk(d, "unmatched")),
      ...L.no_drawing.map((pno): Row => {
        const p = partMap.get(pno);
        return {
          key: `p${pno}`, kind: "no_drawing", d: null, part_no: pno, filename: "", ext: "", rev: "",
          bom_rev: p?.rev ?? "", rev_state: "", versions: null, uploaded_by: "", uploaded_at: "",
          main_group: p?.main_group ?? "", via: "", suggestion: "",
        };
      }),
    ];
  }, [listQ.data, partMap]);

  const rows = useMemo(() => {
    let r = allRows;
    if (filter === "all") r = r.filter((x) => x.kind !== "no_drawing");
    else if (filter === "matched") r = r.filter((x) => x.kind === "matched");
    else if (filter === "unmatched") r = r.filter((x) => x.kind === "unmatched");
    else if (filter === "rev") r = r.filter((x) => x.kind === "matched" && x.d?.rev_mismatch);
    else r = r.filter((x) => x.kind === "no_drawing");
    const s = search.trim().toLocaleLowerCase(LOCALE);
    if (s) r = r.filter((x) => x.part_no.toLocaleLowerCase(LOCALE).includes(s) || x.filename.toLocaleLowerCase(LOCALE).includes(s));
    return r;
  }, [allRows, filter, search]);

  useEffect(() => { setSelection({}); }, [filter]);

  // Viewable drawings in the current filter: the viewer steps through them with ← →
  const gallery = useMemo(() => rows.filter((r) => r.d && IMAGE_EXTS_OR_PDF.has(r.d.ext)).map((r) => r.d!), [rows]);
  const openFile = useCallback((d: DrawingOut, v?: VersionOut) => {
    if (!IMAGE_EXTS_OR_PDF.has(d.ext)) {
      const src = v ? `/drawings/versions/${v.id}/file` : `/drawings/${d.id}/file`;
      void download(src, d.filename).catch((e) => toast(errText(e), true));
      return;
    }
    const kind = d.ext === "pdf" ? "pdf" as const : "image" as const;
    if (v) {
      setViewer({ items: [{ key: `v${v.id}`, name: `${d.filename} · v${v.version_no}`, path: `/drawings/versions/${v.id}/file`, kind }], start: 0 });
      return;
    }
    const list = gallery.some((x) => x.id === d.id) ? gallery : [d];
    setViewer({ items: list.map(dwItem), start: list.findIndex((x) => x.id === d.id) });
  }, [toast, gallery]);

  const assignQuick = useMutation({
    mutationFn: ({ id, part_no }: { id: number; part_no: string }) => api.post(`/drawings/${id}/assign`, { part_no }),
    onSuccess: (_r, v) => { toast(tx("Resim {0} parçasına eşleştirildi", v.part_no)); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<Row>[]>(() => [
    {
      id: "thumb", header: tx("Önizleme"), size: 74, enableSorting: false, noFilter: true,
      cell: ({ row }) => {
        const d = row.original.d;
        if (!d) return <span className="badge warn">{tx("Resim yok")}</span>;
        if (d.has_thumb) return <Thumb d={d} cache={cache} onOpen={() => openFile(d)} />;
        return <span className="dw-thumb dw-thumb-empty dw-ext">{d.ext.toUpperCase()}</span>;
      },
    },
    { accessorKey: "part_no", header: tx("Parça No"), size: 190,
      cell: ({ row }) => row.original.part_no || <span className="badge warn">{tx("Eşleşmedi")}</span> },
    { accessorKey: "filename", header: tx("Dosya"), size: 260 },
    { accessorKey: "ext", header: tx("Tür"), size: 70 },
    { accessorKey: "rev", header: tx("Resim Rev"), size: 90 },
    { accessorKey: "bom_rev", header: tx("BOM Rev"), size: 85 },
    {
      accessorKey: "rev_state", header: tx("Rev kontrol"), size: 110,
      cell: ({ row }) => row.original.rev_state === tx("Uyumsuz") ? <span className="badge warn">{tx("Uyumsuz")}</span>
        : row.original.rev_state ? <span className="muted">{tx("Uyumlu")}</span> : "",
    },
    { accessorKey: "versions", header: tx("Sürüm"), size: 70,
      cell: ({ row }) => row.original.versions == null ? "" : row.original.versions.toLocaleString(LOCALE) },
    { accessorKey: "main_group", header: tx("Ana Grup"), size: 140 },
    { accessorKey: "via", header: tx("Eşleşme"), size: 120 },
    { accessorKey: "uploaded_by", header: tx("Yükleyen"), size: 110 },
    { accessorKey: "uploaded_at", header: tx("Yükleme tarihi"), size: 130, noFilter: true,
      cell: ({ row }) => fmtDate(row.original.uploaded_at) },
    {
      accessorKey: "suggestion", header: tx("Öneri"), size: 210,
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind !== "unmatched" || !r.suggestion || !r.d) return "";
        if (!canDesign) return r.suggestion;
        const d = r.d;
        return (
          <span className="row" style={{ flexWrap: "nowrap", gap: 4 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{r.suggestion}</span>
            <button className="btn small" title={tx("Öneriyi ata")} disabled={assignQuick.isPending}
              onClick={(e) => { e.stopPropagation(); assignQuick.mutate({ id: d.id, part_no: r.suggestion }); }}>{tx("Ata")}</button>
          </span>
        );
      },
    },
    {
      id: "actions", header: "", size: 80, enableSorting: false, noFilter: true,
      cell: ({ row }) => {
        const d = row.original.d;
        if (!d) return "";
        return (
          <button className="btn small" onClick={(e) => { e.stopPropagation(); openFile(d); }}>{d.inline ? tx("Aç") : tx("İndir")}</button>
        );
      },
    },
  ], [cache, openFile, canDesign, assignQuick]);

  const L = listQ.data;
  const counts = {
    all: (L?.items.length ?? 0) + (L?.unmatched.length ?? 0),
    matched: L?.items.length ?? 0,
    unmatched: L?.unmatched.length ?? 0,
    rev: L?.counts.rev_mismatch ?? 0,
    no_drawing: L?.no_drawing.length ?? 0,
  };
  const TABS: { k: Filter; l: string }[] = [
    { k: "all", l: tx("Tüm dosyalar") }, { k: "matched", l: tx("Eşleşen") }, { k: "unmatched", l: tx("Eşleşmeyen") },
    { k: "rev", l: tx("Revizyon uyumsuz") }, { k: "no_drawing", l: tx("Resmi olmayan parçalar") },
  ];

  const zipParts = useMemo(() => {
    const sel = Object.keys(selection).filter((k) => selection[k]);
    const src = sel.length ? allRows.filter((r) => selection[r.key]) : visible;
    return [...new Set(src.filter((r) => r.kind === "matched" && r.part_no).map((r) => r.part_no))];
  }, [selection, allRows, visible]);
  const selCount = Object.values(selection).filter(Boolean).length;
  const selIds = useMemo(() => allRows.filter((r) => selection[r.key] && r.d).map((r) => r.d!.id), [selection, allRows]);
  const pickable = useMemo(() => rows.filter((r) => r.d), [rows]);
  const allPicked = pickable.length > 0 && pickable.every((r) => selection[r.key]);
  const delMany = useMutation({
    mutationFn: () => api.post<{ deleted: number }>("/drawings/delete", { ids: selIds }),
    onSuccess: (r) => {
      toast(tx("{0} resim silindi", r.deleted.toLocaleString(LOCALE)));
      setSelection({}); setAskDelete(false); refresh();
    },
    onError: (e) => toast(errText(e), true),
  });

  const printQr = async (path: string, extra: object, name: string) => {
    setZipBusy(true);
    try {
      await postDownload(`/projects/${pid}/drawings/${path}`, { part_nos: zipParts, ...extra }, name);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setZipBusy(false);
    }
  };

  const downloadZip = async () => {
    if (!zipParts.length) { toast(tx("İndirilecek eşleşmiş resim yok"), true); return; }
    setZipBusy(true);
    try {
      await postDownload(`/projects/${pid}/drawings/zip`, { part_nos: zipParts, mode: zipMode }, "resimler.zip");
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setZipBusy(false);
    }
  };

  const onVisible = useCallback((r: Row[]) => setVisible(r), []);
  const bulkActions = filter !== "no_drawing" && (
    <>
      {filter !== "unmatched" && (
        <>
          <select value={zipMode} onChange={(e) => setZipMode(e.target.value)} aria-label={tx("ZIP içeriği")}>
            {ZIP_MODES.map((m) => <option key={m.v} value={m.v}>{m.l}</option>)}
          </select>
          <button className="btn small" disabled={zipBusy || !zipParts.length} onClick={() => void downloadZip()}
            title={selCount ? tx("Seçili parçaların resimleri") : tx("Filtrelenen parçaların resimleri")}>
            {zipBusy ? tx("Hazırlanıyor…") : tx("ZIP indir ({0} {1} parça)", selCount ? tx("seçili") : tx("filtrelenen"), zipParts.length.toLocaleString(LOCALE))}
          </button>
          <PrintMenu label={tx("QR'lı yazdır")} disabled={zipBusy || !zipParts.length} choices={[
            { label: tx("QR resimde"), hint: tx("Antetin üstündeki boş yere küçük QR basar, sayı ve çizgilerin üstüne binmez. Yer yoksa QR sonraki sayfaya gelir."), run: () => void printQr("print", { place: "front" }, "resimler_qr.pdf") },
            { label: tx("QR arkada"), hint: tx("Çift taraflı yazdırın: QR kodlar resimlerin arkasına gelir."), run: () => void printQr("print", {}, "resimler_qr.pdf") },
            { label: tx("QR etiketleri"), hint: tx("70 x 37 mm, A4'te 24 etiket. Parçaya, kutuya veya basılı resme yapıştırın. %100 ölçekle yazdırın."), run: () => void printQr("codes", { layout: "labels" }, "qr_etiket.pdf") },
            { label: tx("QR listesi"), hint: tx("Tüm kodlar tek listede. İş başında panoda durur."), run: () => void printQr("codes", { layout: "list" }, "qr_liste.pdf") },
          ]} />
        </>
      )}
      {canDesign && selIds.length > 0 && (
        <button className="btn small danger" onClick={() => setAskDelete(true)}>{tx("Seçilenleri sil ({0})", selIds.length.toLocaleString(LOCALE))}</button>
      )}
    </>
  );

  return (
    <Page full>
      <div className="dw-head">
        <div className="row">
          <h1 style={{ margin: 0 }}>{tx("Teknik Resimler")}</h1>
          {L && (
            <span className="muted">
              {tx("{0} parçanın resmi var · {1} imalat parçasının resmi yok", L.counts.parts_with_drawing.toLocaleString(LOCALE), counts.no_drawing.toLocaleString(LOCALE))}
            </span>
          )}
          <span className="spacer" style={{ flex: 1 }} />
          <div className="seg" role="group" aria-label={tx("Görünüm")}>
            <button className={mode === "list" ? "on" : ""} onClick={() => setView("list")} title={tx("Liste")}><List size={15} />{" "}{tx("Liste")}</button>
            <button className={mode === "gallery" ? "on" : ""} onClick={() => setView("gallery")} title={tx("Küçük resimler")}><LayoutGrid size={15} />{" "}{tx("Galeri")}</button>
          </div>
          {canDesign && (
            <button className={"btn" + (showUpload ? "" : " primary")} onClick={() => setShowUpload((s) => !s)}>
              {showUpload ? tx("Yükleme panelini gizle") : tx("Resim yükle")}
            </button>
          )}
        </div>
        {canDesign && showUpload && <UploadPanel pid={pid} onFinished={refresh} />}
        <div className="tabs" style={{ marginBottom: 0, marginTop: 8 }}>
          {TABS.map((t) => (
            <button key={t.k} className={filter === t.k ? "active" : ""} onClick={() => { setFilter(t.k); setSelection({}); }}>
              {t.l} <span className={"badge" + (t.k === "rev" && counts.rev ? " warn" : t.k === "unmatched" && counts.unmatched ? " warn" : "")}>{counts[t.k].toLocaleString(LOCALE)}</span>
            </button>
          ))}
        </div>
      </div>

      {listQ.isLoading ? (
        <div className="muted" style={{ padding: 16 }}>{tx("Yükleniyor…")}</div>
      ) : listQ.isError ? (
        <div className="error" style={{ padding: 16 }}>
          {errText(listQ.error)} <button className="btn small" onClick={() => void listQ.refetch()}>{tx("Tekrar dene")}</button>
        </div>
      ) : mode === "gallery" ? (
        <div className="dw-gallery-wrap">
          <div className="row" style={{ marginBottom: 8 }}>
            <input type="search" placeholder={tx("Parça no veya dosya adı ara…")} value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
            {filter !== "no_drawing" && pickable.length > 0 && (
              <label className="dw-pick-all">
                <input type="checkbox" checked={allPicked}
                  ref={(el) => { if (el) el.indeterminate = selCount > 0 && !allPicked; }}
                  onChange={() => setSelection(allPicked ? {} : Object.fromEntries(pickable.map((r) => [r.key, true])))} />
                {tx("Tümünü seç")}{" "}<span className="muted">({pickable.length.toLocaleString(LOCALE)})</span>
              </label>
            )}
            <span className="muted">{tx("{0} kayıt · küçük resme tıklayınca büyür", rows.length.toLocaleString(LOCALE))}</span>
            {bulkActions}
          </div>
          {!rows.length && <div className="empty">{filter === "no_drawing" ? tx("Resmi olmayan imalat parçası yok.") : tx("Resim yok.")}</div>}
          <div className="dw-gallery">
            {rows.map((r) => (
              <div key={r.key} className={`card dw-card${r.kind !== "matched" ? " warn-card" : ""}`}>
                <div className="dw-card-img" onClick={() => (r.d ? openFile(r.d) : undefined)}
                  title={r.d ? (r.d.inline ? tx("Büyütmek için tıklayın") : tx("İndir")) : ""}>
                  {r.d ? <PreviewThumb path={r.d.has_thumb ? `/drawings/${r.d.id}/thumb` : null} label={r.d.filename} />
                    : <span className="thumb-ph">{tx("Resim yok")}</span>}
                  {r.d?.rev_mismatch && <span className="badge warn dw-card-badge">{tx("Rev farkı")}</span>}
                  {r.d && filter !== "no_drawing" && (
                    <input type="checkbox" className="dw-card-check" aria-label={tx("Seç")} checked={!!selection[r.key]}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const on = e.target.checked;
                        setSelection((cur) => { const n = { ...cur }; if (on) n[r.key] = true; else delete n[r.key]; return n; });
                      }} />
                  )}
                </div>
                <div className="dw-card-body" onClick={() => r.d && setSelected(r.d)}>
                  <b className="mono">{r.part_no || tx("Eşleşmedi")}</b>
                  <span className="muted" title={r.filename}>{r.filename || r.main_group}</span>
                  {r.d && <span className="muted">{tx("Rev")}{" "}{r.rev || "—"} · {r.ext}{r.versions && r.versions > 1 ? tx(" · {0} sürüm", r.versions) : ""}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <DataGrid<Row>
          stateKey="Teknik resimler" exportName={tx("Teknik resimler")}
          data={rows}
          columns={columns}
          getRowId={(r) => r.key}
          rowHeight={ROW_H}
          selectable={filter !== "no_drawing"}
          selection={selection}
          onSelectionChange={setSelection}
          onVisibleRowsChange={onVisible}
          onRowClick={(r) => { if (r.d) setSelected(r.d); }}
          openOnClick
          rowStyle={(r) => (r.kind === "unmatched" || r.kind === "no_drawing" ? { background: "color-mix(in srgb, var(--warn) 10%, var(--surface))" } : undefined)}
          emptyText={filter === "no_drawing" ? tx("Resmi olmayan imalat parçası yok.") : tx("Resim yok.")}
          toolbar={
            <>
              <input type="search" placeholder={tx("Parça no veya dosya adı ara…")} value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
              {bulkActions}
            </>
          }
        />
      )}

      <datalist id="dw-part-nos">
        {selected && partNos.map((p) => <option key={p} value={p} />)}
      </datalist>

      {selected && (
        <DetailDrawer key={selected.id} d0={selected} partNos={partNos} canDesign={canDesign}
          onClose={() => setSelected(null)} onOpen={openFile} onChanged={refresh} />
      )}
      {viewer && <Viewer items={viewer.items} start={viewer.start} onClose={() => setViewer(null)} />}
      {askDelete && (
        <div className="modal-back" onClick={() => setAskDelete(false)}>
          <div className="modal" style={{ maxWidth: 520 }} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>{tx("{0} resim silinsin mi?", selIds.length.toLocaleString(LOCALE))}</h3>
            <p>{tx("Dosyalar tüm sürümleriyle")}{" "}<b>{tx("kalıcı olarak")}</b>{" "}{tx("silinir. Resimler parça numarasına bağlıdır; aynı parçayı kullanan diğer projelerden de kalkar.")}</p>
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
              <button className="btn" onClick={() => setAskDelete(false)} disabled={delMany.isPending}>{tx("Vazgeç")}</button>
              <button className="btn danger" onClick={() => delMany.mutate()} disabled={delMany.isPending}>
                {delMany.isPending ? tx("Siliniyor…") : tx("Kalıcı olarak sil")}
              </button>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}
