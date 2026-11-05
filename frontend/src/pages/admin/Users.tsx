import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { sys } from "../../api/system";
import { useAuth, type Level } from "../../api/auth";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal, fmtDate, roleLabel } from "./shared";
import { LOCALE, tx } from "../../api/i18n";

export type AdminUser = {
  id: number; username: string; full_name: string; email: string; role: string; role_label: string;
  active: boolean; pending?: boolean; created_at: string | null;
  /** Admin's per-user overrides; permissions = effective levels (role defaults + overrides). */
  overrides?: Record<string, Level>; permissions?: Record<string, Level>;
};
type Catalog = {
  modules: { key: string; label: string; group: string }[];
  levels: { key: Level; label: string }[];
  role_defaults: Record<string, Record<string, Level>>;
};
type RoleOpt = { value: string; label: string };

const FALLBACK_ROLES = ["admin", "designer", "planner", "viewer"];

export default function UsersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user: me } = useAuth();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api.get<AdminUser[]>("/admin/users") });
  const roles = useQuery({ queryKey: ["admin", "roles"], queryFn: () => api.get<RoleOpt[]>("/admin/roles"), staleTime: Infinity });
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api.get<{ signup?: { enabled: boolean } }>("/admin/settings") });
  const roleValues = roles.data?.map((r) => r.value) ?? FALLBACK_ROLES;

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [approving, setApproving] = useState<AdminUser | null>(null);
  const [pwFor, setPwFor] = useState<AdminUser | null>(null);
  const [showInactive, setShowInactive] = useState(true);
  const [q, setQ] = useState("");

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "users"] });
    void qc.invalidateQueries({ queryKey: ["admin", "signups"] });
  };
  const toggleActive = useMutation({
    mutationFn: (u: AdminUser) => api.put<AdminUser>(`/admin/users/${u.id}`, { active: !u.active }),
    onSuccess: (u) => {
      toast(u.active ? tx("{0} etkinleştirildi", u.username) : tx("{0} pasif yapıldı", u.username));
      refresh();
    },
    onError: (e) => toast(errText(e), true),
  });
  const reject = useMutation({
    mutationFn: (u: AdminUser) => api.del(`/admin/users/${u.id}/signup`),
    onSuccess: (_, u) => {
      toast(tx("{0} isteği reddedildi", u.username));
      refresh();
    },
    onError: (e) => toast(errText(e), true),
  });
  const signupOn = settings.data?.signup?.enabled ?? false;
  const setSignup = useMutation({
    mutationFn: (enabled: boolean) => api.put("/admin/settings/signup", { value: { enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "settings"] }),
    onError: (e) => toast(errText(e), true),
  });

  const all = users.data ?? [];
  const pending = all.filter((u) => u.pending);
  const needle = q.trim().toLocaleLowerCase("tr");
  const list = all.filter((u) => !u.pending && (showInactive || u.active) &&
    (!needle || `${u.username} ${u.full_name} ${u.email}`.toLocaleLowerCase("tr").includes(needle)));
  return (
    <div className="card">
      {pending.length > 0 && (
        <div className="signup-box">
          <b>{tx("Onay bekleyen hesap istekleri ({0})", pending.length)}</b>
          {pending.map((u) => (
            <div key={u.id} className="ucard pending">
              <div className="ucard-main">
                <b>{u.full_name || u.username}</b>
                <span className="muted">@{u.username}{u.email && ` · ${u.email}`} · {fmtDate(u.created_at)}</span>
              </div>
              <div className="ucard-actions">
                <button className="btn primary small" onClick={() => setApproving(u)}>{tx("Onayla ve yetki ver")}</button>
                <button className="btn danger small" disabled={reject.isPending}
                  onClick={() => confirm(tx("{0} hesap isteği reddedilsin mi?", u.username)) && reject.mutate(u)}>{tx("Reddet")}</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="btn primary" onClick={() => setCreating(true)}>{tx("+ Yeni kullanıcı")}</button>
        <input className="grow" placeholder={tx("Ara: ad, kullanıcı adı, e-posta")} value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 160 }} />
        <label className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />{" "}{tx("Pasifleri göster")}
        </label>
        <label className="row" style={{ gap: 4 }} title={tx("Kapalıysa hesapları yalnızca yönetici açar")}>
          <input type="checkbox" checked={signupOn} disabled={setSignup.isPending || !settings.data}
            onChange={(e) => setSignup.mutate(e.target.checked)} />{" "}{tx("Girişte “Hesap oluştur” göster")}
        </label>
        <span className="muted">{tx("{0} kullanıcı", list.length.toLocaleString(LOCALE))}</span>
      </div>
      <Loading error={users.error} loading={users.isLoading} />
      <div className="ulist">
        {list.map((u) => {
          const self = me?.username === u.username;
          return (
            <div key={u.id} className="ucard" style={u.active ? undefined : { opacity: 0.6 }}>
              <div className="ucard-main">
                <b>
                  {u.full_name || u.username}
                  {self && <span className="badge" style={{ marginLeft: 6 }}>{tx("siz")}</span>}
                </b>
                <span className="muted">@{u.username}{u.email && ` · ${u.email}`}</span>
              </div>
              <div className="ucard-meta">
                <span className="badge">{roleLabel(u.role)}</span>
                {!!Object.keys(u.overrides ?? {}).length && u.role !== "admin" && (
                  <span className="badge" title={tx("Bu kullanıcıya rol dışında özel yetki verilmiş")}>{tx("özel yetki")}</span>
                )}
                {u.active ? <span className="badge new">{tx("Aktif")}</span> : <span className="badge">{tx("Pasif")}</span>}
                <span className="muted">{fmtDate(u.created_at)}</span>
              </div>
              <div className="ucard-actions">
                <button className="btn small" onClick={() => setEditing(u)}>{tx("Düzenle / yetkiler")}</button>
                <button className="btn small" onClick={() => setPwFor(u)}>{tx("Şifre sıfırla")}</button>
                <button className="btn small" disabled={self || toggleActive.isPending}
                  title={self ? tx("Kendi hesabınızı pasif yapamazsınız") : undefined}
                  onClick={() => toggleActive.mutate(u)}>{u.active ? tx("Pasif yap") : tx("Etkinleştir")}</button>
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted" style={{ marginTop: 10 }}>
        {tx("Kullanıcılar silinmez; denetim kaydında adları korunur. Pasif kullanıcılar giriş yapamaz.")}
      </p>
      {creating && <UserForm roles={roleValues} onClose={() => setCreating(false)} onSaved={refresh} />}
      {editing && <UserForm roles={roleValues} user={editing} self={me?.username === editing.username}
        onClose={() => setEditing(null)} onSaved={refresh} />}
      {approving && <UserForm roles={roleValues} user={approving} approve onClose={() => setApproving(null)} onSaved={refresh} />}
      {pwFor && <PasswordForm user={pwFor} onClose={() => setPwFor(null)} />}
    </div>
  );
}

function UserForm({ user, roles, self, approve, onClose, onSaved }: {
  user?: AdminUser; roles: string[]; self?: boolean; approve?: boolean; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState(user?.role ?? "viewer");
  const [active, setActive] = useState(user?.active ?? true);
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [overrides, setOverrides] = useState<Record<string, Level>>(user?.overrides ?? {});

  const save = useMutation({
    mutationFn: async () => {
      if (approve && user) {
        await api.post<AdminUser>(`/admin/users/${user.id}/approve`, { role, permissions: overrides, full_name: fullName });
        return email !== user.email ? api.put<AdminUser>(`/admin/users/${user.id}`, { email }) : { ...user, active: true };
      }
      return user
        ? api.put<AdminUser>(`/admin/users/${user.id}`, { full_name: fullName, email, role, active, permissions: overrides })
        : api.post<AdminUser>("/admin/users", { username: username.trim(), password, full_name: fullName, email, role, permissions: overrides });
    },
    onSuccess: (u) => {
      toast(approve ? tx("{0} onaylandı; artık giriş yapabilir", u.username) : user ? tx("{0} güncellendi", u.username) : tx("{0} oluşturuldu", u.username));
      onSaved();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });

  const pwErr = !user && (password.length < sys.password_min ? tx("Şifre en az {0} karakter olmalı", sys.password_min) : password !== password2 ? tx("Şifreler aynı değil") : null);
  const invalid = (!user && !username.trim()) || !!pwErr;
  return (
    <Modal wide title={approve ? tx("Hesap isteğini onayla: {0}", user?.username) : user ? tx("Kullanıcıyı düzenle: {0}", user.username) : tx("Yeni kullanıcı")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={invalid || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? tx("Kaydediliyor…") : approve ? tx("Onayla") : tx("Kaydet")}
        </button>
      </>}>
      <div className="adm-form">
        <Field label={tx("Kullanıcı adı")}>
          <input value={username} disabled={!!user} autoFocus={!user} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </Field>
        <Field label={tx("Ad Soyad")}>
          <input value={fullName} autoFocus={!!user} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label={tx("E-posta")} hint={tx("Listeler bu adrese gönderilebilir; hesap istekleri yöneticilere buradan bildirilir.")}>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
        </Field>
        <Field label={tx("Rol")} hint={self ? tx("Kendi rolünüzü değiştirirseniz yönetim ekranına erişiminizi kaybedebilirsiniz.") : undefined}>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
          </select>
        </Field>
        {approve && <p className="muted">{tx("Rolü ve modül yetkilerini seçip onaylayın; kullanıcı hemen giriş yapabilir.")}</p>}
        {user && !approve && (
          <label className="row" style={{ gap: 6 }} title={self ? tx("Kendi hesabınızı pasif yapamazsınız") : undefined}>
            <input type="checkbox" checked={active} disabled={self} onChange={(e) => setActive(e.target.checked)} />{" "}{tx("Aktif")}
            {self && <span className="muted">{tx("(kendi hesabınız pasif yapılamaz)")}</span>}
          </label>
        )}
        {!user && (
          <>
            <Field label={tx("Şifre")}><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></Field>
            <Field label={tx("Şifre (tekrar)")}><input type="password" value={password2} onChange={(e) => setPassword2(e.target.value)} autoComplete="new-password" /></Field>
            {password && pwErr && <div className="error">{pwErr}</div>}
          </>
        )}
      </div>
      <PermissionMatrix role={role} value={overrides} onChange={setOverrides} />
    </Modal>
  );
}

function PasswordForm({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const toast = useToast();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const save = useMutation({
    mutationFn: () => api.post(`/admin/users/${user.id}/password`, { password: pw }),
    onSuccess: () => {
      toast(tx("{0} için şifre sıfırlandı", user.username));
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const err = pw.length < sys.password_min ? tx("Şifre en az {0} karakter olmalı", sys.password_min) : pw !== pw2 ? tx("Şifreler aynı değil") : null;
  return (
    <Modal title={tx("Şifre sıfırla: {0}", user.username)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={!!err || save.isPending} onClick={() => save.mutate()}>{tx("Şifreyi kaydet")}</button>
      </>}>
      <div className="adm-form">
        <Field label={tx("Yeni şifre")}><input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
        <Field label={tx("Yeni şifre (tekrar)")}><input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></Field>
        {pw && err && <div className="error">{err}</div>}
      </div>
    </Modal>
  );
}

/** Per-module access: "Rol varsayılanı" follows the role; any other choice overrides it for this user only. */
function PermissionMatrix({ role, value, onChange }: { role: string; value: Record<string, Level>; onChange: (v: Record<string, Level>) => void }) {
  const cat = useQuery({ queryKey: ["admin", "permissions"], queryFn: () => api.get<Catalog>("/admin/permissions"), staleTime: Infinity });
  if (!cat.data) return <Loading error={cat.error} loading={cat.isLoading} />;
  const { modules, levels, role_defaults } = cat.data;
  const defaults = role_defaults[role] ?? {};
  const label = (lv: Level | undefined) => levels.find((l) => l.key === lv)?.label ?? tx("Yok");
  const set = (key: string, lv: string) => {
    const next = { ...value };
    if (lv === "") delete next[key];
    else next[key] = lv as Level;
    onChange(next);
  };
  const setAll = (lv: Level | "") => onChange(lv === "" ? {} : Object.fromEntries(modules.filter((m) => m.key !== "admin").map((m) => [m.key, lv])));
  const groups = [...new Set(modules.map((m) => m.group))];
  if (role === "admin") {
    return <p className="muted perm-note">{tx("Admin rolü tüm modüllere tam erişir; ayrı yetki gerekmez.")}</p>;
  }
  return (
    <div className="perm">
      <div className="row" style={{ justifyContent: "space-between", margin: "16px 0 6px" }}>
        <b>{tx("Modül yetkileri")}</b>
        <div className="row" style={{ gap: 4 }}>
          <span className="muted">{tx("Hepsini:")}</span>
          <button className="btn small" type="button" onClick={() => setAll("")}>{tx("Rol varsayılanı")}</button>
          <button className="btn small" type="button" onClick={() => setAll("view")}>{tx("Görüntüle")}</button>
          <button className="btn small" type="button" onClick={() => setAll("edit")}>{tx("Düzenle")}</button>
        </div>
      </div>
      <div className="perm-grid">
        {groups.map((g) => (
          <div key={g} className="perm-group">
            <div className="perm-title">{g}</div>
            {modules.filter((m) => m.group === g).map((m) => {
              const own = value[m.key];
              const eff = own ?? defaults[m.key] ?? "none";
              return (
                <div key={m.key} className="perm-row">
                  <span>{m.label}</span>
                  <div className="seg small" role="radiogroup" aria-label={m.label}>
                    <button type="button" className={own === undefined ? "on" : ""} onClick={() => set(m.key, "")}
                      title={tx("Rolün varsayılan yetkisi")}>{tx("Rol ({0})", label(defaults[m.key]))}</button>
                    {levels.map((l) => (
                      <button key={l.key} type="button" className={own === l.key ? `on lv-${l.key}` : ""} onClick={() => set(m.key, l.key)}>{l.label}</button>
                    ))}
                  </div>
                  <span className={`perm-eff lv-${eff}`}>{label(eff)}</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <p className="muted">{tx("Değişiklik kullanıcının açık ekranına birkaç saniye içinde yansır; yeniden giriş gerekmez.")}</p>
    </div>
  );
}
