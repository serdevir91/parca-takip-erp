import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal } from "./admin/shared";
import { fmtDay, numOrNull, today } from "./erp/common";
import { Stat } from "./erp/commerce";

export type LeaveKind = "annual" | "sick" | "excuse" | "unpaid";
export type ReqStatus = "pending" | "approved" | "rejected" | "cancelled";
export type Leave = {
  id: number; employee_id: number; employee_name: string; kind: LeaveKind; kind_label: string; start_date: string; end_date: string;
  days: number; status: ReqStatus; status_label: string; note: string; created_by: string; decided_by: string;
  decision_note: string; free_days?: number;
};
export type Fix = {
  id: number; employee_id: number; employee_name: string; attendance_id: number | null; work_date: string; start: string;
  end: string | null; next_day: boolean; current: string | null; reason: string; status: ReqStatus; status_label: string;
  decided_by: string; decision_note: string;
};
type Balance = { year: number; entitled: number; used: number; pending: number; remaining: number };
type MyLeaveResp = { employee: { id: number } | null; balance: Balance | null; rows: Leave[] };
type MyFixResp = { employee: { id: number } | null; rows: Fix[] };
type DayShift = { id: number; work_date: string; start: string; end: string | null };
type Entry = {
  id: number; work_date: string; hours: number; project_id: number | null; project_name: string | null;
  work_order_id: number | null; work_order_no: string | null; note: string;
};
type DayResp = {
  employee: { id: number } | null; day: string; attended: number | null; open: boolean; forgot: boolean; allocated: number;
  remaining: number; editable: boolean; edit_days: number; rows: Entry[];
};
type Options = { work_orders: { id: number; no: string; description: string }[]; projects: { id: number; name: string }[] };

export const LEAVE_KINDS: [LeaveKind, string][] = [["annual", "Yıllık izin"], ["sick", "Rapor"], ["excuse", "Mazeret"], ["unpaid", "Ücretsiz izin"]];
export const fmtH = (h: number) => `${h.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} sa`;
const fmtD = (d: number) => `${d.toLocaleString("tr-TR", { maximumFractionDigits: 1 })} gün`;
export const dayRange = (a: string, b: string) => (a === b ? fmtDay(a) : `${fmtDay(a)} – ${fmtDay(b)}`);
export const fixTimes = (f: Fix) => `${f.start} – ${f.end ? `${f.end}${f.next_day ? " (+1)" : ""}` : "çıkış yok"}`;

/** Everything that hangs on shifts, leave or hours; each screen's keys start with one of these. */
export function useAttRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["attendance-me", "attendance", "hr-me"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

export function StatusBadge({ status, label }: { status: ReqStatus; label: string }) {
  const tone = status === "pending" ? " warn" : status === "rejected" ? " err" : status === "approved" ? " new" : "";
  return <span className={`badge${tone}`}>{label}</span>;
}

/** İzinlerim: yıllık izin bakiyesi, kendi talepleri, yeni talep ve bekleyeni iptal. */
export function MyLeaves() {
  const toast = useToast();
  const refresh = useAttRefresh();
  const now = new Date().getFullYear();
  const [year, setYear] = useState(now);
  const [asking, setAsking] = useState(false);
  const q = useQuery({ queryKey: ["attendance-me", "leave", year], queryFn: () => api.get<MyLeaveResp>(`/leave/me?year=${year}`) });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`/leave/me/${id}/cancel`, {}),
    onSuccess: () => { toast("Talep iptal edildi"); refresh(); },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  const d = q.data;
  const b = d?.balance;
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      <div className="row" style={{ margin: "10px 0", flexWrap: "wrap" }}>
        <select aria-label="Yıl" value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {[now - 1, now, now + 1].map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <button className="btn primary" onClick={() => setAsking(true)}>İzin talebi</button>
      </div>
      {b && (
        <div className="grid stats">
          <Stat label="Yıllık izin hakkı" value={fmtD(b.entitled)} />
          <Stat label="Kullanılan" value={fmtD(b.used)} />
          <Stat label="Bekleyen" value={fmtD(b.pending)} />
          <Stat label="Kalan" value={fmtD(b.remaining)} tone={b.remaining < 0 ? "warn" : undefined} />
        </div>
      )}
      <div className="card">
        <div className="ulist">
          {d?.rows.map((r) => (
            <div key={r.id} className="ucard">
              <div className="ucard-main">
                <b>{r.kind_label} · {fmtD(r.days)}</b>
                <span className="muted">{dayRange(r.start_date, r.end_date)}{r.note ? ` · ${r.note}` : ""}</span>
                {r.decision_note && <span className="muted">Yönetici notu: {r.decision_note}</span>}
              </div>
              <div className="ucard-meta"><StatusBadge status={r.status} label={r.status_label} /></div>
              {r.status === "pending" && (
                <div className="ucard-actions">
                  <button className="btn small" disabled={cancel.isPending} onClick={() => confirm("Talep iptal edilsin mi?") && cancel.mutate(r.id)}>İptal et</button>
                </div>
              )}
            </div>
          ))}
          {d && !d.rows.length && <div className="muted empty">Henüz izin kaydınız yok.</div>}
        </div>
      </div>
      {asking && <LeaveAsk onClose={() => setAsking(false)} />}
    </>
  );
}

function LeaveAsk({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [kind, setKind] = useState<LeaveKind>("annual");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<Leave>("/leave/me", { kind, start_date: start, end_date: end, note }),
    onSuccess: (r) => { toast(`Talebiniz iletildi: ${fmtD(r.days)}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title="İzin talebi" onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || !start || !end} onClick={() => save.mutate()}>Gönder</button>
      </>
    }>
      <div className="adm-form">
        <Field label="Tür">
          <select value={kind} onChange={(e) => setKind(e.target.value as LeaveKind)}>
            {LEAVE_KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </Field>
        <div className="adm-form two">
          <Field label="Başlangıç"><input type="date" value={start} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} /></Field>
          <Field label="Bitiş"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label="Not"><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="muted">Pazartesi ile cuma arasındaki günler sayılır. Yalnızca yıllık izin bakiyeden düşer.</p>
      </div>
    </Modal>
  );
}

/** Düzeltme taleplerim: unutulan çıkış, yanlış saat veya hiç girilmemiş mesai için yöneticiye talep. */
export function MyFixes() {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [asking, setAsking] = useState(false);
  const q = useQuery({ queryKey: ["attendance-me", "fixes"], queryFn: () => api.get<MyFixResp>("/attendance/requests/me") });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`/attendance/requests/${id}/cancel`, {}),
    onSuccess: () => { toast("Talep iptal edildi"); refresh(); },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      <div className="row" style={{ margin: "10px 0" }}>
        <button className="btn primary" onClick={() => setAsking(true)}>Düzeltme talebi</button>
      </div>
      <div className="card">
        <div className="ulist">
          {q.data?.rows.map((r) => (
            <div key={r.id} className="ucard">
              <div className="ucard-main">
                <b>{fmtDay(r.work_date)} · {fixTimes(r)}</b>
                <span className="muted">{r.current ? `Kayıtlı: ${r.current}` : "Yeni mesai"}</span>
                <span className="muted">{r.reason}</span>
                {r.decision_note && <span className="muted">Yönetici notu: {r.decision_note}</span>}
              </div>
              <div className="ucard-meta"><StatusBadge status={r.status} label={r.status_label} /></div>
              {r.status === "pending" && (
                <div className="ucard-actions">
                  <button className="btn small" disabled={cancel.isPending} onClick={() => confirm("Talep iptal edilsin mi?") && cancel.mutate(r.id)}>İptal et</button>
                </div>
              )}
            </div>
          ))}
          {q.data && !q.data.rows.length && <div className="muted empty">Düzeltme talebiniz yok.</div>}
        </div>
      </div>
      {asking && <FixAsk onClose={() => setAsking(false)} />}
    </>
  );
}

function FixAsk({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [day, setDay] = useState(today());
  const [shift, setShift] = useState<number | "">("");
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const month = day.slice(0, 7);
  const q = useQuery({
    queryKey: ["attendance-me", month], enabled: !!month,
    queryFn: () => api.get<{ rows: DayShift[] }>(`/attendance/me?month=${month}`),
  });
  const shifts = q.data?.rows.filter((s) => s.work_date === day) ?? [];
  const pick = (id: number | "") => {
    setShift(id);
    const s = shifts.find((x) => x.id === id);
    if (s) { setStart(s.start); setEnd(s.end ?? ""); }
  };
  const save = useMutation({
    mutationFn: () => api.post("/attendance/requests", { attendance_id: shift || null, work_date: day, clock_in: start, clock_out: end || null, reason }),
    onSuccess: () => { toast("Talebiniz iletildi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title="Mesai düzeltme talebi" onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || !day || !start || !reason.trim() || (!shift && !end)} onClick={() => save.mutate()}>Gönder</button>
      </>
    }>
      <div className="adm-form">
        <div className="adm-form two">
          <Field label="Tarih"><input type="date" value={day} max={today()} onChange={(e) => { setDay(e.target.value); setShift(""); }} /></Field>
          <Field label="Mesai">
            <select value={shift} onChange={(e) => pick(numOrNull(e.target.value) ?? "")}>
              <option value="">Kayıt yok, yeni mesai</option>
              {shifts.map((s) => <option key={s.id} value={s.id}>{s.start} – {s.end ?? "çıkış yok"}</option>)}
            </select>
          </Field>
          <Field label="Giriş"><input type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Çıkış"><input type="time" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label="Gerekçe"><input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
        <p className="muted">Çıkış girişten küçükse gece vardiyası sayılır. Yöneticiniz onaylayınca kayda işlenir.</p>
      </div>
    </Modal>
  );
}

/** Saat dağıtımı: günün mesaisinin hangi iş emrine veya projeye gittiği. Ücret bilgisi burada yoktur. */
export function MyHours() {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [day, setDay] = useState(today());
  const [edit, setEdit] = useState<Entry | null>(null);
  const q = useQuery({ queryKey: ["attendance-me", "time", day], enabled: !!day, queryFn: () => api.get<DayResp>(`/hr/me/time?day=${day}`) });
  const del = useMutation({
    mutationFn: (id: number) => api.del(`/hr/me/time/${id}`),
    onSuccess: () => { toast("Kayıt silindi"); setEdit(null); refresh(); },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  const d = q.data;
  return (
    <>
      <div className="row" style={{ margin: "10px 0" }}>
        <label className="row">Gün <input type="date" value={day} max={today()} onChange={(e) => { if (e.target.value) { setDay(e.target.value); setEdit(null); } }} /></label>
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {d && !d.employee && <div className="card empty">Hesabınıza bağlı bir personel kartı yok.</div>}
      {d?.employee && (
        <>
          <div className="grid stats">
            <Stat label="Mesai (net)" value={d.attended == null ? "Kayıt yok" : fmtH(d.attended)} sub={d.open ? "Mesai sürüyor, şu ana kadar" : undefined} />
            <Stat label="Dağıtılan" value={fmtH(d.allocated)} />
            <Stat label="Kalan" value={fmtH(d.remaining)} sub={d.attended == null ? "Mesai kaydı yoksa üst sınır 24 saat" : undefined} />
          </div>
          {d.forgot && <div className="card error">Bu günde çıkışınız unutulmuş; önce mesai düzeltme talebi açın.</div>}
          {d.editable
            ? <HoursForm key={edit?.id ?? "new"} day={day} entry={edit} left={d.remaining} onDone={() => setEdit(null)} />
            : <div className="card muted">{d.edit_days} günden eski kayıtları yalnızca yöneticiniz değiştirebilir.</div>}
          <div className="card">
            <div className="ulist">
              {d.rows.map((t) => (
                <div key={t.id} className="ucard">
                  <div className="ucard-main">
                    <b>{t.work_order_no ?? t.project_name}</b>
                    <span className="muted">{[t.work_order_no ? t.project_name : "", t.note].filter(Boolean).join(" · ")}</span>
                  </div>
                  <div className="ucard-meta"><b>{fmtH(t.hours)}</b></div>
                  {d.editable && (
                    <div className="ucard-actions">
                      <button className="btn small" onClick={() => setEdit(t)}>Düzenle</button>
                      <button className="btn small" disabled={del.isPending} onClick={() => confirm("Kayıt silinsin mi?") && del.mutate(t.id)}>Sil</button>
                    </div>
                  )}
                </div>
              ))}
              {!d.rows.length && <div className="muted empty">Bu güne saat yazılmamış.</div>}
            </div>
          </div>
        </>
      )}
    </>
  );
}

function HoursForm({ day, entry, left, onDone }: { day: string; entry: Entry | null; left: number; onDone: () => void }) {
  const toast = useToast();
  const refresh = useAttRefresh();
  const current = entry?.work_order_id ? `w${entry.work_order_id}` : entry?.project_id ? `p${entry.project_id}` : "";
  const [target, setTarget] = useState(current);
  const [hours, setHours] = useState(entry ? String(entry.hours) : left > 0 && left < 24 ? String(left) : "");
  const [note, setNote] = useState(entry?.note ?? "");
  const opts = useQuery({ queryKey: ["attendance-me", "time-options"], queryFn: () => api.get<Options>("/hr/me/time/options") });
  const save = useMutation({
    mutationFn: () => {
      const id = Number(target.slice(1));
      const body = { work_date: day, hours: numOrNull(hours), note, work_order_id: target[0] === "w" ? id : null, project_id: target[0] === "p" ? id : null };
      return entry ? api.put(`/hr/me/time/${entry.id}`, body) : api.post("/hr/me/time", body);
    },
    onSuccess: () => { toast("Saat kaydedildi"); refresh(); setTarget(""); setHours(""); setNote(""); onDone(); },
    onError: (e) => toast(errText(e), true),
  });
  const h = numOrNull(hours) ?? 0;
  const known = !current || opts.data?.work_orders.some((w) => `w${w.id}` === current) || opts.data?.projects.some((p) => `p${p.id}` === current);
  return (
    <div className="card">
      <b>{entry ? "Kaydı düzenle" : "Saat yaz"}</b>
      <div className="adm-form two" style={{ marginTop: 8 }}>
        <Field label="İş emri veya proje">
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Seçin</option>
            {!known && <option value={current}>{entry?.work_order_no ?? entry?.project_name}</option>}
            <optgroup label="Açık iş emirleri">
              {opts.data?.work_orders.map((w) => <option key={w.id} value={`w${w.id}`}>{w.no}{w.description ? ` · ${w.description}` : ""}</option>)}
            </optgroup>
            <optgroup label="Projeler">
              {opts.data?.projects.map((p) => <option key={p.id} value={`p${p.id}`}>{p.name}</option>)}
            </optgroup>
          </select>
        </Field>
        <Field label="Saat"><input inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} /></Field>
      </div>
      <Field label="Not"><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary" disabled={!target || h <= 0 || h > 24 || save.isPending} onClick={() => save.mutate()}>{entry ? "Kaydet" : "Ekle"}</button>
        {entry && <button className="btn" onClick={onDone}>Vazgeç</button>}
      </div>
    </div>
  );
}
