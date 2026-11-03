import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../api/auth";
import { api } from "../api/client";
import { mobileApp } from "../api/mobile";

const MIN_PASSWORD = 8;

/** Login, plus "Hesap oluştur": the request waits until an admin approves it in Yönetim > Kullanıcılar. */
export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [signupOn, setSignupOn] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<{ signup: boolean }>("/auth/options").then((o) => setSignupOn(o.signup)).catch(() => setSignupOn(false));
  }, []);

  if (user) return <Navigate to="/" replace />;

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
      if (password.length < MIN_PASSWORD) return setErr(`Şifre en az ${MIN_PASSWORD} karakter olmalı.`);
      if (password !== again) return setErr("Şifreler aynı değil.");
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
      setErr(ex instanceof Error ? ex.message : mode === "login" ? "Giriş başarısız" : "Hesap isteği gönderilemedi");
    } finally {
      setBusy(false);
    }
  }

  const signup = mode === "signup";
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Parça Takip ERP</h1>
        {signup && <div className="muted">Hesabınız yönetici onayından sonra açılır.</div>}
        <label>
          Kullanıcı adı
          <input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
            autoCapitalize="none" spellCheck={false} style={{ width: "100%" }} />
        </label>
        {signup && (
          <>
            <label>Ad soyad<input value={fullName} maxLength={128} onChange={(e) => setFullName(e.target.value)} autoComplete="name" style={{ width: "100%" }} /></label>
            <label>E-posta (isteğe bağlı)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" style={{ width: "100%" }} /></label>
          </>
        )}
        <label>
          Şifre{signup && <span className="muted"> (en az {MIN_PASSWORD} karakter)</span>}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={signup ? "new-password" : "current-password"} style={{ width: "100%" }} />
        </label>
        {signup && (
          <label>Şifre (tekrar)<input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" style={{ width: "100%" }} /></label>
        )}
        {info && <div className="ok-box">{info}</div>}
        {err && <div className="error">{err}</div>}
        <button className="btn primary" disabled={busy || !username.trim() || !password}>
          {signup ? (busy ? "Gönderiliyor…" : "Hesap isteği gönder") : busy ? "Giriş yapılıyor…" : "Giriş yap"}
        </button>
        {signupOn && (
          <button type="button" className="btn" onClick={() => switchTo(signup ? "login" : "signup")}>
            {signup ? "Hesabım var, giriş yap" : "Hesap oluştur"}
          </button>
        )}
        {mobileApp() && (
          <button type="button" className="btn" onClick={() => mobileApp()?.changeServer()}>
            Sunucuyu değiştir ({location.host})
          </button>
        )}
        <div className="muted small-note">Sunucu: {location.host}</div>
      </form>
    </div>
  );
}
