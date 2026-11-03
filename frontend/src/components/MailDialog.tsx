import { useQuery } from "@tanstack/react-query";
import { Mail, Share2 } from "lucide-react";
import { useState } from "react";
import { api, ApiError, getToken, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { mobileApp } from "../api/mobile";
import { Field, Modal } from "../pages/admin/shared";
import { errText, useToast } from "./Toast";

/** A file to attach: fetched from the API (`path`, e.g. an Excel export) or built by the page (`blob`). */
export type MailFile = { name: string; path?: string; blob?: Blob };

type Recipient = { name: string; email: string; kind: string };

async function fileBlob(f: MailFile): Promise<Blob> {
  if (f.blob) return f.blob;
  const token = getToken();
  const res = await fetch(`/api${f.path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `${f.name} hazırlanamadı (${res.status})`);
  return res.blob();
}

function toBase64(b: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(b);
  });
}

/** Phone share sheet (Android app bridge, or the browser's Web Share). False when this device cannot share. */
export async function shareFiles(files: MailFile[], title: string): Promise<boolean> {
  const app = mobileApp();
  if (app?.share && app.shareData) {
    const f = files[0];
    if (f.path) app.share(`${location.origin}/api${f.path}`, f.name, getToken() ?? "");
    else app.shareData(await toBase64(f.blob!), f.name, f.blob!.type || "application/octet-stream");
    return true;
  }
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean };
  if (!nav.share || !nav.canShare) return false;
  const list = await Promise.all(files.map(async (f) => new File([await fileBlob(f)], f.name, { type: f.blob?.type })));
  if (!nav.canShare({ files: list })) return false;
  try {
    await nav.share({ files: list, title });
  } catch (e) {
    if ((e as Error).name !== "AbortError") throw e;
  }
  return true;
}

export const canShareFromDevice = () =>
  !!(mobileApp()?.shareData || ((navigator as Navigator & { canShare?: unknown }).canShare && /Android|iPhone|iPad/i.test(navigator.userAgent)));

/** "E-posta ile gönder": recipients (with suggestions), subject, message; the files go as attachments. */
export default function MailDialog({ files, subject, body = "", onClose }: {
  files: MailFile[]; subject: string; body?: string; onClose: () => void;
}) {
  const toast = useToast();
  const { user } = useAuth();
  const status = useQuery({ queryKey: ["mail", "status"], queryFn: () => api.get<{ ready: boolean }>("/mail/status"), staleTime: 60_000 });
  const recips = useQuery({ queryKey: ["mail", "recipients"], queryFn: () => api.get<Recipient[]>("/mail/recipients"), staleTime: 60_000 });
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subj, setSubj] = useState(subject);
  const [text, setText] = useState(body);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const ready = status.data?.ready;
  const add = (email: string) => {
    const cur = to.split(/[,;]\s*/).map((x) => x.trim()).filter(Boolean);
    if (!cur.includes(email)) setTo([...cur, email].join(", "));
  };

  async function send() {
    setBusy(true);
    setErr("");
    try {
      const form = new FormData();
      form.append("to", to);
      form.append("cc", cc);
      form.append("subject", subj);
      form.append("body", text);
      for (const f of files) form.append("files", await fileBlob(f), f.name);
      await upload("/mail/send", form);
      toast(`E-posta gönderildi: ${to}`);
      onClose();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    try {
      if (!(await shareFiles(files, subj))) toast("Bu cihaz dosya paylaşmayı desteklemiyor", true);
    } catch (e) {
      toast(errText(e), true);
    }
  }

  const suggestions = (recips.data ?? []).filter((r) => !to.includes(r.email)).slice(0, 12);
  return (
    <Modal title="E-posta ile gönder" onClose={onClose}
      footer={<>
        {canShareFromDevice() && (
          <button className="btn" onClick={() => void share()} title="Gmail, WhatsApp, Drive… ile paylaş">
            <Share2 size={15} /> Telefonla paylaş
          </button>
        )}
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={!ready || busy || !to.trim()} onClick={() => void send()}>
          <Mail size={15} /> {busy ? "Gönderiliyor…" : "Gönder"}
        </button>
      </>}>
      <div className="adm-form">
        {status.data && !ready && (
          <div className="warn">
            E-posta sunucusu ayarlanmamış.{" "}
            {user?.role === "admin" ? "Yönetim > E-posta sekmesinden ayarlayın." : "Yöneticinizden Yönetim > E-posta ayarını yapmasını isteyin."}
            {canShareFromDevice() && " Şimdilik “Telefonla paylaş” ile gönderebilirsiniz."}
          </div>
        )}
        <Field label="Alıcı" hint="Birden fazla adresi virgülle ayırın">
          <input type="email" multiple autoFocus value={to} onChange={(e) => setTo(e.target.value)} placeholder="ornek@firma.com" />
        </Field>
        {suggestions.length > 0 && (
          <div className="chips">
            {suggestions.map((r) => (
              <button key={`${r.kind}-${r.email}`} type="button" className="chip" onClick={() => add(r.email)} title={r.email}>
                + {r.name} <span className="muted">({r.kind})</span>
              </button>
            ))}
          </div>
        )}
        <Field label="Bilgi (CC)"><input type="email" multiple value={cc} onChange={(e) => setCc(e.target.value)} /></Field>
        <Field label="Konu"><input value={subj} maxLength={200} onChange={(e) => setSubj(e.target.value)} /></Field>
        <Field label="Mesaj"><textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} /></Field>
        <div className="muted">Ek: {files.map((f) => f.name).join(", ")}</div>
        {err && <div className="error">{err}</div>}
      </div>
    </Modal>
  );
}
