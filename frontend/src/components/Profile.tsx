import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { sys } from "../api/system";
import { useAuth, type User } from "../api/auth";
import { Field, Modal, roleLabel } from "../pages/admin/shared";
import { errText, useToast } from "./Toast";
import { tx } from "../api/i18n";


/** Own profile: display name, e-mail and password. User name, role and permissions stay with the admin. */
export default function Profile({ onClose }: { onClose: () => void }) {
  const { user, reloadUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pwWanted = !!(oldPw || newPw || again);
  const pwProblem = !pwWanted ? ""
    : !oldPw ? tx("Mevcut şifrenizi yazın.")
    : newPw.length < sys.password_min ? tx("Yeni şifre en az {0} karakter olmalı.", sys.password_min)
    : newPw !== again ? tx("Yeni şifreler aynı değil.")
    : "";
  const nameChanged = name.trim() !== (user?.full_name ?? "") || email.trim() !== (user?.email ?? "");

  async function save(e: FormEvent) {
    e.preventDefault();
    if (pwProblem) return setErr(pwProblem);
    setBusy(true);
    setErr("");
    try {
      if (nameChanged) await api.put<User>("/auth/me", { full_name: name.trim(), email: email.trim() });
      if (pwWanted) {
        await api.post("/auth/password", { old_password: oldPw, new_password: newPw });
      }
      reloadUser();
      toast(pwWanted ? tx("Profil ve şifre kaydedildi. Diğer cihazlarda yeniden giriş gerekir.") : tx("Profil kaydedildi"));
      onClose();
    } catch (ex) {
      setErr(errText(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={tx("Profilim")} onClose={onClose}>
      <form className="profile-form" onSubmit={save}>
        <div className="muted">
          {tx("Kullanıcı adı:")}{" "}<b>{user?.username}</b>{" "}{tx("· Rol: {0}", roleLabel(user?.role ?? ""))}
        </div>
        <Field label={tx("Ad soyad")}>
          <input value={name} maxLength={128} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </Field>
        <Field label={tx("E-posta")} hint={tx("Gönderdiğiniz e-postalara verilen yanıtlar bu adrese gelir.")}>
          <input type="email" value={email} maxLength={200} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </Field>
        <h4>{tx("Şifre değiştir")}</h4>
        <Field label={tx("Mevcut şifre")}>
          <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
        </Field>
        <Field label={tx("Yeni şifre")} hint={tx("En az {0} karakter", sys.password_min)}>
          <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label={tx("Yeni şifre (tekrar)")}>
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
        </Field>
        {err && <div className="error">{err}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
          <button className="btn primary" disabled={busy || (!nameChanged && !pwWanted)}>
            {busy ? tx("Kaydediliyor…") : tx("Kaydet")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
