import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal } from "./admin/shared";
import { fmtDay, numOrNull, today } from "./erp/common";
import { LEAVE_KINDS, StatusBadge, dayRange, fixTimes, useAttRefresh, type Fix, type Leave, type LeaveKind } from "./SelfService";

type PersonPick = { employee_id: number; name: string };
type Queue<T> = { rows: T[]; pending: number };

/** Everyone with a card, for the pickers; the summary of a filtered query holds only the chosen person. */
export function usePeople() {
  return useQuery({
    queryKey: ["attendance", "people"],
    queryFn: () => api.get<{ people: PersonPick[] }>(`/attendance?date_from=${today()}&date_to=${today()}`),
    select: (d) => d.people,
  });
}

/** İzin talepleri: filtreli liste, onay veya ret, doğrudan izin girişi, onaylı izni iptal. */
export function LeaveQueue() {
  const canEdit = useAuth().can("attendance", "edit");
  const people = usePeople();
  const [status, setStatus] = useState("pending");
  const [kind, setKind] = useState("");
  const [emp, setEmp] = useState<number | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [act, setAct] = useState<{ row: Leave; way: "decide" | "cancel" } | null>(null);
  const [adding, setAdding] = useState(false);
  const p = new URLSearchParams();
  if (status) p.set("status", status);
  if (kind) p.set("kind", kind);
  if (emp) p.set("employee_id", String(emp));
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  const q = useQuery({ queryKey: ["attendance", "leave", p.toString()], queryFn: () => api.get<Queue<Leave>>(`/leave?${p}`) });
  return (
    <>
      <div className="row" style={{ margin: "10px 0", flexWrap: "wrap" }}>
        <select aria-label="Durum" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Bekleyen</option><option value="approved">Onaylı</option>
          <option value="rejected">Reddedilen</option><option value="cancelled">İptal</option><option value="">Tümü</option>
        </select>
        <select aria-label="Tür" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Tüm türler</option>
          {LEAVE_KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <select aria-label="Personel" value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
          <option value="">Tüm personel</option>
          {people.data?.map((x) => <option key={x.employee_id} value={x.employee_id}>{x.name}</option>)}
        </select>
        <label className="row">Başlangıç <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row">Bitiş <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        {canEdit && <button className="btn primary" onClick={() => setAdding(true)}>İzin gir</button>}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      <div className="card">
        <div className="ulist">
          {q.data?.rows.map((r) => (
            <div key={r.id} className="ucard">
              <div className="ucard-main">
                <b>{r.employee_name}</b>
                <span className="muted">{r.kind_label} · {dayRange(r.start_date, r.end_date)} · {r.days} gün{r.free_days != null ? ` · bakiye ${r.free_days} gün` : ""}</span>
                {r.note && <span className="muted">{r.note}</span>}
                {r.decision_note && <span className="muted">Karar notu: {r.decision_note}{r.decided_by ? ` (${r.decided_by})` : ""}</span>}
              </div>
              <div className="ucard-meta"><StatusBadge status={r.status} label={r.status_label} /></div>
              {canEdit && r.status === "pending" && <div className="ucard-actions"><button className="btn small primary" onClick={() => setAct({ row: r, way: "decide" })}>Karar ver</button></div>}
              {canEdit && r.status === "approved" && <div className="ucard-actions"><button className="btn small" onClick={() => setAct({ row: r, way: "cancel" })}>İptal et</button></div>}
            </div>
          ))}
          {q.data && !q.data.rows.length && <div className="muted empty">Bu seçimde izin kaydı yok.</div>}
        </div>
      </div>
      {act && <LeaveDecision row={act.row} way={act.way} onClose={() => setAct(null)} />}
      {adding && <LeaveEntryForm people={people.data ?? []} onClose={() => setAdding(false)} />}
    </>
  );
}

function LeaveDecision({ row, way, onClose }: { row: Leave; way: "decide" | "cancel"; onClose: () => void }) {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [note, setNote] = useState("");
  const go = useMutation({
    mutationFn: (approve: boolean) => (way === "cancel"
      ? api.post(`/leave/${row.id}/cancel`, { note })
      : api.post(`/leave/${row.id}/decide`, { approve, note })),
    onSuccess: () => { toast("Kaydedildi"); refresh(); onClose(); },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  return (
    <Modal title={`${row.employee_name}: ${row.kind_label}`} onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        {way === "cancel"
          ? <button className="btn primary" disabled={go.isPending} onClick={() => go.mutate(false)}>İzni iptal et</button>
          : <>
            <button className="btn" disabled={go.isPending} onClick={() => go.mutate(false)}>Reddet</button>
            <button className="btn primary" disabled={go.isPending} onClick={() => go.mutate(true)}>Onayla</button>
          </>}
      </>
    }>
      <p>{dayRange(row.start_date, row.end_date)} · {row.days} gün</p>
      {row.note && <p className="muted">{row.note}</p>}
      {row.free_days != null && <p className="muted">Kullanılabilir bakiye: {row.free_days} gün</p>}
      <div className="adm-form"><Field label="Not"><input autoFocus value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field></div>
    </Modal>
  );
}

function LeaveEntryForm({ people, onClose }: { people: PersonPick[]; onClose: () => void }) {
  const toast = useToast();
  const refresh = useAttRefresh();
  const [emp, setEmp] = useState<number | "">("");
  const [kind, setKind] = useState<LeaveKind>("sick");
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post("/leave", { employee_id: emp, kind, start_date: start, end_date: end, note }),
    onSuccess: () => { toast("İzin kaydedildi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title="İzin gir" onClose={onClose} footer={
      <>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || !emp || !start || !end} onClick={() => save.mutate()}>Kaydet</button>
      </>
    }>
      <div className="adm-form two">
        <Field label="Personel">
          <select value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
            <option value="">Seçin</option>
            {people.map((p) => <option key={p.employee_id} value={p.employee_id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Tür">
          <select value={kind} onChange={(e) => setKind(e.target.value as LeaveKind)}>
            {LEAVE_KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </Field>
        <Field label="Başlangıç"><input type="date" value={start} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} /></Field>
        <Field label="Bitiş"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Field label="Not"><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <p className="muted">Doğrudan onaylı kaydedilir.</p>
    </Modal>
  );
}

/** Düzeltme talepleri: bekleyen kuyruk, tek tıkla onay veya ret. */
export function FixQueue() {
  const canEdit = useAuth().can("attendance", "edit");
  const toast = useToast();
  const refresh = useAttRefresh();
  const [status, setStatus] = useState("pending");
  const q = useQuery({
    queryKey: ["attendance", "fixes", status],
    queryFn: () => api.get<Queue<Fix>>(`/attendance/requests${status ? `?status=${status}` : ""}`),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) => api.post(`/attendance/requests/${id}/decide`, { approve }),
    onSuccess: (_, v) => { toast(v.approve ? "Talep onaylandı, mesai güncellendi" : "Talep reddedildi"); refresh(); },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  return (
    <>
      <div className="row" style={{ margin: "10px 0" }}>
        <select aria-label="Durum" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Bekleyen</option><option value="approved">Onaylı</option>
          <option value="rejected">Reddedilen</option><option value="cancelled">İptal</option><option value="">Tümü</option>
        </select>
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      <div className="card">
        <div className="ulist">
          {q.data?.rows.map((r) => (
            <div key={r.id} className="ucard">
              <div className="ucard-main">
                <b>{r.employee_name}</b>
                <span className="muted">{fmtDay(r.work_date)} · {r.status === "pending" ? "İstenen" : "Talep"}: {fixTimes(r)}</span>
                <span className="muted">{r.current ? `Kayıtlı: ${r.current}` : r.status === "pending" ? "Yeni mesai" : ""}</span>
                <span className="muted">{r.reason}</span>
                {r.decision_note && <span className="muted">Karar notu: {r.decision_note}</span>}
              </div>
              <div className="ucard-meta"><StatusBadge status={r.status} label={r.status_label} /></div>
              {canEdit && r.status === "pending" && (
                <div className="ucard-actions">
                  <button className="btn small" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: false })}>Reddet</button>
                  <button className="btn small primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: r.id, approve: true })}>Onayla</button>
                </div>
              )}
            </div>
          ))}
          {q.data && !q.data.rows.length && <div className="muted empty">Bu seçimde talep yok.</div>}
        </div>
      </div>
    </>
  );
}
