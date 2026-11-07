import { useState, type FormEvent } from "react";
import { DesktopMenu } from "../components/DesktopMenu";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../api/auth";
import { api } from "../api/client";
import { mobileApp } from "../api/mobile";
import BrandMark from "../components/BrandMark";
import { useBrand } from "../api/system";
import LangSelect from "../components/LangSelect";
import { tx } from "../api/i18n";

/** Login, plus "Hesap oluştur": the request waits until an admin approves it in Yönetim > Kullanıcılar. */
export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [mode, setMode] = useState<"login" | "signup">("login");
  const brand = useBrand();
  const signupOn = brand.options?.signup ?? false;
  const minPw = brand.options?.password_min ?? 8;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  function switchTo(m: "login" | "signup") {
    setMode(m);
    setErr("");
    setInfo("");
    setPassword("");
    setAgain("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (mode === "signup") {
      if (password.length < minPw) return setErr(tx("Şifre en az {0} karakter olmalı.", minPw));
      if (password !== again) return setErr(tx("Şifreler aynı değil."));
    }
    setBusy(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
        nav("/", { replace: true });
      } else {
        const r = await api.post<{ message: string }>("/auth/register", {
          username: username.trim(), full_name: fullName.trim(), email: email.trim(), password,
        });
        switchTo("login");
        setInfo(r.message);
      }
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : mode === "login" ? tx("Giriş başarısız") : tx("Hesap isteği gönderilemedi"));
    } finally {
      setBusy(false);
    }
  }

  const signup = mode === "signup";
  return (
    <div className="login">
      <div className="login-desk"><LangSelect /><DesktopMenu /></div>
      <form className="card" onSubmit={submit}>
        <h1 className="login-brand"><span className="brand-logo"><BrandMark size={22} logo={brand.logo} /></span>{brand.name}</h1>
        {signup && <div className="muted">{tx("Hesabınız yönetici onayından sonra açılır.")}</div>}
        <label>
          {tx("Kullanıcı adı")}
          <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
            autoCapitalize="none" spellCheck={false} style={{ width: "100%" }} />
        </label>
        {signup && (
          <>
            <label>{tx("Ad soyad")}<input value={fullName} maxLength={128} onChange={(e) => setFullName(e.target.value)} autoComplete="name" style={{ width: "100%" }} /></label>
            <label>{tx("E-posta (isteğe bağlı)")}<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" style={{ width: "100%" }} /></label>
          </>
        )}
        <label>
          {tx("Şifre")}{signup && <span className="muted">{" "}{tx("(en az {0} karakter)", minPw)}</span>}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={signup ? "new-password" : "current-password"} style={{ width: "100%" }} />
        </label>
        {signup && (
          <label>{tx("Şifre (tekrar)")}<input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" style={{ width: "100%" }} /></label>
        )}
        {info && <div className="ok-box">{info}</div>}
        {err && <div className="error">{err}</div>}
        <button className="btn primary" disabled={busy || !username.trim() || !password}>
          {signup ? (busy ? tx("Gönderiliyor…") : tx("Hesap isteği gönder")) : busy ? tx("Giriş yapılıyor…") : tx("Giriş yap")}
        </button>
        {signupOn && (
          <button type="button" className="btn" onClick={() => switchTo(signup ? "login" : "signup")}>
            {signup ? tx("Hesabım var, giriş yap") : tx("Hesap oluştur")}
          </button>
        )}
        {mobileApp() && (
          <button type="button" className="btn" onClick={() => mobileApp()?.changeServer()}>
            {tx("Sunucuyu değiştir ({0})", location.host)}
          </button>
        )}
        <div className="muted small-note">{tx("Sunucu: {0}", location.host)}</div>
      </form>
    </div>
  );
}
