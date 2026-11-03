import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { Page, useProject } from "../components/Layout";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import PdfViewer from "../components/PdfViewer";
import { errText, useToast } from "../components/Toast";
import { api, ApiError, blobUrl, desktopFile, download, getToken, upload } from "../api/client";
import { desktop } from "../api/desktop";
import { useAuth } from "../api/auth";

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
type Viewer = { kind: "pdf" | "image"; src: string; title: string; name: string };

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg"]);
const VIA_LABELS: Record<string, string> = { exact: "Otomatik", normalized: "Otomatik (normalize)", alias: "Alias", manual: "Elle" };
const STATUS_LABELS: Record<UploadResult["status"], string> = {
  created: "Yeni", new_version: "Yeni sürüm", unchanged: "Değişmedi", rejected: "Reddedildi",
};
const ZIP_MODES = [
  { v: "pdf", l: "Sadece PDF" }, { v: "pdf_dwg", l: "PDF + DWG" }, { v: "all", l: "Tüm dosyalar" },
];
const UPLOAD_CONCURRENCY = 3;
const THUMB_CONCURRENCY = 4;
const ROW_H = 44;

const fmtDate = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" }) : "");
function fmtSize(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${n.toLocaleString("tr-TR")} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} KB`;
  return `${(n / 1024 / 1024).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} MB`;
}
const viaLabel = (v: string | null | undefined) => (v ? VIA_LABELS[v] ?? v : "");

/** POST that returns a file (zip); `download()` only does GET. */
async function postDownload(path: string, body: unknown, fallbackName: string): Promise<void> {
  const token = getToken();
  if (desktop()) return desktopFile({ path, token, filename: fallbackName, action: "save", method: "POST", body });
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) {
    let msg = `İndirme başarısız (${res.status})`;
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
          .catch(() => { this.urls.set(key, null); resolve(null); })
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
      onClick={(e) => { e.stopPropagation(); onOpen(); }} title="Önizleme – açmak için tıklayın" />
  );
}

// ---------- upload queue ----------
type QItem = { id: number; file: File; pct: number; state: "waiting" | "uploading" | "done" | "error"; error?: string; results?: UploadResult[] };
let qSeq = 0;

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
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
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

  const start = useCallback(async (files: File[]) => {
    const list = files.filter((f) => !isJunk(f.name));
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
    toast(`${items.length.toLocaleString("tr-TR")} dosyanın yüklemesi tamamlandı`);
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
          void filesFromDrop(e.dataTransfer).then(start).catch((er) => toast(errText(er), true));
        }}
      >
        <div><b>Teknik resimleri buraya sürükleyip bırakın</b></div>
        <div className="muted">PDF, DWG, DXF, SLDDRW, SLDPRT, SLDASM, STEP/STP, PNG/JPG veya .zip · klasör de bırakılabilir</div>
        <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
          <button className="btn primary" disabled={busy} onClick={() => fileRef.current?.click()}>Dosya seç</button>
          <button className="btn" disabled={busy} onClick={() => dirRef.current?.click()}>Klasör seç</button>
        </div>
        <input ref={fileRef} type="file" multiple hidden
          accept=".pdf,.dwg,.dxf,.slddrw,.sldprt,.sldasm,.step,.stp,.png,.jpg,.jpeg,.zip"
          onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; void start(f); }} />
        <input ref={dirRef} type="file" multiple hidden
          onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; void start(f); }} />
      </div>

      {queue.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="row">
            <b>{busy ? "Yükleniyor" : "Yükleme tamamlandı"}</b>
            <span className="muted">{done.toLocaleString("tr-TR")} / {queue.length.toLocaleString("tr-TR")} dosya</span>
            <div className="progress" style={{ flex: 1, minWidth: 120 }}><div style={{ width: `${totalPct}%` }} /></div>
            {!busy && <button className="btn small" onClick={() => setQueue([])}>Temizle</button>}
          </div>
          <div className="dw-queue">
            {queue.map((q) => (
              <div key={q.id} className="dw-qrow">
                <span className="dw-qname" title={q.file.name}>{q.file.name}</span>
                <span className="muted">{fmtSize(q.file.size)}</span>
                {q.state === "error" ? (
                  <span className="badge err" title={q.error}>Hata: {q.error}</span>
                ) : q.state === "waiting" ? (
                  <span className="muted">Sırada</span>
                ) : (
                  <div className="progress" style={{ width: 120 }}><div style={{ width: `${q.pct}%` }} /></div>
                )}
              </div>
            ))}
          </div>
          {results.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 10 }}>
                <span className="badge">Kaydedilen: {sum.stored.toLocaleString("tr-TR")}</span>
                <span className="badge">Değişmeyen: {sum.unchanged.toLocaleString("tr-TR")}</span>
                <span className="badge new">Eşleşen: {sum.matched.toLocaleString("tr-TR")}</span>
                <span className={"badge" + (sum.unmatched ? " warn" : "")}>Eşleşmeyen: {sum.unmatched.toLocaleString("tr-TR")}</span>
                <span className={"badge" + (sum.rev ? " warn" : "")}>Revizyon uyumsuz: {sum.rev.toLocaleString("tr-TR")}</span>
                <span className={"badge" + (sum.rejected ? " err" : "")}>Reddedilen: {sum.rejected.toLocaleString("tr-TR")}</span>
              </div>
              <div className="dw-results">
                <table className="simple">
                  <thead>
                    <tr><th>Dosya</th><th>Durum</th><th>Parça No</th><th>Rev (resim / BOM)</th><th>Not</th></tr>
                  </thead>
                  <tbody>
                    {shownResults.map((r, i) => (
                      <tr key={i}>
                        <td>{r.filename}{r.zip && <span className="muted"> ({r.zip})</span>}</td>
                        <td>
                          <span className={"badge" + (r.status === "rejected" ? " err" : r.status === "unchanged" ? "" : " new")}>{STATUS_LABELS[r.status] ?? r.status}</span>
                        </td>
                        <td>{r.part_no ?? (r.status !== "rejected" && <span className="badge warn">Eşleşmedi</span>)}</td>
                        <td>
                          {r.status !== "rejected" && <>{r.rev || "—"} / {r.bom_rev || "—"}</>}
                          {r.rev_mismatch && <span className="badge warn" style={{ marginLeft: 6 }}>Uyumsuz</span>}
                        </td>
                        <td className="muted">
                          {r.error || (r.suggestions?.length ? `Öneri: ${r.suggestions.slice(0, 3).map((s) => s.part_no).join(", ")}` : viaLabel(r.via))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {results.length > shownResults.length && (
                  <div className="muted" style={{ padding: 6 }}>
                    İlk {shownResults.length.toLocaleString("tr-TR")} sonuç gösteriliyor (toplam {results.length.toLocaleString("tr-TR")}).
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
function ImageViewer({ src, title, onClose, onDownload }: { src: string; title: string; onClose: () => void; onDownload: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let u: string | null = null;
    blobUrl(src).then((x) => { u = x; if (alive) setUrl(x); else URL.revokeObjectURL(x); }).catch((e) => alive && setErr(errText(e)));
    return () => { alive = false; if (u) URL.revokeObjectURL(u); };
  }, [src]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal pdfv" onClick={(e) => e.stopPropagation()}>
        <div className="row pdfv-bar">
          <b className="pdfv-title">{title}</b>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="btn small" onClick={onDownload}>İndir</button>
          <button className="btn small" onClick={onClose}>Kapat</button>
        </div>
        <div className="pdfv-body">
          {err ? <div className="error" style={{ padding: 16 }}>{err}</div>
            : url ? <img src={url} alt={title} style={{ maxWidth: "100%" }} />
            : <div className="muted pdfv-loading">Yükleniyor…</div>}
        </div>
      </div>
    </div>
  );
}

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
      toast(r.part_no ? `Resim ${r.part_no} parçasına eşleştirildi` : "Eşleşme kaldırıldı");
      onChanged();
    },
    onError: (e) => toast(errText(e), true),
  });
  const delVersion = useMutation({
    mutationFn: (vid: number) => api.del<{ deleted: boolean; drawing: DrawingDetail | null }>(`/drawings/versions/${vid}`),
    onSuccess: (r) => {
      toast("Sürüm silindi");
      onChanged();
      if (r.drawing) qc.setQueryData(["drawing", d0.id], r.drawing);
      else onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const delDrawing = useMutation({
    mutationFn: () => api.del(`/drawings/${d0.id}`),
    onSuccess: () => { toast("Resim silindi"); onChanged(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const busy = assign.isPending || delVersion.isPending || delDrawing.isPending;
  const sugg = d0.suggestions ?? [];

  return (
    <div className="drawer" role="dialog" aria-label={d.filename}>
      <div className="row">
        <h2 style={{ margin: 0, flex: 1, wordBreak: "break-all" }}>{d.filename}</h2>
        <button className="btn small" onClick={onClose}>Kapat</button>
      </div>
      {q.isError && <div className="error">{errText(q.error)}</div>}
      <table className="simple" style={{ marginTop: 10 }}>
        <tbody>
          <tr><th>Parça No</th><td>{d.part_no ?? <span className="badge warn">Eşleşmedi</span>}</td></tr>
          <tr><th>Eşleşme</th><td>{viaLabel(d.match_via) || "—"}</td></tr>
          <tr><th>Tür</th><td>{d.ext.toUpperCase()}</td></tr>
          <tr><th>Revizyon</th><td>
            {d.rev || "—"}{d0.bom_rev != null && <> · BOM: {d0.bom_rev || "—"}</>}
            {d0.rev_mismatch && <span className="badge warn" style={{ marginLeft: 6 }}>Revizyon uyumsuz</span>}
          </td></tr>
          <tr><th>Güncel sürüm</th><td>v{d.current_version} · {fmtSize(d.size)}</td></tr>
          <tr><th>Yükleyen</th><td>{d.uploaded_by || "—"} · {fmtDate(d.uploaded_at)}</td></tr>
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn primary" onClick={() => onOpen(d)}>{d.inline ? "Aç" : "İndir"}</button>
        {d.inline && <button className="btn" onClick={() => void download(`/drawings/${d.id}/file`, d.filename).catch((e) => toast(errText(e), true))}>İndir</button>}
      </div>

      {canDesign && (
        <>
          <h2>Elle eşleştir</h2>
          <div className="row">
            <input list="dw-part-nos" value={pno} onChange={(e) => setPno(e.target.value)} placeholder="Parça numarası…" style={{ flex: 1, minWidth: 180 }}
              onKeyDown={(e) => { if (e.key === "Enter" && pno.trim()) assign.mutate(pno.trim()); }} />
            <button className="btn primary" disabled={busy || !pno.trim() || pno.trim() === d.part_no} onClick={() => assign.mutate(pno.trim())}>Eşleştir</button>
            {d.part_no && <button className="btn" disabled={busy} onClick={() => assign.mutate(null)}>Eşleşmeyi kaldır</button>}
          </div>
          {partNos.length === 0 && <div className="muted">Parça listesi yüklenemedi; numarayı elle yazabilirsiniz.</div>}
          {!d.part_no && sugg.length > 0 && (
            <div className="row" style={{ marginTop: 6 }}>
              <span className="muted">Öneriler:</span>
              {sugg.slice(0, 6).map((s) => (
                <button key={s.part_no} className="btn small" disabled={busy} onClick={() => assign.mutate(s.part_no)}
                  title={`Benzerlik %${Math.round(s.score * (s.score <= 1 ? 100 : 1))}`}>{s.part_no}</button>
              ))}
            </div>
          )}
        </>
      )}

      <h2>Sürüm geçmişi</h2>
      {q.isLoading ? <div className="muted">Yükleniyor…</div> : (
        <table className="simple">
          <thead><tr><th>Sürüm</th><th>Boyut</th><th>Yükleyen</th><th>Tarih</th><th /></tr></thead>
          <tbody>
            {(q.data?.versions ?? []).map((v) => (
              <tr key={v.id}>
                <td>v{v.version_no}{v.version_no === d.current_version && <span className="badge new" style={{ marginLeft: 6 }}>Güncel</span>}</td>
                <td>{fmtSize(v.size)}</td>
                <td>{v.uploaded_by || "—"}</td>
                <td>{fmtDate(v.uploaded_at)}</td>
                <td>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <button className="btn small" onClick={() => onOpen(d, v)}>{d.inline ? "Aç" : "İndir"}</button>
                    {canDesign && (
                      <button className="btn small danger" disabled={busy}
                        onClick={() => {
                          const last = (q.data?.versions.length ?? 0) <= 1;
                          const msg = last
                            ? `v${v.version_no} bu resmin son sürümü. Silinirse resim tamamen kaldırılır. Devam edilsin mi?`
                            : `${d.filename} dosyasının v${v.version_no} sürümü silinsin mi?`;
                          if (window.confirm(msg)) delVersion.mutate(v.id);
                        }}>Sil</button>
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
            onClick={() => { if (window.confirm(`${d.filename} ve tüm sürümleri silinsin mi? Bu işlem geri alınamaz.`)) delDrawing.mutate(); }}>
            Resmi tüm sürümleriyle sil
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
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<DrawingOut | null>(null);
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [visible, setVisible] = useState<Row[]>([]);
  const [zipMode, setZipMode] = useState("pdf");
  const [zipBusy, setZipBusy] = useState(false);

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
  const partNos = useMemo(() => [...partMap.keys()].sort((a, b) => a.localeCompare(b, "tr-TR", { numeric: true })), [partMap]);

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
        rev_state: kind !== "matched" ? "" : d.rev_mismatch ? "Uyumsuz" : "Uyumlu",
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
    const s = search.trim().toLocaleLowerCase("tr-TR");
    if (s) r = r.filter((x) => x.part_no.toLocaleLowerCase("tr-TR").includes(s) || x.filename.toLocaleLowerCase("tr-TR").includes(s));
    return r;
  }, [allRows, filter, search]);

  useEffect(() => { setSelection({}); }, [filter]);

  const openFile = useCallback((d: DrawingOut, v?: VersionOut) => {
    const src = v ? `/drawings/versions/${v.id}/file` : `/drawings/${d.id}/file`;
    const title = v ? `${d.filename} · v${v.version_no}` : d.filename;
    if (d.ext === "pdf") setViewer({ kind: "pdf", src, title, name: d.filename });
    else if (IMAGE_EXTS.has(d.ext)) setViewer({ kind: "image", src, title, name: d.filename });
    else void download(src, d.filename).catch((e) => toast(errText(e), true));
  }, [toast]);

  const assignQuick = useMutation({
    mutationFn: ({ id, part_no }: { id: number; part_no: string }) => api.post(`/drawings/${id}/assign`, { part_no }),
    onSuccess: (_r, v) => { toast(`Resim ${v.part_no} parçasına eşleştirildi`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<Row>[]>(() => [
    {
      id: "thumb", header: "Önizleme", size: 74, enableSorting: false, noFilter: true,
      cell: ({ row }) => {
        const d = row.original.d;
        if (!d) return <span className="badge warn">Resim yok</span>;
        if (d.has_thumb) return <Thumb d={d} cache={cache} onOpen={() => openFile(d)} />;
        return <span className="dw-thumb dw-thumb-empty dw-ext">{d.ext.toUpperCase()}</span>;
      },
    },
    { accessorKey: "part_no", header: "Parça No", size: 190,
      cell: ({ row }) => row.original.part_no || <span className="badge warn">Eşleşmedi</span> },
    { accessorKey: "filename", header: "Dosya", size: 260 },
    { accessorKey: "ext", header: "Tür", size: 70 },
    { accessorKey: "rev", header: "Resim Rev", size: 90 },
    { accessorKey: "bom_rev", header: "BOM Rev", size: 85 },
    {
      accessorKey: "rev_state", header: "Rev kontrol", size: 110,
      cell: ({ row }) => row.original.rev_state === "Uyumsuz" ? <span className="badge warn">Uyumsuz</span>
        : row.original.rev_state ? <span className="muted">Uyumlu</span> : "",
    },
    { accessorKey: "versions", header: "Sürüm", size: 70,
      cell: ({ row }) => row.original.versions == null ? "" : row.original.versions.toLocaleString("tr-TR") },
    { accessorKey: "main_group", header: "Ana Grup", size: 140 },
    { accessorKey: "via", header: "Eşleşme", size: 120 },
    { accessorKey: "uploaded_by", header: "Yükleyen", size: 110 },
    { accessorKey: "uploaded_at", header: "Yükleme tarihi", size: 130, noFilter: true,
      cell: ({ row }) => fmtDate(row.original.uploaded_at) },
    {
      accessorKey: "suggestion", header: "Öneri", size: 210,
      cell: ({ row }) => {
        const r = row.original;
        if (r.kind !== "unmatched" || !r.suggestion || !r.d) return "";
        if (!canDesign) return r.suggestion;
        const d = r.d;
        return (
          <span className="row" style={{ flexWrap: "nowrap", gap: 4 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{r.suggestion}</span>
            <button className="btn small" title="Öneriyi ata" disabled={assignQuick.isPending}
              onClick={(e) => { e.stopPropagation(); assignQuick.mutate({ id: d.id, part_no: r.suggestion }); }}>Ata</button>
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
          <button className="btn small" onClick={(e) => { e.stopPropagation(); openFile(d); }}>{d.inline ? "Aç" : "İndir"}</button>
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
    { k: "all", l: "Tüm dosyalar" }, { k: "matched", l: "Eşleşen" }, { k: "unmatched", l: "Eşleşmeyen" },
    { k: "rev", l: "Revizyon uyumsuz" }, { k: "no_drawing", l: "Resmi olmayan parçalar" },
  ];

  const zipParts = useMemo(() => {
    const sel = Object.keys(selection).filter((k) => selection[k]);
    const src = sel.length ? allRows.filter((r) => selection[r.key]) : visible;
    return [...new Set(src.filter((r) => r.kind === "matched" && r.part_no).map((r) => r.part_no))];
  }, [selection, allRows, visible]);
  const selCount = Object.values(selection).filter(Boolean).length;

  const downloadZip = async () => {
    if (!zipParts.length) { toast("İndirilecek eşleşmiş resim yok", true); return; }
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

  return (
    <Page full>
      <div className="dw-head">
        <div className="row">
          <h1 style={{ margin: 0 }}>Teknik Resimler</h1>
          {L && (
            <span className="muted">
              {L.counts.parts_with_drawing.toLocaleString("tr-TR")} parçanın resmi var · {counts.no_drawing.toLocaleString("tr-TR")} imalat parçasının resmi yok
            </span>
          )}
          <span className="spacer" style={{ flex: 1 }} />
          {canDesign && (
            <button className={"btn" + (showUpload ? "" : " primary")} onClick={() => setShowUpload((s) => !s)}>
              {showUpload ? "Yükleme panelini gizle" : "Resim yükle"}
            </button>
          )}
        </div>
        {canDesign && showUpload && <UploadPanel pid={pid} onFinished={refresh} />}
        <div className="tabs" style={{ marginBottom: 0, marginTop: 8 }}>
          {TABS.map((t) => (
            <button key={t.k} className={filter === t.k ? "active" : ""} onClick={() => setFilter(t.k)}>
              {t.l} <span className={"badge" + (t.k === "rev" && counts.rev ? " warn" : t.k === "unmatched" && counts.unmatched ? " warn" : "")}>{counts[t.k].toLocaleString("tr-TR")}</span>
            </button>
          ))}
        </div>
      </div>

      {listQ.isLoading ? (
        <div className="muted" style={{ padding: 16 }}>Yükleniyor…</div>
      ) : listQ.isError ? (
        <div className="error" style={{ padding: 16 }}>
          {errText(listQ.error)} <button className="btn small" onClick={() => void listQ.refetch()}>Tekrar dene</button>
        </div>
      ) : (
        <DataGrid<Row>
          data={rows}
          columns={columns}
          getRowId={(r) => r.key}
          rowHeight={ROW_H}
          selectable={filter !== "no_drawing" && filter !== "unmatched"}
          selection={selection}
          onSelectionChange={setSelection}
          onVisibleRowsChange={onVisible}
          onRowClick={(r) => { if (r.d) setSelected(r.d); }}
          rowStyle={(r) => (r.kind === "unmatched" || r.kind === "no_drawing" ? { background: "color-mix(in srgb, var(--warn) 10%, var(--surface))" } : undefined)}
          emptyText={filter === "no_drawing" ? "Resmi olmayan imalat parçası yok." : "Resim yok."}
          toolbar={
            <>
              <input type="search" placeholder="Parça no veya dosya adı ara…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
              {filter !== "no_drawing" && filter !== "unmatched" && (
                <>
                  <select value={zipMode} onChange={(e) => setZipMode(e.target.value)} aria-label="ZIP içeriği">
                    {ZIP_MODES.map((m) => <option key={m.v} value={m.v}>{m.l}</option>)}
                  </select>
                  <button className="btn small" disabled={zipBusy || !zipParts.length} onClick={() => void downloadZip()}
                    title={selCount ? "Seçili parçaların resimleri" : "Filtrelenen parçaların resimleri"}>
                    {zipBusy ? "Hazırlanıyor…" : `ZIP indir (${selCount ? "seçili" : "filtrelenen"} ${zipParts.length.toLocaleString("tr-TR")} parça)`}
                  </button>
                </>
              )}
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
      {viewer?.kind === "pdf" && (
        <PdfViewer src={viewer.src} title={viewer.title} onClose={() => setViewer(null)}
          onDownload={() => void download(viewer.src, viewer.name).catch((e) => toast(errText(e), true))} />
      )}
      {viewer?.kind === "image" && (
        <ImageViewer src={viewer.src} title={viewer.title} onClose={() => setViewer(null)}
          onDownload={() => void download(viewer.src, viewer.name).catch((e) => toast(errText(e), true))} />
      )}
    </Page>
  );
}
