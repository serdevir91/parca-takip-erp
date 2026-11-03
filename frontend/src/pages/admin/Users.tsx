import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth, type Level } from "../../api/auth";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal, fmtDate, roleLabel } from "./shared";

export type AdminUser = {
  id: number; username: string; full_name: string; role: string; role_label: string;
  active: boolean; created_at: string | null;
  /** Admin's per-user overrides; permissions = effective levels (role defaults + overrides). */
  overrides?: Record<string, Level>; permissions?: Record<string, Level>;
};
type Catalog = {
  modules: { key: string; label: string; group: string }[];
  levels: { key: Level; label: string }[];
  role_defaults: Record<string, Record<string, Level>>;
};
type RoleOpt = { value: string; label: string };

const MIN_PASSWORD = 8;
const FALLBACK_ROLES = ["admin", "designer", "planner", "viewer"];

export default function UsersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user: me } = useAuth();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api.get<AdminUser[]>("/admin/users") });
  const roles = useQuery({ queryKey: ["admin", "roles"], queryFn: () => api.get<RoleOpt[]>("/admin/roles"), staleTime: Infinity });
  const roleValues = roles.data?.map((r) => r.value) ?? FALLBACK_ROLES;

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [pwFor, setPwFor] = useState<AdminUser | null>(null);
  const [showInactive, setShowInactive] = useState(true);

  const refresh = () => qc.invalidateQueries({ queryKey: ["admin", "users"] });
  const toggleActive = useMutation({
    mutationFn: (u: AdminUser) => api.put<AdminUser>(`/admin/users/${u.id}`, { active: !u.active }),
    onSuccess: (u) => {
      toast(u.active ? `${u.username} etkinleştirildi` : `${u.username} pasif yapıldı`);
      void refresh();
    },
    onError: (e) => toast(errText(e), true),
  });

  const list = (users.data ?? []).filter((u) => showInactive || u.active);
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="btn primary" onClick={() => setCreating(true)}>+ Yeni kullanıcı</button>
        <label className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Pasif kullanıcıları göster
        </label>
        <span className="muted">{(users.data?.length ?? 0).toLocaleString("tr-TR")} kullanıcı</span>
      </div>
      <Loading error={users.error} loading={users.isLoading} />
      {users.data && (
        <div className="adm-scroll">
          <table className="simple">
            <thead>
              <tr><th>Kullanıcı adı</th><th>Ad Soyad</th><th>Rol</th><th>Durum</th><th>Oluşturulma</th><th></th></tr>
            </thead>
            <tbody>
              {list.map((u) => {
                const self = me?.username === u.username;
                return (
                  <tr key={u.id} style={u.active ? undefined : { opacity: 0.6 }}>
                    <td><b>{u.username}</b>{self && <span className="badge" style={{ marginLeft: 6 }}>siz</span>}</td>
                    <td>{u.full_name}</td>
                    <td>
                      {roleLabel(u.role)}
                      {!!Object.keys(u.overrides ?? {}).length && u.role !== "admin" && (
                        <span className="badge" style={{ marginLeft: 6 }} title="Bu kullanıcıya rol dışında özel yetki verilmiş">özel yetki</span>
                      )}
                    </td>
                    <td>{u.active ? <span className="badge new">Aktif</span> : <span className="badge">Pasif</span>}</td>
                    <td className="muted">{fmtDate(u.created_at)}</td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <button className="btn small" onClick={() => setEditing(u)}>Düzenle</button>
                        <button className="btn small" onClick={() => setPwFor(u)}>Şifre sıfırla</button>
                        <button className="btn small" disabled={self || toggleActive.isPending}
                          title={self ? "Kendi hesabınızı pasif yapamazsınız" : undefined}
                          onClick={() => toggleActive.mutate(u)}>{u.active ? "Pasif yap" : "Etkinleştir"}</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ marginTop: 10 }}>
        Kullanıcılar silinmez; denetim kaydında adları korunur. Pasif kullanıcılar giriş yapamaz.
      </p>
      {creating && <UserForm roles={roleValues} onClose={() => setCreating(false)} onSaved={refresh} />}
      {editing && <UserForm roles={roleValues} user={editing} self={me?.username === editing.username}
        onClose={() => setEditing(null)} onSaved={refresh} />}
      {pwFor && <PasswordForm user={pwFor} onClose={() => setPwFor(null)} />}
    </div>
  );
}

function UserForm({ user, roles, self, onClose, onSaved }: {
  user?: AdminUser; roles: string[]; self?: boolean; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [role, setRole] = useState(user?.role ?? "viewer");
  const [active, setActive] = useState(user?.active ?? true);
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [overrides, setOverrides] = useState<Record<string, Level>>(user?.overrides ?? {});

  const save = useMutation({
    mutationFn: () =>
      user
        ? api.put<AdminUser>(`/admin/users/${user.id}`, { full_name: fullName, role, active, permissions: overrides })
        : api.post<AdminUser>("/admin/users", { username: username.trim(), password, full_name: fullName, role, permissions: overrides }),
    onSuccess: (u) => {
      toast(user ? `${u.username} güncellendi` : `${u.username} oluşturuldu`);
      onSaved();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });

  const pwErr = !user && (password.length < MIN_PASSWORD ? `Şifre en az ${MIN_PASSWORD} karakter olmalı` : password !== password2 ? "Şifreler aynı değil" : null);
  const invalid = (!user && !username.trim()) || !!pwErr;
  return (
    <Modal wide title={user ? `Kullanıcıyı düzenle: ${user.username}` : "Yeni kullanıcı"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={invalid || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Kaydediliyor…" : "Kaydet"}
        </button>
      </>}>
      <div className="adm-form">
        <Field label="Kullanıcı adı">
          <input value={username} disabled={!!user} autoFocus={!user} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Ad Soyad">
          <input value={fullName} autoFocus={!!user} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label="Rol" hint={self ? "Kendi rolünüzü değiştirirseniz yönetim ekranına erişiminizi kaybedebilirsiniz." : undefined}>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
          </select>
        </Field>
        {user && (
          <label className="row" style={{ gap: 6 }} title={self ? "Kendi hesabınızı pasif yapamazsınız" : undefined}>
            <input type="checkbox" checked={active} disabled={self} onChange={(e) => setActive(e.target.checked)} /> Aktif
            {self && <span className="muted">(kendi hesabınız pasif yapılamaz)</span>}
          </label>
        )}
        {!user && (
          <>
            <Field label="Şifre"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></Field>
            <Field label="Şifre (tekrar)"><input type="password" value={password2} onChange={(e) => setPassword2(e.target.value)} autoComplete="new-password" /></Field>
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
      toast(`${user.username} için şifre sıfırlandı`);
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const err = pw.length < MIN_PASSWORD ? `Şifre en az ${MIN_PASSWORD} karakter olmalı` : pw !== pw2 ? "Şifreler aynı değil" : null;
  return (
    <Modal title={`Şifre sıfırla: ${user.username}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={!!err || save.isPending} onClick={() => save.mutate()}>Şifreyi kaydet</button>
      </>}>
      <div className="adm-form">
        <Field label="Yeni şifre"><input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
        <Field label="Yeni şifre (tekrar)"><input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></Field>
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
  const label = (lv: Level | undefined) => levels.find((l) => l.key === lv)?.label ?? "Yok";
  const set = (key: string, lv: string) => {
    const next = { ...value };
    if (lv === "") delete next[key];
    else next[key] = lv as Level;
    onChange(next);
  };
  const setAll = (lv: Level | "") => onChange(lv === "" ? {} : Object.fromEntries(modules.filter((m) => m.key !== "admin").map((m) => [m.key, lv])));
  const groups = [...new Set(modules.map((m) => m.group))];
  if (role === "admin") {
    return <p className="muted perm-note">Admin rolü tüm modüllere tam erişir; ayrı yetki gerekmez.</p>;
  }
  return (
    <div className="perm">
      <div className="row" style={{ justifyContent: "space-between", margin: "16px 0 6px" }}>
        <b>Modül yetkileri</b>
        <div className="row" style={{ gap: 4 }}>
          <span className="muted">Hepsini:</span>
          <button className="btn small" type="button" onClick={() => setAll("")}>Rol varsayılanı</button>
          <button className="btn small" type="button" onClick={() => setAll("view")}>Görüntüle</button>
          <button className="btn small" type="button" onClick={() => setAll("edit")}>Düzenle</button>
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
                      title="Rolün varsayılan yetkisi">Rol ({label(defaults[m.key])})</button>
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
      <p className="muted">Değişiklik kullanıcının açık ekranına birkaç saniye içinde yansır; yeniden giriş gerekmez.</p>
    </div>
  );
}
