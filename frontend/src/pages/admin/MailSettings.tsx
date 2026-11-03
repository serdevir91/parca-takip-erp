import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading } from "./shared";

type Smtp = {
  host: string; port: number; security: "starttls" | "ssl" | "none"; username: string;
  from_addr: string; from_name: string; has_password: boolean; ready: boolean;
};

const PRESETS: { label: string; host: string; port: number; security: Smtp["security"] }[] = [
  { label: "Gmail", host: "smtp.gmail.com", port: 587, security: "starttls" },
  { label: "Outlook / Office 365", host: "smtp.office365.com", port: 587, security: "starttls" },
  { label: "Yandex", host: "smtp.yandex.com", port: 465, security: "ssl" },
  { label: "Yahoo", host: "smtp.mail.yahoo.com", port: 465, security: "ssl" },
];

/** SMTP server used for "E-posta ile gönder" and sign-up notices. */
export default function MailSettingsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["mail", "settings"], queryFn: () => api.get<Smtp>("/mail/settings") });
  const [f, setF] = useState<Smtp | null>(null);
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState("");
  useEffect(() => {
    if (q.data && !f) setF(q.data);
  }, [q.data, f]);

  const save = useMutation({
    mutationFn: () => api.put<Smtp>("/mail/settings", { ...f, password }),
    onSuccess: (s) => {
      setF(s);
      setPassword("");
      qc.setQueryData(["mail", "settings"], s);
      void qc.invalidateQueries({ queryKey: ["mail", "status"] });
      toast("E-posta ayarları kaydedildi");
    },
    onError: (e) => toast(errText(e), true),
  });
  const test = useMutation({
    mutationFn: () => api.post<{ to: string[] }>("/mail/test", { to: testTo }),
    onSuccess: (r) => toast(`Test e-postası gönderildi: ${r.to.join(", ")}`),
    onError: (e) => toast(errText(e), true),
  });

  if (!f) return <Loading error={q.error} loading={q.isLoading} />;
  const set = <K extends keyof Smtp>(k: K, v: Smtp[K]) => setF({ ...f, [k]: v });
  const gmail = f.host.includes("gmail");
  return (
    <div className="card">
      <p className="muted">
        Listeleri ve dosyaları uygulamadan e-postayla göndermek için bir e-posta hesabı girin. Yanıtlar gönderen kullanıcının
        Profilim'deki e-posta adresine gider. {f.ready ? <b className="ok">Durum: hazır</b> : <b className="warn">Durum: ayarlanmamış</b>}
      </p>
      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        <span className="muted">Hazır ayar:</span>
        {PRESETS.map((p) => (
          <button key={p.label} type="button" className="btn small" onClick={() => setF({ ...f, host: p.host, port: p.port, security: p.security })}>{p.label}</button>
        ))}
      </div>
      <div className="adm-form">
        <Field label="SMTP sunucusu"><input value={f.host} onChange={(e) => set("host", e.target.value)} placeholder="smtp.gmail.com" /></Field>
        <div className="row" style={{ gap: 10 }}>
          <Field label="Port"><input type="number" value={f.port} onChange={(e) => set("port", Number(e.target.value) || 587)} style={{ width: 100 }} /></Field>
          <Field label="Güvenlik">
            <select value={f.security} onChange={(e) => set("security", e.target.value as Smtp["security"])}>
              <option value="starttls">STARTTLS (587)</option>
              <option value="ssl">SSL/TLS (465)</option>
              <option value="none">Yok (yalnız iç ağ)</option>
            </select>
          </Field>
        </div>
        <Field label="Kullanıcı adı" hint="Genelde e-posta adresinin kendisi">
          <input value={f.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Şifre" hint={gmail ? "Gmail: Google Hesabı > Güvenlik > 2 adımlı doğrulama > Uygulama şifreleri'nden 16 haneli şifre oluşturun." : f.has_password ? "Kayıtlı şifre korunur; değiştirmek için yenisini yazın." : undefined}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
            placeholder={f.has_password ? "•••••••• (kayıtlı)" : ""} />
        </Field>
        <Field label="Gönderen adresi"><input type="email" value={f.from_addr} onChange={(e) => set("from_addr", e.target.value)} placeholder="erp@firma.com" /></Field>
        <Field label="Gönderen adı"><input value={f.from_name} onChange={(e) => set("from_name", e.target.value)} /></Field>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Kaydediliyor…" : "Kaydet"}</button>
        </div>
        <h4>Test</h4>
        <div className="row">
          <input className="grow" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="Alıcı (boşsa Profilim'deki adresiniz)" />
          <button className="btn" disabled={!f.ready || test.isPending} onClick={() => test.mutate()}>{test.isPending ? "Gönderiliyor…" : "Test e-postası gönder"}</button>
        </div>
      </div>
    </div>
  );
}
