import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import jsQR from "jsqr";
import { Camera, Image as ImageIcon } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api } from "../api/client";
import { useAuth } from "../api/auth";
import { Page } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Loading } from "./admin/shared";
import { PO_COLORS, WO_COLORS, fmtDay, fmtQty, numOrNull, type PoLine, type WoMaterial, type WoWarning, type WorkOrder } from "./erp/common";

type StockDetail = { code: string; name: string; kind_label: string; unit: string; qty: number; min_qty: number; location: string };
type PoDetail = { no: string; firm_name: string; status: string; status_label: string; due_date: string | null; lines: PoLine[] };
type WoDetail = {
  no: string; part_no: string; description: string; qty: number; done_qty: number; remaining: number; status: string;
  status_label: string; project_name: string | null; materials: WoMaterial[];
};
type Result =
  | { type: "stock"; id: number; label: string; actions: string[]; detail: StockDetail }
  | { type: "po"; id: number; label: string; actions: string[]; detail: PoDetail }
  | { type: "wo"; id: number; label: string; actions: string[]; detail: WoDetail };

const MAX_SIDES = [1600, 1000, 2400];   // a phone photo is far bigger than jsQR needs; smaller is faster and often reads better

/** Read a QR code from a photo, at a few sizes, never above the photo's own. */
async function decodePhoto(file: File): Promise<string | null> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const longest = Math.max(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    for (const side of new Set(MAX_SIDES.map((s) => Math.min(s, longest)))) {
      canvas.width = Math.round((img.naturalWidth * side) / longest);
      canvas.height = Math.round((img.naturalHeight * side) / longest);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const hit = jsQR(ctx.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
      if (hit?.data) return hit.data;
    }
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Live camera. Only on a secure page: getUserMedia does not exist on the plain HTTP of the LAN. */
function CameraReader({ onRead, onClose }: { onRead: (text: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const toast = useToast();
  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer = 0;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const tick = () => {
      const v = video.current;
      if (stopped || !v || !ctx) return;
      if (v.readyState >= v.HAVE_ENOUGH_DATA && v.videoWidth) {
        const k = Math.min(1, 800 / Math.max(v.videoWidth, v.videoHeight));
        canvas.width = Math.round(v.videoWidth * k);
        canvas.height = Math.round(v.videoHeight * k);
        ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
        const hit = jsQR(ctx.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height, { inversionAttempts: "dontInvert" });
        if (hit?.data) { onRead(hit.data); return; }
      }
      timer = window.setTimeout(tick, 150);
    };
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false }).then((s) => {
      if (stopped) { s.getTracks().forEach((t) => t.stop()); return; }
      stream = s;
      if (video.current) {
        video.current.srcObject = s;
        void video.current.play();
      }
      tick();
    }).catch((e) => { toast(`Kamera açılamadı: ${errText(e)}`, true); onClose(); });
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <div className="scan-video"><video ref={video} playsInline muted /></div>;
}

export default function Scan() {
  const { can } = useAuth();
  const toast = useToast();
  const [text, setText] = useState("");
  const [payload, setPayload] = useState("");
  const [camera, setCamera] = useState(false);
  const [decoding, setDecoding] = useState(false);
  const box = useRef<HTMLInputElement>(null);
  const liveCamera = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

  const res = useQuery({
    queryKey: ["scan", payload], enabled: !!payload, retry: false,
    queryFn: () => api.post<Result>("/scan/resolve", { payload }),
  });
  const { refetch } = res;
  const read = useCallback((value: string) => {
    const v = value.trim();
    if (!v) return;
    setCamera(false);
    setText("");
    setPayload((old) => {
      if (old === v) void refetch();
      return v;
    });
    box.current?.focus({ preventScroll: true });
  }, [refetch]);

  useEffect(() => {
    // A phone would pop its keyboard over the camera buttons; a desk with a hand scanner wants the cursor ready
    if (window.matchMedia("(pointer: fine)").matches) box.current?.focus();
  }, []);

  const photo = async (file: File | undefined) => {
    if (!file) return;
    setDecoding(true);
    try {
      const hit = await decodePhoto(file);
      if (hit) read(hit);
      else toast("Fotoğrafta QR kod okunamadı. Daha yakından ve net çekin.", true);
    } catch {
      toast("Fotoğraf açılamadı", true);
    } finally {
      setDecoding(false);
    }
  };

  if (!(can("stock") || can("purchasing") || can("workorders"))) {
    return <Page><div className="card empty">Tarama için stok, satın alma veya iş emri yetkisi gerekli.</div></Page>;
  }
  const submit = (e: FormEvent) => { e.preventDefault(); read(text); };
  const failed = res.error instanceof ApiError ? res.error : null;
  return (
    <Page>
      <div className="scan">
        <div className="card">
          <h2 style={{ margin: "0 0 10px" }}>Barkod okut</h2>
          <form onSubmit={submit}>
            <input ref={box} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" autoCapitalize="off"
              spellCheck={false} enterKeyHint="go" placeholder="Okutun veya kodu yazın" aria-label="Barkod veya stok kodu" />
            <button className="btn primary" disabled={!text.trim()}>Bul</button>
          </form>
          <div className="scan-ways" style={{ marginTop: 10 }}>
            {liveCamera && (
              <button type="button" className="btn" onClick={() => setCamera((v) => !v)}>
                <Camera size={16} /> {camera ? "Kamerayı kapat" : "Kamera ile okut"}
              </button>
            )}
            <label className="btn">
              <ImageIcon size={16} /> {decoding ? "Okunuyor…" : "Fotoğraf ile okut"}
              <input type="file" accept="image/*" capture="environment" disabled={decoding}
                onChange={(e) => { void photo(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
          </div>
          {!liveCamera && <p className="muted" style={{ margin: "8px 0 0" }}>Canlı kamera yalnızca güvenli (HTTPS) bağlantıda açılır; burada QR kodun fotoğrafını çekin.</p>}
        </div>
        {camera && <CameraReader onRead={read} onClose={() => setCamera(false)} />}
        {payload && res.isLoading && <Loading error={null} loading />}
        {failed && <div className="card"><span className="error">{failed.message}</span></div>}
        {res.data && !res.error && <ResultCard key={`${res.data.type}-${res.data.id}`} r={res.data} />}
      </div>
    </Page>
  );
}

function useDone() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["scan", "stock", "stock-moves", "work-orders", "purchase-orders", "purchase-order", "requirements", "costs", "parts"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  };
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="scan-facts">{rows.filter(([, v]) => v !== "" && v != null).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>;
}

function ResultCard({ r }: { r: Result }) {
  return (
    <div className="card scan-card">
      {r.type === "stock" && <StockCard id={r.id} d={r.detail} actions={r.actions} />}
      {r.type === "po" && <PoCard id={r.id} d={r.detail} actions={r.actions} />}
      {r.type === "wo" && <WoCard id={r.id} d={r.detail} actions={r.actions} />}
    </div>
  );
}

const STOCK_ACTIONS: Record<string, string> = { in: "Giriş", out: "Çıkış", count: "Sayım" };

function StockCard({ id, d, actions }: { id: number; d: StockDetail; actions: string[] }) {
  const toast = useToast();
  const done = useDone();
  const [kind, setKind] = useState(actions[0] ?? "");
  const [qty, setQty] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<{ qty: number; unit: string }>(`/stock/${id}/moves`, { kind, qty: numOrNull(qty) ?? 0 }),
    onSuccess: (i) => { toast(`${d.code}: stok ${fmtQty(i.qty)} ${i.unit}`); setQty(""); done(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <>
      <span className="badge">Stok kartı</span>
      <h3 className="mono">{d.code}</h3>
      <Facts rows={[["Ad", d.name], ["Tür", d.kind_label], ["Stok", <b>{fmtQty(d.qty)} {d.unit}</b>], ["Min. stok", d.min_qty ? fmtQty(d.min_qty) : ""], ["Konum", d.location]]} />
      {actions.length > 0 && (
        <div className="scan-act">
          <div className="seg" role="group" aria-label="Hareket">
            {actions.map((a) => <button key={a} type="button" className={kind === a ? "on" : ""} onClick={() => setKind(a)}>{STOCK_ACTIONS[a]}</button>)}
          </div>
          <div className="row">
            <input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} aria-label="Miktar"
              placeholder={kind === "count" ? "Sayılan miktar" : "Miktar"} />
            <button className="btn primary" disabled={save.isPending || numOrNull(qty) === null} onClick={() => save.mutate()}>Kaydet</button>
          </div>
        </div>
      )}
    </>
  );
}

function PoCard({ id, d, actions }: { id: number; d: PoDetail; actions: string[] }) {
  const toast = useToast();
  const done = useDone();
  const canReceive = actions.includes("receive");
  const [qty, setQty] = useState<Record<number, string>>({});
  const picked = d.lines.map((l) => ({ line_id: l.id as number, qty: numOrNull(qty[l.id as number] ?? "") ?? 0 })).filter((l) => l.qty > 0);
  const save = useMutation({
    mutationFn: () => api.post(`/purchase-orders/${id}/receive`, { lines: picked }),
    onSuccess: () => { toast(`${d.no}: mal kabul işlendi`); setQty({}); done(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <>
      <span className="badge">Satın alma siparişi</span>
      <h3>{d.no}</h3>
      <Facts rows={[["Firma", d.firm_name], ["Durum", <span className="badge" style={statusStyle(PO_COLORS[d.status])}>{d.status_label}</span>], ["Termin", fmtDay(d.due_date)]]} />
      {d.lines.map((l) => (
        <div className="scan-line" key={l.id}>
          <div>
            <b className="mono">{l.code || l.description}</b><br />
            <small>{l.code ? `${l.description} · ` : ""}kalan {fmtQty(l.remaining)} {l.unit}</small>
          </div>
          {canReceive && (
            <input inputMode="decimal" value={qty[l.id as number] ?? ""} placeholder={fmtQty(l.remaining)} aria-label={`${l.code} teslim miktarı`}
              onChange={(e) => setQty((q) => ({ ...q, [l.id as number]: e.target.value }))} />
          )}
        </div>
      ))}
      {!d.lines.length && <p className="muted">Açık satır yok.</p>}
      {canReceive && (
        <div className="scan-act">
          <div className="row">
            <button className="btn" onClick={() => setQty(Object.fromEntries(d.lines.map((l) => [l.id as number, String(l.remaining)])))}>Tümünü doldur</button>
            <button className="btn primary" style={{ flex: 1 }} disabled={save.isPending || !picked.length} onClick={() => save.mutate()}>Mal kabul</button>
          </div>
        </div>
      )}
    </>
  );
}

function WoCard({ id, d, actions }: { id: number; d: WoDetail; actions: string[] }) {
  const toast = useToast();
  const done = useDone();
  const [made, setMade] = useState("");
  const [mid, setMid] = useState<number | null>(d.materials[0]?.id ?? null);
  const [issueQty, setIssueQty] = useState("");
  const [warnings, setWarnings] = useState<WoWarning[]>([]);
  const start = useMutation({
    mutationFn: () => api.post(`/work-orders/${id}/status`, { status: "in_progress" }),
    onSuccess: () => { toast(`${d.no} başlatıldı`); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const complete = useMutation({
    mutationFn: () => api.post<WorkOrder & { warnings: WoWarning[] }>(`/work-orders/${id}/complete`, { qty: numOrNull(made) ?? 0 }),
    onSuccess: (w) => { toast(`${w.no}: ${fmtQty(w.done_qty)} / ${fmtQty(w.qty)} üretildi`); setMade(""); setWarnings(w.warnings); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const issue = useMutation({
    mutationFn: () => api.post(`/work-orders/${id}/materials/${mid}/issue`, { qty: numOrNull(issueQty) ?? 0 }),
    onSuccess: () => { toast("Malzeme çıkışı işlendi"); setIssueQty(""); done(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <>
      <span className="badge">İş emri</span>
      <h3>{d.no}</h3>
      <Facts rows={[["Parça", <span className="mono">{d.part_no}</span>], ["Açıklama", d.description], ["Proje", d.project_name],
        ["Durum", <span className="badge" style={statusStyle(WO_COLORS[d.status])}>{d.status_label}</span>],
        ["Üretilen", `${fmtQty(d.done_qty)} / ${fmtQty(d.qty)}`]]} />
      {warnings.length > 0 && <ul className="scan-warn">{warnings.map((w) => <li key={w.code}>{w.message}</li>)}</ul>}
      {actions.includes("start") && (
        <div className="scan-act"><button className="btn" disabled={start.isPending} onClick={() => start.mutate()}>Başlat</button></div>
      )}
      {actions.includes("complete") && (
        <div className="scan-act">
          <div className="row">
            <input inputMode="decimal" value={made} onChange={(e) => setMade(e.target.value)} placeholder={`Üretilen (kalan ${fmtQty(d.remaining)})`} aria-label="Üretilen miktar" />
            <button className="btn primary" disabled={complete.isPending || !numOrNull(made)} onClick={() => complete.mutate()}>Üretim girişi</button>
          </div>
        </div>
      )}
      {actions.includes("issue") && (
        <div className="scan-act">
          <select value={mid ?? ""} onChange={(e) => setMid(Number(e.target.value))} aria-label="Malzeme">
            {d.materials.map((m) => (
              <option key={m.id} value={m.id}>{m.code} · {fmtQty(m.issued_qty)} / {fmtQty(m.planned_qty)} {m.unit}{m.stock_qty != null ? ` · stok ${fmtQty(m.stock_qty)}` : ""}</option>
            ))}
          </select>
          <div className="row">
            <input inputMode="decimal" value={issueQty} onChange={(e) => setIssueQty(e.target.value)} placeholder="Miktar" aria-label="Çıkış miktarı" />
            <button className="btn primary" disabled={issue.isPending || !mid || !numOrNull(issueQty)} onClick={() => issue.mutate()}>Malzeme çıkışı</button>
          </div>
        </div>
      )}
    </>
  );
}
