import { useMutation, useQuery } from "@tanstack/react-query";
import { LogIn, LogOut, Timer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { saveRev } from "../api/conflict";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal } from "./admin/shared";
import { fmtDay, numOrNull, today } from "./erp/common";
import { Stat } from "./erp/commerce";
import { FixQueue, LeaveQueue, usePeople } from "./AttendanceQueues";
import { MyFixes, MyHours, MyLeaves, fmtH, useAttRefresh as useRefresh } from "./SelfService";
import { LOCALE, tx } from "../api/i18n";

type Shift = {
  rev?: number;
  id: number; employee_id: number; employee_name: string; work_date: string; start: string; end: string | null;
  next_day: boolean; break_minutes: number; hours: number; overtime: number; status: "open" | "forgot" | "done";
  note: string; corrected_by: string;
};
type Summary = { hours: number; overtime: number; days: number; forgot: number; expected: number; covered: number; missing_days: number; short: number };
type LeaveDay = { employee_id: number; employee_name: string; work_date: string; kind: string; label: string };
type MyResp = {
  employee: { id: number; name: string } | null; open: { id: number; clock_in: string } | null;
  rows: Shift[]; leave_days: LeaveDay[]; summary: Summary; week_hours?: number;
};
type Person = Summary & { employee_id: number; name: string; department: string; inside: boolean; leave: Record<string, number> };
type AllResp = { rows: Shift[]; people: Person[]; total: Summary; inside: number; leave_days: LeaveDay[] };
type GridRow = Shift & { leave?: string };
type Tab = "all" | "leave" | "fixes" | "me" | "my-leave" | "my-fixes" | "my-hours";

const STATUS: Record<Shift["status"], string> = { open: tx("İçeride"), forgot: tx("Çıkış unutuldu"), done: tx("Tamam") };
const thisMonth = () => today().slice(0, 7);
const monthEnd = (m: string) => {
  const [y, mo] = m.split("-").map(Number);
  return `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, "0")}`;
};
const endText = (s: Shift) => (s.end ? `${s.end}${s.next_day ? " (+1)" : ""}` : "");

/** A leave day as a row of the shift grid, so the day reads izinli instead of looking empty. */
const leaveRow = (l: LeaveDay): GridRow => ({
  id: 0, employee_id: l.employee_id, employee_name: l.employee_name, work_date: l.work_date, start: "", end: null, next_day: false,
  break_minutes: 0, hours: 0, overtime: 0, status: "done", note: "", corrected_by: "", leave: l.label,
});
const leaveCount = (p: Person) => Object.values(p.leave).reduce((a, b) => a + b, 0);

/** Mesai takibi: herkes yalnızca kendi mesaisini görür; mesai yetkisi olan tüm personeli görür ve düzeltir. */
export default function Attendance() {
  const manager = useAuth().can("attendance");
  const [tab, setTab] = useState<Tab>(manager ? "all" : "me");
  const queue = useQuery({ queryKey: ["attendance", "queue"], enabled: manager, queryFn: () => api.get<{ leave: number; shifts: number }>("/attendance/queue") });
  const mine = useQuery({ queryKey: ["attendance-me", thisMonth()], queryFn: () => api.get<MyResp>(`/attendance/me?month=${thisMonth()}`) });
  const tabs: [Tab, string, number?][] = [
    ...(manager ? [["all", tx("Tüm personel")], ["leave", tx("İzin talepleri"), queue.data?.leave], ["fixes", tx("Düzeltme talepleri"), queue.data?.shifts]] as [Tab, string, number?][] : []),
    ["me", manager ? tx("Benim mesaim") : tx("Mesaim")],
    ...(mine.data?.employee ? [["my-leave", tx("İzinlerim")], ["my-fixes", tx("Düzeltme taleplerim")], ["my-hours", tx("Saat dağıtımı")]] as [Tab, string][] : []),
  ];
  return (
    <Page>
      <PageHeader icon={Timer} title={tx("Mesai takibi")} sub={manager ? tx("Giriş ve çıkış saatleri, izinler ve talepler") : tx("Yalnızca size ait kayıtlar")} />
      {tabs.length > 1 && (
        <div className="tabs" role="tablist">
          {tabs.map(([k, label, n]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
              {label}{n ? <> <span className="badge warn">{n}</span></> : null}
            </button>
          ))}
        </div>
      )}
      {tab === "all" && manager && <AllTab />}
      {tab === "leave" && manager && <LeaveQueue />}
      {tab === "fixes" && manager && <FixQueue />}
      {tab === "me" && <MyTab />}
      {tab === "my-leave" && <MyLeaves />}
      {tab === "my-fixes" && <MyFixes />}
      {tab === "my-hours" && <MyHours />}
    </Page>
  );
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const min = Math.max(0, Math.floor((now - new Date(since).getTime()) / 60_000));
  return <>{tx("{0} sa", Math.floor(min / 60))}{" "}{min % 60}{" "}{tx("dk")}</>;
}

function MyTab() {
  const toast = useToast();
  const refresh = useRefresh();
  const [month, setMonth] = useState(thisMonth());
  const q = useQuery({ queryKey: ["attendance-me", month], queryFn: () => api.get<MyResp>(`/attendance/me?month=${month}`) });
  const clock = useMutation({
    mutationFn: (way: "in" | "out") => api.post<{ hours?: number; break_minutes?: number }>(`/attendance/clock-${way}`, {}),
    onSuccess: (r, way) => {
      refresh();
      toast(way === "in" ? tx("Giriş kaydedildi") : tx("Çıkış kaydedildi: {0}{1}", fmtH(r.hours ?? 0), r.break_minutes ? tx(", {0} dk mola düşüldü", r.break_minutes) : ""));
    },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  const d = q.data;
  const days = useMemo(() => [
    ...(d?.rows ?? []).map((s) => ({ day: s.work_date, s, l: null })),
    ...(d?.leave_days ?? []).map((l) => ({ day: l.work_date, s: null, l })),
  ].sort((a, b) => b.day.localeCompare(a.day)), [d]);
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      {d && !d.employee && (
        <div className="card empty">{tx("Hesabınıza bağlı bir personel kartı yok. Kartınızın hesabınıza bağlanması için yöneticinize başvurun.")}</div>
      )}
      {d?.employee && (
        <>
          <div className="card att-clock">
            <div>
              <b>{d.employee.name}</b>
              <div className="muted">
                {d.open
                  ? <>{tx("Giriş {0},", new Date(d.open.clock_in).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }))}{" "}<Elapsed since={d.open.clock_in} />{" "}{tx("geçti")}</>
                  : tx("Şu an mesaide değilsiniz")}
              </div>
            </div>
            <button className={`btn att-btn${d.open ? "" : " primary"}`} disabled={clock.isPending} onClick={() => clock.mutate(d.open ? "out" : "in")}>
              {d.open ? <LogOut size={18} /> : <LogIn size={18} />}{d.open ? tx("Çıkış yap") : tx("Giriş yap")}
            </button>
          </div>
          <div className="row" style={{ margin: "10px 0" }}>
            <label className="row">{tx("Ay")}{" "}<input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
          </div>
          <div className="grid stats">
            <Stat label={tx("Çalışılan saat")} value={fmtH(d.summary.hours)} />
            <Stat label={tx("Fazla mesai")} value={fmtH(d.summary.overtime)} sub={d.week_hours ? tx("Haftalık {0} saatin üstü", d.week_hours) : undefined} />
            <Stat label={tx("Çalışılan gün")} value={d.summary.days} />
            <Stat label={tx("Beklenen saat")} value={fmtH(d.summary.expected)} sub={d.summary.covered ? tx("{0} izinle karşılandı", fmtH(d.summary.covered)) : tx("Geçen iş günleri")} />
            {d.leave_days.length > 0 && <Stat label={tx("İzinli gün")} value={d.leave_days.length} />}
            {d.summary.missing_days > 0 && <Stat label={tx("Eksik gün")} value={d.summary.missing_days} tone="warn" sub={tx("Mesai veya izin kaydı yok")} />}
            {d.summary.forgot > 0 && <Stat label={tx("Çıkış unutuldu")} value={d.summary.forgot} tone="warn" sub={tx("Düzeltme talebi açın")} />}
          </div>
          <div className="card">
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>{tx("Tarih")}</th><th>{tx("Giriş")}</th><th>{tx("Çıkış")}</th><th className="num">{tx("Mola")}</th><th className="num">{tx("Saat")}</th><th className="num">{tx("Fazla")}</th><th>{tx("Durum")}</th><th>{tx("Not")}</th></tr></thead>
                <tbody>
                  {days.map(({ s, l }) => (l ? (
                    <tr key={`l${l.work_date}`}>
                      <td>{fmtDay(l.work_date)}</td><td colSpan={5} /><td><span className="badge">{l.label}</span></td><td />
                    </tr>
                  ) : s && (
                    <tr key={s.id}>
                      <td>{fmtDay(s.work_date)}</td><td>{s.start}</td><td>{endText(s)}</td>
                      <td className="num">{s.break_minutes ? `${s.break_minutes} dk` : ""}</td>
                      <td className="num">{s.end ? fmtH(s.hours) : ""}</td>
                      <td className="num">{s.overtime ? fmtH(s.overtime) : ""}</td>
                      <td className={s.status === "forgot" ? "error" : ""}>{STATUS[s.status]}{s.corrected_by ? <span className="muted">{" "}{tx("· düzeltildi")}</span> : null}</td>
                      <td className="muted">{s.note}</td>
                    </tr>
                  )))}
                  {!days.length && <tr><td colSpan={8} className="muted empty">{tx("Bu ay kayıt yok.")}</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function AllTab() {
  const canEdit = useAuth().can("attendance", "edit");
  const [from, setFrom] = useState(`${thisMonth()}-01`);
  const [to, setTo] = useState(monthEnd(thisMonth()));
  const [emp, setEmp] = useState<number | "">("");
  const [edit, setEdit] = useState<Shift | "new" | null>(null);
  const people = usePeople();
  const params = `date_from=${from}&date_to=${to}${emp ? `&employee_id=${emp}` : ""}`;
  const q = useQuery({ queryKey: ["attendance", params], queryFn: () => api.get<AllResp>(`/attendance?${params}`), enabled: !!from && !!to });
  const d = q.data;
  const grid = useMemo(() => [...(d?.rows ?? []) as GridRow[], ...(d?.leave_days ?? []).map(leaveRow)]
    .sort((a, b) => b.work_date.localeCompare(a.work_date)), [d]);
  const columns = useMemo<GridColumn<GridRow>[]>(() => [
    { accessorKey: "employee_name", header: tx("Personel"), size: 170, card: "title" },
    { id: "day", header: tx("Tarih"), size: 105, card: "sub", accessorFn: (s) => fmtDay(s.work_date) },
    { accessorKey: "start", header: tx("Giriş"), size: 75, card: "field" },
    { id: "end", header: tx("Çıkış"), size: 85, card: "field", accessorFn: endText },
    { accessorKey: "break_minutes", header: tx("Mola (dk)"), size: 85, card: "field" },
    { accessorKey: "hours", header: tx("Saat"), size: 75, card: "field" },
    { accessorKey: "overtime", header: tx("Fazla Mesai"), size: 95, card: "field" },
    { id: "status", header: tx("Durum"), size: 130, card: "badge", accessorFn: (s) => s.leave ?? STATUS[s.status] },
    { accessorKey: "note", header: tx("Not"), size: 200, card: "field" },
    { accessorKey: "corrected_by", header: tx("Düzelten"), size: 110, card: "hide" },
  ], []);
  return (
    <>
      <div className="row" style={{ margin: "10px 0", flexWrap: "wrap" }}>
        <label className="row">{tx("Başlangıç")}{" "}<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row">{tx("Bitiş")}{" "}<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <select aria-label={tx("Personel")} value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
          <option value="">{tx("Tüm personel")}</option>
          {people.data?.map((p) => <option key={p.employee_id} value={p.employee_id}>{p.name}</option>)}
        </select>
        {canEdit && <button className="btn primary" onClick={() => setEdit("new")}>{tx("Mesai ekle")}</button>}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {d && (
        <>
          <div className="grid stats">
            <Stat label={tx("Şu an içeride")} value={d.inside} />
            <Stat label={tx("Toplam saat")} value={fmtH(d.total.hours)} />
            <Stat label={tx("Fazla mesai")} value={fmtH(d.total.overtime)} />
            <Stat label={tx("Beklenen saat")} value={fmtH(d.total.expected)} sub={d.total.covered ? tx("{0} izinle karşılandı", fmtH(d.total.covered)) : tx("Geçen iş günleri")} />
            <Stat label={tx("Eksik gün")} value={d.total.missing_days} tone={d.total.missing_days ? "warn" : undefined} sub={tx("Mesai veya izin kaydı yok")} />
            <Stat label={tx("Çıkış unutulan")} value={d.total.forgot} tone={d.total.forgot ? "warn" : undefined} />
          </div>
          <div className="card">
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>{tx("Personel")}</th><th>{tx("Bölüm")}</th><th>{tx("Şimdi")}</th><th className="num">{tx("Gün")}</th><th className="num">{tx("Saat")}</th><th className="num">{tx("Beklenen")}</th><th className="num">{tx("İzin karşılığı")}</th><th className="num">{tx("Eksik saat")}</th><th className="num">{tx("İzinli gün")}</th><th className="num">{tx("Eksik gün")}</th><th className="num">{tx("Fazla mesai")}</th><th className="num">{tx("Çıkış yok")}</th></tr></thead>
                <tbody>
                  {d.people.map((p) => (
                    <tr key={p.employee_id}>
                      <td><b>{p.name}</b></td><td className="muted">{p.department}</td>
                      <td>{p.inside ? tx("İçeride") : <span className="muted">{tx("Dışarıda")}</span>}</td>
                      <td className="num">{p.days}</td><td className="num">{fmtH(p.hours)}</td>
                      <td className="num">{fmtH(p.expected)}</td>
                      <td className="num">{p.covered ? fmtH(p.covered) : ""}</td>
                      <td className="num">{p.short ? fmtH(p.short) : ""}</td>
                      <td className="num">{leaveCount(p) || ""}</td>
                      <td className={`num${p.missing_days ? " error" : ""}`}>{p.missing_days || ""}</td>
                      <td className="num">{p.overtime ? fmtH(p.overtime) : ""}</td>
                      <td className={`num${p.forgot ? " error" : ""}`}>{p.forgot || ""}</td>
                    </tr>
                  ))}
                  {!d.people.length && <tr><td colSpan={12} className="muted empty">{tx("Personel kartı yok.")}</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
          <DataGrid data={grid} columns={columns} getRowId={(s) => (s.leave ? `l${s.employee_id}-${s.work_date}` : String(s.id))} exportName={`mesai_${from}_${to}`} stateKey="attendance"
            emptyText={tx("Bu aralıkta mesai kaydı yok.")} onRowClick={canEdit ? (s) => { if (!s.leave) setEdit(s); } : undefined} openOnClick />
        </>
      )}
      {edit && <ShiftModal shift={edit === "new" ? null : edit} onClose={() => setEdit(null)} />}
    </>
  );
}

function ShiftModal({ shift, onClose }: { shift: Shift | null; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const people = usePeople();
  const [emp, setEmp] = useState<number | "">(shift?.employee_id ?? "");
  const [day, setDay] = useState(shift?.work_date ?? today());
  const [start, setStart] = useState(shift?.start ?? "08:00");
  const [end, setEnd] = useState(shift?.end ?? "");
  const [pause, setPause] = useState(shift ? String(shift.break_minutes) : "");
  const [note, setNote] = useState(shift?.note ?? "");
  const [sure, setSure] = useState(false);
  const done = (msg: string) => { refresh(); toast(msg); onClose(); };
  const save = useMutation({
    mutationFn: () => {
      const body = { work_date: day, start, end: end || null, break_minutes: numOrNull(pause), note };
      return shift ? saveRev(shift.rev, (rev) => api.put(`/attendance/${shift.id}`, { ...body, rev })) : api.post("/attendance", { ...body, employee_id: emp });
    },
    onSuccess: () => done(tx("Mesai kaydedildi")),
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/attendance/${shift!.id}`),
    onSuccess: () => done(tx("Mesai silindi")),
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={shift ? `${shift.employee_name} mesaisi` : tx("Mesai ekle")} onClose={onClose} footer={
      <>
        {shift && (
          <button className="btn" style={{ marginRight: "auto" }} disabled={del.isPending} onClick={() => (sure ? del.mutate() : setSure(true))}>
            {sure ? tx("Silmeyi onayla") : tx("Sil")}
          </button>
        )}
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending || !day || !start || (!shift && !emp)} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>
    }>
      <div className="adm-form two">
        {!shift && (
          <Field label={tx("Personel")}>
            <select value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
              <option value="">{tx("Seçin")}</option>
              {people.data?.map((p) => <option key={p.employee_id} value={p.employee_id}>{p.name}</option>)}
            </select>
          </Field>
        )}
        <Field label={tx("Tarih")}><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label={tx("Giriş")}><input type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label={tx("Çıkış")}><input type="time" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Field label={tx("Mola (dk)")}><input type="number" min={0} value={pause} placeholder={tx("Boşsa ayardan gelir")} onChange={(e) => setPause(e.target.value)} /></Field>
        <Field label={tx("Not")}><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <p className="muted">{tx("Çıkış girişten küçükse gece vardiyası sayılır ve ertesi güne yazılır.")}</p>
    </Modal>
  );
}
