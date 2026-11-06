import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, CheckCheck, CheckSquare, ChevronDown, Copy, CornerUpLeft, Download, FileText, Forward, MessageCircle,
  Paperclip, Pencil, Pin, PinOff, Plus, Search, Send, Settings2, Trash2, User as UserIcon, Users, X,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type TouchEvent as ReactTouchEvent, type MouseEvent as ReactMouseEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, upload } from "../api/client";
import { useAuth } from "../api/auth";
import { fmtBytes, isImageFile, makeThumb } from "../api/images";
import { Page } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import Thumb from "../components/viewer/Thumb";
import Viewer, { type ViewItem } from "../components/viewer/Viewer";
import { Modal } from "./admin/shared";
import { copyText } from "../api/clipboard";
import { LOCALE, tx } from "../api/i18n";

export type ChatState = { key: string; unread: number; last_id: number };
type ChatUser = { id: number; name: string; username: string };
type Member = ChatUser & { is_admin: boolean; active: boolean };
type Room = {
  id: number; kind: "direct" | "group"; name: string; is_admin: boolean; members: Member[];
  last_message: string; last_at: string | null; last_id: number; unread: number; created_by: number | null;
  pinned: Quote | null;
};
type Quote = { id: number; user_name: string; deleted: boolean; text: string };
type Reaction = { emoji: string; count: number; mine: boolean; names: string[] };
type FileInfo = { name: string; size: number; type: string; image: boolean };
type Msg = {
  id: number; room_id: number; user_id: number | null; user_name: string; kind: "text" | "system";
  body: string; file: FileInfo | null; deleted: boolean; created_at: string | null;
  edited_at: string | null; reply_to: Quote | null; forwarded_from: string | null; reactions: Reaction[];
};
type MsgPage = { messages: Msg[]; more: boolean; last_read_id: number; read_by_all: number };

const REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];
const EDIT_MS = 48 * 3600 * 1000;
const LONG_PRESS_MS = 450;
const summary = (m: Msg) => m.body || (m.file ? `📎 ${m.file.name}` : "");
const editable = (m: Msg) => !m.deleted && !m.forwarded_from && !!m.created_at && Date.now() - new Date(m.created_at).getTime() < EDIT_MS;

const isPdf = (name: string) => name.toLowerCase().endsWith(".pdf");
const initial = (s: string) => (s || "?").slice(0, 1).toLocaleUpperCase(LOCALE);
const dayKey = (iso: string | null) => (iso ? new Date(iso).toDateString() : "");
const timeOf = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }) : "");
function dayLabel(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return tx("Bugün");
  if (d.toDateString() === y.toDateString()) return tx("Dün");
  return d.toLocaleDateString(LOCALE, { day: "numeric", month: "long", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric", weekday: "long" });
}
function listTime(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? timeOf(iso) : d.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" });
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
    const f = filter.trim().toLocaleLowerCase(LOCALE);
    const all = [...(rooms.data ?? [])].sort((a, b) => (b.last_at ?? "").localeCompare(a.last_at ?? ""));
    return f ? all.filter((r) => r.name.toLocaleLowerCase(LOCALE).includes(f)
      || r.members.some((m) => m.name.toLocaleLowerCase(LOCALE).includes(f))) : all;
  }, [rooms.data, filter]);
  const room = rooms.data?.find((r) => r.id === roomId) ?? null;

  return (
    <Page full>
      <div className={`chat${roomId ? " has-room" : ""}`}>
        <aside className="chat-rooms">
          <div className="chat-rooms-head">
            <h2><MessageCircle size={18} />{" "}{tx("Sohbet")}</h2>
            {canWrite && <button className="btn small primary" onClick={() => setCreating(true)}><Plus size={15} />{" "}{tx("Yeni")}</button>}
          </div>
          <label className="chat-search">
            <Search size={15} />
            <input type="search" placeholder={tx("Kişi veya grup ara…")} value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <div className="chat-room-list">
            {rooms.isError && <div className="error">{errText(rooms.error)}</div>}
            {rooms.isSuccess && !list.length && (
              <div className="empty">{filter ? tx("Eşleşen sohbet yok.") : tx("Henüz sohbet yok. “Yeni” ile bir kişiye yazın veya grup kurun.")}</div>
            )}
            {list.map((r) => (
              <button key={r.id} className={`chat-room${r.id === roomId ? " on" : ""}${r.unread ? " unread" : ""}`} onClick={() => open(r.id)}>
                <span className={`chat-avatar${r.kind === "group" ? " group" : ""}`}>{r.kind === "group" ? <Users size={16} /> : initial(r.name)}</span>
                <span className="chat-room-text">
                  <span className="chat-room-top"><b>{r.name}</b><small>{listTime(r.last_at)}</small></span>
                  <span className="chat-room-last">{r.last_message || (r.kind === "group" ? tx("{0} üye", r.members.length) : tx("Mesaj yok"))}</span>
                </span>
                {r.unread > 0 && <span className="chat-badge">{r.unread > 99 ? "99+" : r.unread}</span>}
              </button>
            ))}
          </div>
        </aside>
        <section className="chat-pane">
          {room ? <RoomPane key={room.id} room={room} canWrite={canWrite} onBack={() => open(null)} onLeft={() => open(null)} />
            : <div className="chat-empty"><MessageCircle size={42} /><p>{tx("Bir sohbet seçin veya yeni bir sohbet başlatın.")}</p></div>}
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
  const [replying, setReplying] = useState<Msg | null>(null);
  const [editing, setEditing] = useState<Msg | null>(null);
  const [menu, setMenu] = useState<{ m: Msg; x: number; y: number } | null>(null);
  const press = useRef<number | undefined>(undefined);
  const held = useRef(false);
  const [deleting, setDeleting] = useState<Msg[] | null>(null);
  const [forwarding, setForwarding] = useState<number[] | null>(null);
  const [picked, setPicked] = useState<Set<number> | null>(null);
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

  const put = (m: Msg) => setMsgs((old) => old.map((x) => (x.id === m.id ? m : x)));
  const roomsChanged = () => void qc.invalidateQueries({ queryKey: ["chat", "rooms"] });
  const cancelCompose = () => {
    if (editing) setText("");
    setEditing(null);
    setReplying(null);
  };
  const startEdit = (m: Msg) => {
    setReplying(null);
    setEditing(m);
    setText(m.body);
    input.current?.focus();
  };
  const saveEdit = async () => {
    if (!editing || busy) return;
    try {
      put(await api.patch<Msg>(`/chat/messages/${editing.id}`, { body: text.trim() }));
      setEditing(null);
      setText("");
      roomsChanged();
    } catch (e) { toast(errText(e), true); }
  };

  const send = async () => {
    if (editing) { await saveEdit(); return; }
    const body = text.trim();
    if ((!body && !files.length) || busy) return;
    stick.current = true;
    const replyTo = replying ? String(replying.id) : null;
    try {
      if (!files.length) {
        const f = new FormData();
        f.append("body", body);
        if (replyTo) f.append("reply_to", replyTo);
        setBusy(tx("Gönderiliyor…"));
        await upload(`${base}/messages`, f);
      } else {
        for (const [i, file] of files.entries()) {
          const f = new FormData();
          f.append("body", i === 0 ? body : "");
          if (replyTo && i === 0) f.append("reply_to", replyTo);
          f.append("file", file, file.name);
          if (isImageFile(file)) {
            const t = await makeThumb(file);
            if (t) f.append("thumb", t, "t.jpg");
          }
          const tag = files.length > 1 ? `${i + 1} / ${files.length} ` : "";
          setBusy(tx("{0}{1} gönderiliyor…", tag, file.name));
          await upload(`${base}/messages`, f, (pct) => setBusy(tx("{0}{1} gönderiliyor… %{2}", tag, file.name, pct)));
        }
      }
      setText("");
      setFiles([]);
      setReplying(null);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setBusy(null);
      await refresh();
      void qc.invalidateQueries({ queryKey: ["chat", "rooms"] });
      input.current?.focus();
    }
  };

  const remove = async (list: Msg[], scope: "all" | "me") => {
    setDeleting(null);
    setPicked(null);
    try {
      for (const m of list) {
        const out = await api.del<Msg>(`/chat/messages/${m.id}?scope=${scope}`);
        if (scope === "all") put(out);
        else setMsgs((old) => old.filter((x) => x.id !== m.id));
      }
      roomsChanged();
    } catch (e) { toast(errText(e), true); }
  };
  const react = async (m: Msg, emoji: string) => {
    try { put(await api.put<Msg>(`/chat/messages/${m.id}/reaction`, { emoji })); } catch (e) { toast(errText(e), true); }
  };
  const pin = async (id: number | null) => {
    try {
      await api.post(`${base}/pin`, { message_id: id });
      roomsChanged();
    } catch (e) { toast(errText(e), true); }
  };
  const copy = async (list: Msg[]) => {
    try {
      await copyText(list.map(summary).join("\n"));
      toast(tx("Kopyalandı"));
    } catch (e) { toast(errText(e), true); }
  };
  const jump = (id: number) => {
    const el = document.getElementById(`chat-m-${id}`);
    if (!el) { toast(tx("Mesaj yüklü değil. “Daha eski mesajlar” ile açın.")); return; }
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("flash");
    window.setTimeout(() => el.classList.remove("flash"), 1500);
  };
  const openMenu = (e: ReactMouseEvent, m: Msg) => {
    e.preventDefault();
    setMenu({ m, x: e.clientX, y: e.clientY });
  };
  /** Phones have no hover or right click: a long press on the message opens the same menu. */
  const pressStart = (e: ReactTouchEvent, m: Msg) => {
    const { clientX: x, clientY: y } = e.touches[0];
    window.clearTimeout(press.current);
    press.current = window.setTimeout(() => {
      held.current = true;
      setMenu({ m, x, y });
    }, LONG_PRESS_MS);
  };
  const pressMove = () => window.clearTimeout(press.current);
  /** The finger that opened the menu lifts over it: that release must not count as a tap on the menu. */
  const pressEnd = (e: ReactTouchEvent) => {
    window.clearTimeout(press.current);
    if (held.current) e.preventDefault();
    held.current = false;
  };
  const toggle = (id: number) => setPicked((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next.size ? next : null;
  });
  const pickedMsgs = picked ? msgs.filter((m) => picked.has(m.id)) : [];
  const canDeleteAll = (m: Msg) => canWrite && !m.deleted && (m.user_id === user?.id || (room.kind === "group" && room.is_admin));
  const canPin = canWrite && (room.kind === "direct" || room.is_admin);

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
  const sub = room.kind === "group" ? room.members.map((m) => (m.id === user?.id ? tx("Siz") : m.name)).join(", ")
    : others[0]?.username ? `@${others[0].username}${others[0].active ? "" : tx(" · pasif kullanıcı")}` : "";

  return (
    <div className={`chat-room-pane${over ? " drop" : ""}`}
      onDragOver={(e) => { if (canWrite && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }} onDrop={onDrop}>
      {picked ? (
        <header className="chat-head chat-picking">
          <button className="icon-btn" onClick={() => setPicked(null)} aria-label={tx("Seçimi bırak")}><X size={18} /></button>
          <b style={{ flex: 1 }}>{tx("{0} mesaj seçili", picked.size)}</b>
          <button className="icon-btn" onClick={() => void copy(pickedMsgs).then(() => setPicked(null))} title={tx("Kopyala")} aria-label={tx("Kopyala")}><Copy size={18} /></button>
          {canWrite && <button className="icon-btn" disabled={pickedMsgs.some((m) => m.deleted)} onClick={() => setForwarding(pickedMsgs.map((m) => m.id))} title={tx("İlet")} aria-label={tx("İlet")}><Forward size={18} /></button>}
          <button className="icon-btn" onClick={() => setDeleting(pickedMsgs)} title={tx("Sil")} aria-label={tx("Sil")}><Trash2 size={18} /></button>
        </header>
      ) : <header className="chat-head">
        <button className="icon-btn chat-back" onClick={onBack} aria-label={tx("Sohbetler")}><ArrowLeft size={18} /></button>
        <span className={`chat-avatar${room.kind === "group" ? " group" : ""}`}>{room.kind === "group" ? <Users size={16} /> : initial(room.name)}</span>
        <div className="chat-head-text">
          <b>{room.name}</b>
          <small className="muted" title={sub}>{sub}</small>
        </div>
        {room.kind === "group" && (
          <button className="icon-btn" onClick={() => setSettings(true)} title={tx("Grup ayarları")} aria-label={tx("Grup ayarları")}><Settings2 size={18} /></button>
        )}
      </header>}
      {room.pinned && (
        <div className="chat-pinned">
          <Pin size={15} />
          <button className="chat-pinned-text" onClick={() => jump(room.pinned!.id)}>
            <b>{tx("Sabitlenmiş mesaj")}</b><span>{room.pinned.user_name}: {room.pinned.text}</span>
          </button>
          {canPin && <button className="icon-btn" onClick={() => void pin(null)} title={tx("Sabitlemeyi kaldır")} aria-label={tx("Sabitlemeyi kaldır")}><X size={15} /></button>}
        </div>
      )}
      <div className="chat-msgs" ref={scroller} onScroll={onScroll}>
        {more && <div className="chat-more"><button className="btn small" onClick={() => void older()}>{tx("Daha eski mesajlar")}</button></div>}
        {loading && <div className="muted chat-sys">{tx("Yükleniyor…")}</div>}
        {err && <div className="error">{err}</div>}
        {!loading && !msgs.length && <div className="muted chat-sys">{tx("İlk mesajı yazın. Dosya göndermek için 📎 veya sürükle-bırak.")}</div>}
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
                <div id={`chat-m-${m.id}`} className={`chat-msg${mine ? " mine" : ""}${picked?.has(m.id) ? " picked" : ""}`}
                  onClick={picked ? () => toggle(m.id) : undefined}>
                  {picked && <input type="checkbox" className="chat-check" readOnly checked={picked.has(m.id)} tabIndex={-1} aria-label={tx("Mesajı seç")} />}
                  <div className={`chat-bubble${m.deleted ? " deleted" : ""}`} onContextMenu={picked ? undefined : (e) => openMenu(e, m)}
                    onTouchStart={picked ? undefined : (e) => pressStart(e, m)} onTouchMove={pressMove} onTouchEnd={pressEnd} onTouchCancel={pressEnd}>
                    {head && <div className="chat-author">{m.user_name}</div>}
                    {m.deleted ? <i className="muted">{tx("Bu mesaj silindi")}</i> : <>
                      {m.forwarded_from && <div className="chat-forwarded"><Forward size={12} />{" "}{tx("İletildi: {0}", m.forwarded_from)}</div>}
                      {m.reply_to && (
                        <button className="chat-quote" onClick={(e) => { e.stopPropagation(); jump(m.reply_to!.id); }}>
                          <b>{m.reply_to.user_name}</b>
                          <span>{m.reply_to.deleted ? tx("Bu mesaj silindi") : m.reply_to.text}</span>
                        </button>
                      )}
                      {m.file && <Attachment m={m} onOpen={() => openFile(m)} />}
                      {m.body && <div className="chat-text">{m.body}</div>}
                    </>}
                    <div className="chat-meta">
                      {m.edited_at && <span>{tx("düzenlendi")}</span>}
                      {timeOf(m.created_at)}
                      {mine && !m.deleted && (m.id <= readAll
                        ? <CheckCheck size={14} className="seen" aria-label={tx("Görüldü")} />
                        : <Check size={14} aria-label={tx("Gönderildi")} />)}
                    </div>
                    {!!m.reactions.length && (
                      <div className="chat-reactions">
                        {m.reactions.map((r) => (
                          <button key={r.emoji} className={r.mine ? "on" : ""} title={r.names.join(", ")} disabled={!canWrite}
                            onClick={(e) => { e.stopPropagation(); void react(m, r.emoji); }}>{r.emoji} {r.count}</button>
                        ))}
                      </div>
                    )}
                  </div>
                  {!picked && <button className="chat-more-btn" onClick={(e) => openMenu(e, m)} title={tx("Mesaj işlemleri")} aria-label={tx("Mesaj işlemleri")}><ChevronDown size={16} /></button>}
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
      {canWrite ? (
        <div className="chat-compose">
          {(replying || editing) && (
            <div className="chat-context">
              {editing ? <Pencil size={15} /> : <CornerUpLeft size={15} />}
              <div className="chat-context-text">
                <b>{editing ? tx("Mesajı düzenle") : replying!.user_name}</b>
                <span>{summary(editing ?? replying!)}</span>
              </div>
              <button className="icon-btn" onClick={cancelCompose} aria-label={tx("Vazgeç")}><X size={15} /></button>
            </div>
          )}
          {!!files.length && (
            <div className="chat-files">
              {files.map((f, i) => (
                <span key={i} className="chat-file-chip" title={f.name}>
                  {isImageFile(f) ? "🖼" : "📄"} {f.name} <small className="muted">{fmtBytes(f.size)}</small>
                  <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={tx("Kaldır")} disabled={!!busy}><X size={13} /></button>
                </span>
              ))}
            </div>
          )}
          {busy && <div className="muted chat-busy">{busy}</div>}
          <div className="chat-compose-row">
            <button className="icon-btn" onClick={() => pick.current?.click()} disabled={!!busy || !!editing} title={tx("Dosya ekle")} aria-label={tx("Dosya ekle")}><Paperclip size={19} /></button>
            <input ref={pick} type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
            <textarea ref={input} rows={1} value={text} placeholder={tx("Mesaj yazın…")} title={tx("Enter: gönder · Shift+Enter: yeni satır")}
              onChange={(e) => setText(e.target.value)} onPaste={onPaste} maxLength={10000}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
                if (e.key === "Escape") cancelCompose();
                if (e.key === "ArrowUp" && !text && !editing) {
                  const last = [...msgs].reverse().find((m) => m.user_id === user?.id && m.kind === "text" && editable(m));
                  if (last) { e.preventDefault(); startEdit(last); }
                }
              }} />
            <button className="btn primary chat-send" onClick={() => void send()} disabled={!!busy || (!text.trim() && !files.length && !editing?.file)} aria-label={editing ? tx("Kaydet") : tx("Gönder")}><Send size={17} /></button>
          </div>
        </div>
      ) : <div className="muted chat-compose">{tx("Sohbet için yalnızca okuma yetkiniz var.")}</div>}
      {over && <div className="chat-drop">{tx("Göndermek için dosyaları bırakın")}</div>}
      {viewing !== null && viewing >= 0 && items.length > 0 && <Viewer items={items} start={viewing} onClose={() => setViewing(null)} />}
      {settings && <GroupSettings room={room} onClose={() => setSettings(false)} onLeft={onLeft} />}
      {menu && (
        <MessageMenu at={menu} onClose={() => { if (!held.current) setMenu(null); }} canWrite={canWrite}
          onReact={(emoji) => void react(menu.m, emoji)}
          actions={[
            ...(canWrite && !menu.m.deleted ? [{ icon: <CornerUpLeft size={16} />, label: tx("Yanıtla"), run: () => { setEditing(null); setReplying(menu.m); input.current?.focus(); } }] : []),
            ...(!menu.m.deleted ? [{ icon: <Copy size={16} />, label: tx("Kopyala"), run: () => void copy([menu.m]) }] : []),
            ...(canWrite && !menu.m.deleted ? [{ icon: <Forward size={16} />, label: tx("İlet"), run: () => setForwarding([menu.m.id]) }] : []),
            ...(canPin && !menu.m.deleted ? [room.pinned?.id === menu.m.id
              ? { icon: <PinOff size={16} />, label: tx("Sabitlemeyi kaldır"), run: () => void pin(null) }
              : { icon: <Pin size={16} />, label: tx("Sabitle"), run: () => void pin(menu.m.id) }] : []),
            ...(canWrite && menu.m.user_id === user?.id && editable(menu.m) ? [{ icon: <Pencil size={16} />, label: tx("Düzenle"), run: () => startEdit(menu.m) }] : []),
            { icon: <CheckSquare size={16} />, label: tx("Seç"), run: () => setPicked(new Set([menu.m.id])) },
            { icon: <Trash2 size={16} />, label: tx("Sil"), danger: true, run: () => setDeleting([menu.m]) },
          ]} />
      )}
      {deleting && (
        <Modal title={deleting.length > 1 ? tx("{0} mesaj silinsin mi?", deleting.length) : tx("Mesaj silinsin mi?")} onClose={() => setDeleting(null)}
          footer={<>
            <button className="btn" onClick={() => setDeleting(null)}>{tx("Vazgeç")}</button>
            <button className="btn" onClick={() => void remove(deleting, "me")}>{tx("Benden sil")}</button>
            {deleting.every(canDeleteAll) && <button className="btn danger" onClick={() => void remove(deleting, "all")}>{tx("Herkesten sil")}</button>}
          </>}>
          <p className="muted" style={{ margin: 0 }}>
            {tx("“Benden sil” yalnızca sizin ekranınızdan kaldırır.")}
            {deleting.every(canDeleteAll) ? tx(" “Herkesten sil” mesajı ve dosyasını herkesten kaldırır, geri alınamaz.") : ""}
          </p>
        </Modal>
      )}
      {forwarding && <ForwardModal ids={forwarding} onClose={() => setForwarding(null)} onDone={() => { setForwarding(null); setPicked(null); void refresh(); }} />}
    </div>
  );
}

type MenuAction = { icon: JSX.Element; label: string; danger?: boolean; run: () => void };

/** Fixed to the viewport: the message list scrolls and would cut a menu inside the bubble. */
function MessageMenu({ at, actions, canWrite, onReact, onClose }: {
  at: { m: Msg; x: number; y: number }; actions: MenuAction[]; canWrite: boolean; onReact: (emoji: string) => void; onClose: () => void;
}) {
  const left = Math.max(8, Math.min(at.x, window.innerWidth - 228));
  const top = Math.max(8, Math.min(at.y, window.innerHeight - (actions.length * 38 + 66)));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="chat-menu-back" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div className="chat-menu" role="menu" style={{ left, top }} onClick={(e) => e.stopPropagation()}>
        {canWrite && !at.m.deleted && (
          <div className="chat-menu-emoji">
            {REACTIONS.map((r) => (
              <button key={r} className={at.m.reactions.some((x) => x.mine && x.emoji === r) ? "on" : ""} aria-label={tx("Tepki {0}", r)}
                onClick={() => { onReact(r); onClose(); }}>{r}</button>
            ))}
          </div>
        )}
        {actions.map((a) => (
          <button key={a.label} role="menuitem" className={a.danger ? "danger" : ""} onClick={() => { onClose(); a.run(); }}>{a.icon} {a.label}</button>
        ))}
      </div>
    </div>
  );
}

function ForwardModal({ ids, onClose, onDone }: { ids: number[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const rooms = useQuery({ queryKey: ["chat", "rooms"], queryFn: () => api.get<Room[]>("/chat/rooms") });
  const [filter, setFilter] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const f = filter.trim().toLocaleLowerCase(LOCALE);
  const list = (rooms.data ?? []).filter((r) => !f || r.name.toLocaleLowerCase(LOCALE).includes(f));
  const go = async () => {
    setBusy(true);
    try {
      await api.post("/chat/forward", { message_ids: ids, room_ids: [...sel] });
      toast(sel.size > 1 ? tx("{0} sohbete iletildi", sel.size) : tx("İletildi"));
      void qc.invalidateQueries({ queryKey: ["chat"] });
      onDone();
    } catch (e) { toast(errText(e), true); setBusy(false); }
  };
  return (
    <Modal title={ids.length > 1 ? tx("{0} mesajı ilet", ids.length) : tx("Mesajı ilet")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={busy || !sel.size} onClick={() => void go()}>{tx("İlet ({0})", sel.size)}</button>
      </>}>
      <input type="search" autoFocus placeholder={tx("Sohbet ara…")} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
      {rooms.isError && <div className="error">{errText(rooms.error)}</div>}
      {rooms.isSuccess && !list.length && <div className="empty">{tx("Sohbet yok.")}</div>}
      <div className="chat-pick">
        {list.map((r) => (
          <button key={r.id} className={`chat-pick-row${sel.has(r.id) ? " on" : ""}`}
            onClick={() => setSel((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n; })}>
            <span className={`chat-avatar${r.kind === "group" ? " group" : ""}`}>{r.kind === "group" ? <Users size={16} /> : initial(r.name)}</span>
            <span className="chat-room-text"><b>{r.name}</b></span>
            <input type="checkbox" readOnly checked={sel.has(r.id)} tabIndex={-1} />
          </button>
        ))}
      </div>
    </Modal>
  );
}

function Attachment({ m, onOpen }: { m: Msg; onOpen: () => void }) {
  const toast = useToast();
  const f = m.file!;
  const dl = () => void download(`/chat/messages/${m.id}/file?download=true`, f.name).catch((e) => toast(errText(e), true));
  if (f.image) {
    return (
      <button className="chat-image" onClick={onOpen} title={tx("Büyütmek için tıklayın")}>
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
      {isPdf(f.name) && <button className="btn small" onClick={onOpen}>{tx("İncele")}</button>}
      <button className="btn small" onClick={dl} title={tx("İndir")} aria-label={tx("İndir")}><Download size={15} /></button>
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
  const f = filter.trim().toLocaleLowerCase(LOCALE);
  const list = f ? users.filter((u) => `${u.name} ${u.username}`.toLocaleLowerCase(LOCALE).includes(f)) : users;
  if (!list.length) return <div className="empty">{tx("Kullanıcı yok.")}</div>;
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
    <Modal title={tx("Yeni sohbet")} onClose={onClose}
      footer={tab === "group" ? <>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={busy || !name.trim() || !sel.size} onClick={() => void group()}>{tx("Grubu kur ({0} kişi)", sel.size)}</button>
      </> : undefined}>
      <div className="seg" style={{ marginBottom: 10 }}>
        <button className={tab === "direct" ? "on" : ""} onClick={() => setTab("direct")}><UserIcon size={15} />{" "}{tx("Kişiye özel")}</button>
        <button className={tab === "group" ? "on" : ""} onClick={() => setTab("group")}><Users size={15} />{" "}{tx("Grup")}</button>
      </div>
      {tab === "group" && (
        <input autoFocus placeholder={tx("Grup adı (ör. Montaj ekibi)")} value={name} maxLength={120}
          onChange={(e) => setName(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
      )}
      <input type="search" placeholder={tx("Kişi ara…")} value={filter} onChange={(e) => setFilter(e.target.value)}
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
    m.is_admin ? tx("{0} artık yönetici değil", m.name) : tx("{0} yönetici yapıldı", m.name));
  const leave = async () => {
    if (!confirm(tx("“{0}” grubundan ayrılmak istiyor musunuz?", room.name))) return;
    try { await api.post(`/chat/rooms/${room.id}/leave`, {}); refresh(); onClose(); onLeft(); } catch (e) { toast(errText(e), true); }
  };
  const candidates = (users.data ?? []).filter((u) => !room.members.some((m) => m.id === u.id));

  return (
    <Modal title={tx("Grup ayarları")} onClose={onClose}
      footer={<>
        <button className="btn danger" onClick={() => void leave()}>{tx("Gruptan ayrıl")}</button>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onClose}>{tx("Kapat")}</button>
      </>}>
      {admin ? (
        <div className="row" style={{ marginBottom: 12 }}>
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          <button className="btn" disabled={!name.trim() || name.trim() === room.name}
            onClick={() => void patch({ name: name.trim() }, tx("Grup adı değişti"))}>{tx("Yeniden adlandır")}</button>
        </div>
      ) : <p className="muted" style={{ marginTop: 0 }}>{tx("Üyeleri ve adı yalnızca grup yöneticileri değiştirebilir.")}</p>}
      <h4 style={{ margin: "0 0 6px" }}>{tx("Üyeler ({0})", room.members.length)}</h4>
      <div className="chat-pick">
        {room.members.map((m) => (
          <div key={m.id} className="chat-pick-row">
            <span className="chat-avatar">{initial(m.name)}</span>
            <span className="chat-room-text">
              <b>{m.id === user?.id ? tx("{0} (siz)", m.name) : m.name}</b>
              <small className="muted">@{m.username}{m.is_admin ? tx(" · yönetici") : ""}{m.active ? "" : tx(" · pasif")}</small>
            </span>
            {admin && m.id !== user?.id && <>
              <button className="btn small" onClick={() => toggleAdmin(m)}>{m.is_admin ? tx("Yöneticiliği al") : tx("Yönetici yap")}</button>
              <button className="btn small danger" onClick={() => void patch({ remove: [m.id] }, tx("{0} çıkarıldı", m.name))}>{tx("Çıkar")}</button>
            </>}
          </div>
        ))}
      </div>
      {admin && (adding ? (
        <div style={{ marginTop: 12 }}>
          <input type="search" placeholder={tx("Eklenecek kişiyi ara…")} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
          <UserPicker users={candidates} filter={filter} selected={sel}
            toggle={(u) => setSel((s) => { const n = new Set(s); if (n.has(u.id)) n.delete(u.id); else n.add(u.id); return n; })} />
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
            <button className="btn" onClick={() => { setAdding(false); setSel(new Set()); }}>{tx("Vazgeç")}</button>
            <button className="btn primary" disabled={!sel.size}
              onClick={() => void patch({ add: [...sel] }, tx("{0} kişi eklendi", sel.size)).then(() => { setAdding(false); setSel(new Set()); })}>{tx("Ekle")}</button>
          </div>
        </div>
      ) : <button className="btn" style={{ marginTop: 12 }} onClick={() => setAdding(true)}><Plus size={15} />{" "}{tx("Üye ekle")}</button>)}
    </Modal>
  );
}
