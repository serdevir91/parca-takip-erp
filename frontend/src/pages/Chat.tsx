import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, CheckCheck, Download, FileText, MessageCircle, Paperclip, Plus, Search, Send, Settings2, Trash2,
  User as UserIcon, Users, X,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { fmtBytes, isImageFile, makeThumb } from "../api/images";
import { Page } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import Thumb from "../components/viewer/Thumb";
import Viewer, { type ViewItem } from "../components/viewer/Viewer";
import { Modal } from "./admin/shared";

export type ChatState = { key: string; unread: number; last_id: number };
type ChatUser = { id: number; name: string; username: string };
type Member = ChatUser & { is_admin: boolean; active: boolean };
type Room = {
  id: number; kind: "direct" | "group"; name: string; is_admin: boolean; members: Member[];
  last_message: string; last_at: string | null; last_id: number; unread: number; created_by: number | null;
};
type FileInfo = { name: string; size: number; type: string; image: boolean };
type Msg = {
  id: number; room_id: number; user_id: number | null; user_name: string; kind: "text" | "system";
  body: string; file: FileInfo | null; deleted: boolean; created_at: string | null;
};
type MsgPage = { messages: Msg[]; more: boolean; last_read_id: number; read_by_all: number };

const isPdf = (name: string) => name.toLowerCase().endsWith(".pdf");
const initial = (s: string) => (s || "?").slice(0, 1).toLocaleUpperCase("tr-TR");
const dayKey = (iso: string | null) => (iso ? new Date(iso).toDateString() : "");
const timeOf = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "");
function dayLabel(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Bugün";
  if (d.toDateString() === y.toDateString()) return "Dün";
  return d.toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric", weekday: "long" });
}
function listTime(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? timeOf(iso) : d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" });
}

/** Sohbet: direct messages and groups with file sharing. New messages arrive through the /chat/state poll in Layout. */
export default function Chat() {
  const { can } = useAuth();
  const canWrite = can("chat", "edit");
  const [params, setParams] = useSearchParams();
  const roomId = Number(params.get("r")) || null;
  const open = (id: number | null) => setParams(id ? { r: String(id) } : {}, { replace: true });
  const rooms = useQuery({ queryKey: ["chat", "rooms"], queryFn: () => api.get<Room[]>("/chat/rooms") });
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const list = useMemo(() => {
    const f = filter.trim().toLocaleLowerCase("tr-TR");
    const all = [...(rooms.data ?? [])].sort((a, b) => (b.last_at ?? "").localeCompare(a.last_at ?? ""));
    return f ? all.filter((r) => r.name.toLocaleLowerCase("tr-TR").includes(f)
      || r.members.some((m) => m.name.toLocaleLowerCase("tr-TR").includes(f))) : all;
  }, [rooms.data, filter]);
  const room = rooms.data?.find((r) => r.id === roomId) ?? null;

  return (
    <Page full>
      <div className={`chat${roomId ? " has-room" : ""}`}>
        <aside className="chat-rooms">
          <div className="chat-rooms-head">
            <h2><MessageCircle size={18} /> Sohbet</h2>
            {canWrite && <button className="btn small primary" onClick={() => setCreating(true)}><Plus size={15} /> Yeni</button>}
          </div>
          <label className="chat-search">
            <Search size={15} />
            <input type="search" placeholder="Kişi veya grup ara…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <div className="chat-room-list">
            {rooms.isError && <div className="error">{errText(rooms.error)}</div>}
            {rooms.isSuccess && !list.length && (
              <div className="empty">{filter ? "Eşleşen sohbet yok." : "Henüz sohbet yok. “Yeni” ile bir kişiye yazın veya grup kurun."}</div>
            )}
            {list.map((r) => (
              <button key={r.id} className={`chat-room${r.id === roomId ? " on" : ""}${r.unread ? " unread" : ""}`} onClick={() => open(r.id)}>
                <span className={`chat-avatar${r.kind === "group" ? " group" : ""}`}>{r.kind === "group" ? <Users size={16} /> : initial(r.name)}</span>
                <span className="chat-room-text">
                  <span className="chat-room-top"><b>{r.name}</b><small>{listTime(r.last_at)}</small></span>
                  <span className="chat-room-last">{r.last_message || (r.kind === "group" ? `${r.members.length} üye` : "Mesaj yok")}</span>
                </span>
                {r.unread > 0 && <span className="chat-badge">{r.unread > 99 ? "99+" : r.unread}</span>}
              </button>
            ))}
          </div>
        </aside>
        <section className="chat-pane">
          {room ? <RoomPane key={room.id} room={room} canWrite={canWrite} onBack={() => open(null)} onLeft={() => open(null)} />
            : <div className="chat-empty"><MessageCircle size={42} /><p>Bir sohbet seçin veya yeni bir sohbet başlatın.</p></div>}
        </section>
      </div>
      {creating && <NewChat onClose={() => setCreating(false)} onOpen={(id) => { setCreating(false); open(id); }} />}
    </Page>
  );
}

// ---------- one conversation ----------
function RoomPane({ room, canWrite, onBack, onLeft }: { room: Room; canWrite: boolean; onBack: () => void; onLeft: () => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const state = useQuery({ queryKey: ["chat", "state"], queryFn: () => api.get<ChatState>("/chat/state") });
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [more, setMore] = useState(false);
  const [readAll, setReadAll] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [settings, setSettings] = useState(false);
  const [viewing, setViewing] = useState<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pick = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const keepFrom = useRef<number | null>(null);
  const lastRead = useRef(0);
  const base = `/chat/rooms/${room.id}`;

  // Latest page, merged into what is loaded (older pages stay; deleted messages update in place)
  const refresh = useCallback(async () => {
    try {
      const p = await api.get<MsgPage>(`${base}/messages`);
      setReadAll(p.read_by_all);
      lastRead.current = Math.max(lastRead.current, p.last_read_id);
      setMsgs((old) => {
        const first = p.messages[0]?.id;
        if (!old.length || first === undefined || (p.more && old[old.length - 1].id < first)) {
          setMore(p.more);
          return p.messages;
        }
        const byId = new Map(old.map((m) => [m.id, m]));
        for (const m of p.messages) byId.set(m.id, m);
        return [...byId.values()].sort((a, b) => a.id - b.id);
      });
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => { void refresh(); }, [refresh]);
  const key = state.data?.key;
  useEffect(() => { if (key) void refresh(); }, [key, refresh]);

  const older = async () => {
    if (!msgs.length) return;
    const el = scroller.current;
    keepFrom.current = el ? el.scrollHeight - el.scrollTop : null;
    try {
      const p = await api.get<MsgPage>(`${base}/messages?before=${msgs[0].id}`);
      setMore(p.more);
      setMsgs((old) => [...p.messages.filter((m) => !old.some((o) => o.id === m.id)), ...old]);
    } catch (e) { toast(errText(e), true); }
  };

  // Scroll: stay at the bottom for new messages, keep position when older ones are prepended
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (keepFrom.current !== null) { el.scrollTop = el.scrollHeight - keepFrom.current; keepFrom.current = null; }
    else if (stick.current) el.scrollTop = el.scrollHeight;
  }, [msgs]);
  const onScroll = () => {
    const el = scroller.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  // Mark as read while the conversation is on screen
  useEffect(() => {
    const last = msgs[msgs.length - 1]?.id ?? 0;
    if (!last || last <= lastRead.current || document.visibilityState !== "visible") return;
    lastRead.current = last;
    void api.post(`${base}/read`, { last_id: last }).then(() => {
      void qc.invalidateQueries({ queryKey: ["chat", "rooms"] });
      void qc.invalidateQueries({ queryKey: ["chat", "state"] });
    }).catch(() => { lastRead.current = 0; });
  }, [msgs, base, qc]);

  useEffect(() => { input.current?.focus(); }, []);

  const addFiles = (list: FileList | File[] | null) => {
    const arr = [...(list ?? [])];
    if (arr.length) setFiles((f) => [...f, ...arr]);
  };

  const send = async () => {
    const body = text.trim();
    if ((!body && !files.length) || busy) return;
    stick.current = true;
    try {
      if (!files.length) {
        const f = new FormData();
        f.append("body", body);
        setBusy("Gönderiliyor…");
        await upload(`${base}/messages`, f);
      } else {
        for (const [i, file] of files.entries()) {
          const f = new FormData();
          f.append("body", i === 0 ? body : "");
          f.append("file", file, file.name);
          if (isImageFile(file)) {
            const t = await makeThumb(file);
            if (t) f.append("thumb", t, "t.jpg");
          }
          const tag = files.length > 1 ? `${i + 1} / ${files.length} ` : "";
          setBusy(`${tag}${file.name} gönderiliyor…`);
          await upload(`${base}/messages`, f, (pct) => setBusy(`${tag}${file.name} gönderiliyor… %${pct}`));
        }
      }
      setText("");
      setFiles([]);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setBusy(null);
      await refresh();
      void qc.invalidateQueries({ queryKey: ["chat", "rooms"] });
      input.current?.focus();
    }
  };

  const remove = async (m: Msg) => {
    if (!confirm("Mesaj silinsin mi? Herkes için silinir.")) return;
    try {
      const out = await api.del<Msg>(`/chat/messages/${m.id}`);
      setMsgs((old) => old.map((x) => (x.id === m.id ? out : x)));
      void qc.invalidateQueries({ queryKey: ["chat", "rooms"] });
    } catch (e) { toast(errText(e), true); }
  };

  const viewable = useMemo(() => msgs.filter((m) => m.file && (m.file.image || isPdf(m.file.name))), [msgs]);
  const items: ViewItem[] = viewable.map((m) => ({
    key: m.id, name: m.file!.name, path: `/chat/messages/${m.id}/file`,
    thumb: m.file!.image ? `/chat/messages/${m.id}/thumb` : undefined, kind: m.file!.image ? "image" : "pdf",
    caption: `${m.user_name} · ${dayLabel(m.created_at)} ${timeOf(m.created_at)}`,
  }));
  const openFile = (m: Msg) => setViewing(viewable.findIndex((x) => x.id === m.id));

  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (canWrite) addFiles(e.dataTransfer.files); };
  const onPaste = (e: ClipboardEvent) => {
    if (e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files); }
  };
  const others = room.members.filter((m) => m.id !== user?.id);
  const sub = room.kind === "group" ? room.members.map((m) => (m.id === user?.id ? "Siz" : m.name)).join(", ")
    : others[0]?.username ? `@${others[0].username}${others[0].active ? "" : " · pasif kullanıcı"}` : "";

  return (
    <div className={`chat-room-pane${over ? " drop" : ""}`}
      onDragOver={(e) => { if (canWrite && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }} onDrop={onDrop}>
      <header className="chat-head">
        <button className="icon-btn chat-back" onClick={onBack} aria-label="Sohbetler"><ArrowLeft size={18} /></button>
        <span className={`chat-avatar${room.kind === "group" ? " group" : ""}`}>{room.kind === "group" ? <Users size={16} /> : initial(room.name)}</span>
        <div className="chat-head-text">
          <b>{room.name}</b>
          <small className="muted" title={sub}>{sub}</small>
        </div>
        {room.kind === "group" && (
          <button className="icon-btn" onClick={() => setSettings(true)} title="Grup ayarları" aria-label="Grup ayarları"><Settings2 size={18} /></button>
        )}
      </header>
      <div className="chat-msgs" ref={scroller} onScroll={onScroll}>
        {more && <div className="chat-more"><button className="btn small" onClick={() => void older()}>Daha eski mesajlar</button></div>}
        {loading && <div className="muted chat-sys">Yükleniyor…</div>}
        {err && <div className="error">{err}</div>}
        {!loading && !msgs.length && <div className="muted chat-sys">İlk mesajı yazın. Dosya göndermek için 📎 veya sürükle-bırak.</div>}
        {msgs.map((m, i) => {
          const prev = msgs[i - 1];
          const newDay = !prev || dayKey(prev.created_at) !== dayKey(m.created_at);
          const mine = m.user_id === user?.id;
          const head = room.kind === "group" && !mine && m.kind === "text"
            && (newDay || !prev || prev.user_id !== m.user_id || prev.kind !== "text");
          return (
            <Fragment key={m.id}>
              {newDay && <div className="chat-day"><span>{dayLabel(m.created_at)}</span></div>}
              {m.kind === "system" ? <div className="chat-sys">{m.body} · {timeOf(m.created_at)}</div> : (
                <div className={`chat-msg${mine ? " mine" : ""}`}>
                  <div className={`chat-bubble${m.deleted ? " deleted" : ""}`}>
                    {head && <div className="chat-author">{m.user_name}</div>}
                    {m.deleted ? <i className="muted">Bu mesaj silindi</i> : <>
                      {m.file && <Attachment m={m} onOpen={() => openFile(m)} />}
                      {m.body && <div className="chat-text">{m.body}</div>}
                    </>}
                    <div className="chat-meta">
                      {timeOf(m.created_at)}
                      {mine && !m.deleted && (m.id <= readAll
                        ? <CheckCheck size={14} className="seen" aria-label="Görüldü" />
                        : <Check size={14} aria-label="Gönderildi" />)}
                      {mine && !m.deleted && canWrite && (
                        <button className="chat-del" onClick={() => void remove(m)} title="Sil" aria-label="Mesajı sil"><Trash2 size={13} /></button>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
      {canWrite ? (
        <div className="chat-compose">
          {!!files.length && (
            <div className="chat-files">
              {files.map((f, i) => (
                <span key={i} className="chat-file-chip" title={f.name}>
                  {isImageFile(f) ? "🖼" : "📄"} {f.name} <small className="muted">{fmtBytes(f.size)}</small>
                  <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label="Kaldır" disabled={!!busy}><X size={13} /></button>
                </span>
              ))}
            </div>
          )}
          {busy && <div className="muted chat-busy">{busy}</div>}
          <div className="chat-compose-row">
            <button className="icon-btn" onClick={() => pick.current?.click()} disabled={!!busy} title="Dosya ekle" aria-label="Dosya ekle"><Paperclip size={19} /></button>
            <input ref={pick} type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
            <textarea ref={input} rows={1} value={text} placeholder="Mesaj yazın…" title="Enter: gönder · Shift+Enter: yeni satır"
              onChange={(e) => setText(e.target.value)} onPaste={onPaste} maxLength={10000}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
            <button className="btn primary chat-send" onClick={() => void send()} disabled={!!busy || (!text.trim() && !files.length)} aria-label="Gönder"><Send size={17} /></button>
          </div>
        </div>
      ) : <div className="muted chat-compose">Sohbet için yalnızca okuma yetkiniz var.</div>}
      {over && <div className="chat-drop">Göndermek için dosyaları bırakın</div>}
      {viewing !== null && viewing >= 0 && items.length > 0 && <Viewer items={items} start={viewing} onClose={() => setViewing(null)} />}
      {settings && <GroupSettings room={room} onClose={() => setSettings(false)} onLeft={onLeft} />}
    </div>
  );
}

function Attachment({ m, onOpen }: { m: Msg; onOpen: () => void }) {
  const toast = useToast();
  const f = m.file!;
  const dl = () => void download(`/chat/messages/${m.id}/file?download=true`, f.name).catch((e) => toast(errText(e), true));
  if (f.image) {
    return (
      <button className="chat-image" onClick={onOpen} title="Büyütmek için tıklayın">
        <Thumb path={`/chat/messages/${m.id}/thumb`} label={f.name} />
      </button>
    );
  }
  return (
    <div className="chat-file">
      <FileText size={26} />
      <div className="chat-file-text">
        <b title={f.name}>{f.name}</b>
        <small className="muted">{fmtBytes(f.size)}</small>
      </div>
      {isPdf(f.name) && <button className="btn small" onClick={onOpen}>İncele</button>}
      <button className="btn small" onClick={dl} title="İndir" aria-label="İndir"><Download size={15} /></button>
    </div>
  );
}

// ---------- new conversation ----------
function useChatUsers() {
  return useQuery({ queryKey: ["chat", "users"], queryFn: () => api.get<ChatUser[]>("/chat/users") });
}

function UserPicker({ users, selected, toggle, filter }: {
  users: ChatUser[]; selected?: Set<number>; toggle: (u: ChatUser) => void; filter: string;
}) {
  const f = filter.trim().toLocaleLowerCase("tr-TR");
  const list = f ? users.filter((u) => `${u.name} ${u.username}`.toLocaleLowerCase("tr-TR").includes(f)) : users;
  if (!list.length) return <div className="empty">Kullanıcı yok.</div>;
  return (
    <div className="chat-pick">
      {list.map((u) => (
        <button key={u.id} className={`chat-pick-row${selected?.has(u.id) ? " on" : ""}`} onClick={() => toggle(u)}>
          <span className="chat-avatar">{initial(u.name)}</span>
          <span className="chat-room-text"><b>{u.name}</b><small className="muted">@{u.username}</small></span>
          {selected && <input type="checkbox" readOnly checked={selected.has(u.id)} tabIndex={-1} />}
        </button>
      ))}
    </div>
  );
}

function NewChat({ onClose, onOpen }: { onClose: () => void; onOpen: (roomId: number) => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const users = useChatUsers();
  const [tab, setTab] = useState<"direct" | "group">("direct");
  const [filter, setFilter] = useState("");
  const [name, setName] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const done = (r: Room) => { void qc.invalidateQueries({ queryKey: ["chat"] }); onOpen(r.id); };
  const direct = async (u: ChatUser) => {
    setBusy(true);
    try { done(await api.post<Room>("/chat/direct", { user_id: u.id })); } catch (e) { toast(errText(e), true); setBusy(false); }
  };
  const group = async () => {
    setBusy(true);
    try { done(await api.post<Room>("/chat/groups", { name: name.trim(), member_ids: [...sel] })); } catch (e) { toast(errText(e), true); setBusy(false); }
  };
  return (
    <Modal title="Yeni sohbet" onClose={onClose}
      footer={tab === "group" ? <>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={busy || !name.trim() || !sel.size} onClick={() => void group()}>Grubu kur ({sel.size} kişi)</button>
      </> : undefined}>
      <div className="seg" style={{ marginBottom: 10 }}>
        <button className={tab === "direct" ? "on" : ""} onClick={() => setTab("direct")}><UserIcon size={15} /> Kişiye özel</button>
        <button className={tab === "group" ? "on" : ""} onClick={() => setTab("group")}><Users size={15} /> Grup</button>
      </div>
      {tab === "group" && (
        <input autoFocus placeholder="Grup adı (ör. Montaj ekibi)" value={name} maxLength={120}
          onChange={(e) => setName(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
      )}
      <input type="search" placeholder="Kişi ara…" value={filter} onChange={(e) => setFilter(e.target.value)}
        autoFocus={tab === "direct"} style={{ width: "100%", marginBottom: 8 }} />
      {users.isError && <div className="error">{errText(users.error)}</div>}
      {users.data && (tab === "direct"
        ? <UserPicker users={users.data} filter={filter} toggle={(u) => !busy && void direct(u)} />
        : <UserPicker users={users.data} filter={filter} selected={sel}
            toggle={(u) => setSel((s) => { const n = new Set(s); if (n.has(u.id)) n.delete(u.id); else n.add(u.id); return n; })} />)}
    </Modal>
  );
}

// ---------- group settings ----------
function GroupSettings({ room, onClose, onLeft }: { room: Room; onClose: () => void; onLeft: () => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const users = useChatUsers();
  const [name, setName] = useState(room.name);
  const [adding, setAdding] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const admin = room.is_admin;
  const refresh = () => void qc.invalidateQueries({ queryKey: ["chat"] });
  const patch = async (body: Record<string, unknown>, ok: string) => {
    try { await api.patch(`/chat/rooms/${room.id}`, body); toast(ok); refresh(); } catch (e) { toast(errText(e), true); }
  };
  const admins = room.members.filter((m) => m.is_admin).map((m) => m.id);
  const toggleAdmin = (m: Member) => void patch(
    { admins: m.is_admin ? admins.filter((x) => x !== m.id) : [...admins, m.id] },
    m.is_admin ? `${m.name} artık yönetici değil` : `${m.name} yönetici yapıldı`);
  const leave = async () => {
    if (!confirm(`“${room.name}” grubundan ayrılmak istiyor musunuz?`)) return;
    try { await api.post(`/chat/rooms/${room.id}/leave`, {}); refresh(); onClose(); onLeft(); } catch (e) { toast(errText(e), true); }
  };
  const candidates = (users.data ?? []).filter((u) => !room.members.some((m) => m.id === u.id));

  return (
    <Modal title="Grup ayarları" onClose={onClose}
      footer={<>
        <button className="btn danger" onClick={() => void leave()}>Gruptan ayrıl</button>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onClose}>Kapat</button>
      </>}>
      {admin ? (
        <div className="row" style={{ marginBottom: 12 }}>
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          <button className="btn" disabled={!name.trim() || name.trim() === room.name}
            onClick={() => void patch({ name: name.trim() }, "Grup adı değişti")}>Yeniden adlandır</button>
        </div>
      ) : <p className="muted" style={{ marginTop: 0 }}>Üyeleri ve adı yalnızca grup yöneticileri değiştirebilir.</p>}
      <h4 style={{ margin: "0 0 6px" }}>Üyeler ({room.members.length})</h4>
      <div className="chat-pick">
        {room.members.map((m) => (
          <div key={m.id} className="chat-pick-row">
            <span className="chat-avatar">{initial(m.name)}</span>
            <span className="chat-room-text">
              <b>{m.id === user?.id ? `${m.name} (siz)` : m.name}</b>
              <small className="muted">@{m.username}{m.is_admin ? " · yönetici" : ""}{m.active ? "" : " · pasif"}</small>
            </span>
            {admin && m.id !== user?.id && <>
              <button className="btn small" onClick={() => toggleAdmin(m)}>{m.is_admin ? "Yöneticiliği al" : "Yönetici yap"}</button>
              <button className="btn small danger" onClick={() => void patch({ remove: [m.id] }, `${m.name} çıkarıldı`)}>Çıkar</button>
            </>}
          </div>
        ))}
      </div>
      {admin && (adding ? (
        <div style={{ marginTop: 12 }}>
          <input type="search" placeholder="Eklenecek kişiyi ara…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
          <UserPicker users={candidates} filter={filter} selected={sel}
            toggle={(u) => setSel((s) => { const n = new Set(s); if (n.has(u.id)) n.delete(u.id); else n.add(u.id); return n; })} />
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
            <button className="btn" onClick={() => { setAdding(false); setSel(new Set()); }}>Vazgeç</button>
            <button className="btn primary" disabled={!sel.size}
              onClick={() => void patch({ add: [...sel] }, `${sel.size} kişi eklendi`).then(() => { setAdding(false); setSel(new Set()); })}>Ekle</button>
          </div>
        </div>
      ) : <button className="btn" style={{ marginTop: 12 }} onClick={() => setAdding(true)}><Plus size={15} /> Üye ekle</button>)}
    </Modal>
  );
}
