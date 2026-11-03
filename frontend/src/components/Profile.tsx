import { useState, type FormEvent } from "react";
import { api, setToken } from "../api/client";
import { useAuth, type User } from "../api/auth";
import { Field, Modal, roleLabel } from "../pages/admin/shared";
import { errText, useToast } from "./Toast";

const MIN_PASSWORD = 8;

/** Own profile: display name and password. User name, role and permissions stay with the admin. */
export default function Profile({ onClose }: { onClose: () => void }) {
  const { user, reloadUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.full_name ?? "");
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pwWanted = !!(oldPw || newPw || again);
  const pwProblem = !pwWanted ? ""
    : !oldPw ? "Mevcut şifrenizi yazın."
    : newPw.length < MIN_PASSWORD ? `Yeni şifre en az ${MIN_PASSWORD} karakter olmalı.`
    : newPw !== again ? "Yeni şifreler aynı değil."
    : "";
  const nameChanged = name.trim() !== (user?.full_name ?? "");

  async function save(e: FormEvent) {
    e.preventDefault();
    if (pwProblem) return setErr(pwProblem);
    setBusy(true);
    setErr("");
    try {
      if (nameChanged) await api.put<User>("/auth/me", { full_name: name.trim() });
      if (pwWanted) {
        const r = await api.post<{ access_token: string }>("/auth/password", { old_password: oldPw, new_password: newPw });
        setToken(r.access_token); // the old token is revoked; other devices must log in again
      }
      reloadUser();
      toast(pwWanted ? "Profil ve şifre kaydedildi. Diğer cihazlarda yeniden giriş gerekir." : "Profil kaydedildi");
      onClose();
    } catch (ex) {
      setErr(errText(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Profilim" onClose={onClose}>
      <form className="profile-form" onSubmit={save}>
        <div className="muted">
          Kullanıcı adı: <b>{user?.username}</b> · Rol: {roleLabel(user?.role ?? "")}
        </div>
        <Field label="Ad soyad">
          <input value={name} maxLength={128} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </Field>
        <h4>Şifre değiştir</h4>
        <Field label="Mevcut şifre">
          <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
        </Field>
        <Field label="Yeni şifre" hint={`En az ${MIN_PASSWORD} karakter`}>
          <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label="Yeni şifre (tekrar)">
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
        </Field>
        {err && <div className="error">{err}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>Vazgeç</button>
          <button className="btn primary" disabled={busy || (!nameChanged && !pwWanted)}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
