import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../api/auth";
import { mobileApp } from "../api/mobile";

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await login(username.trim(), password);
      nav("/", { replace: true });
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Giriş başarısız");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Parça Takip ERP</h1>
        <label>Kullanıcı adı<input autoFocus value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: "100%" }} /></label>
        <label>Şifre<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ width: "100%" }} /></label>
        {err && <div className="error">{err}</div>}
        <button className="btn primary" disabled={busy || !username || !password}>{busy ? "Giriş yapılıyor…" : "Giriş yap"}</button>
        {mobileApp() && (
          <button type="button" className="btn" onClick={() => mobileApp()?.changeServer()}>
            Sunucuyu değiştir ({location.host})
          </button>
        )}
      </form>
    </div>
  );
}
