import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut, Timer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal } from "./admin/shared";
import { fmtDay, numOrNull, today } from "./erp/common";
import { Stat } from "./erp/commerce";

type Shift = {
  id: number; employee_id: number; employee_name: string; work_date: string; start: string; end: string | null;
  next_day: boolean; break_minutes: number; hours: number; overtime: number; status: "open" | "forgot" | "done";
  note: string; corrected_by: string;
};
type Summary = { hours: number; overtime: number; days: number; forgot: number };
type MyResp = {
  employee: { id: number; name: string } | null; open: { id: number; clock_in: string } | null;
  rows: Shift[]; summary: Summary; week_hours?: number;
};
type Person = Summary & { employee_id: number; name: string; department: string; inside: boolean };
type AllResp = { rows: Shift[]; people: Person[]; total: Summary; inside: number };

const fmtH = (h: number) => `${h.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} sa`;
const STATUS: Record<Shift["status"], string> = { open: "İçeride", forgot: "Çıkış unutuldu", done: "Tamam" };
const thisMonth = () => today().slice(0, 7);
const monthEnd = (m: string) => {
  const [y, mo] = m.split("-").map(Number);
  return `${m}-${String(new Date(y, mo, 0).getDate()).padStart(2, "0")}`;
};
const endText = (s: Shift) => (s.end ? `${s.end}${s.next_day ? " (+1)" : ""}` : "");

/** Everyone with a card, for the pickers; the summary of a filtered query holds only the chosen person. */
function usePeople() {
  return useQuery({
    queryKey: ["attendance", "people"],
    queryFn: () => api.get<AllResp>(`/attendance?date_from=${today()}&date_to=${today()}`),
    select: (d) => d.people,
  });
}

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["attendance-me", "attendance"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Mesai takibi: herkes yalnızca kendi mesaisini görür; mesai yetkisi olan tüm personeli görür ve düzeltir. */
export default function Attendance() {
  const manager = useAuth().can("attendance");
  const [tab, setTab] = useState<"me" | "all">(manager ? "all" : "me");
  return (
    <Page>
      <PageHeader icon={Timer} title="Mesai takibi" sub={manager ? "Giriş ve çıkış saatleri, fazla mesai" : "Yalnızca size ait mesai kayıtları"} />
      {manager && (
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "all"} className={tab === "all" ? "active" : ""} onClick={() => setTab("all")}>Tüm personel</button>
          <button role="tab" aria-selected={tab === "me"} className={tab === "me" ? "active" : ""} onClick={() => setTab("me")}>Benim mesaim</button>
        </div>
      )}
      {tab === "all" && manager ? <AllTab /> : <MyTab />}
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
  return <>{Math.floor(min / 60)} sa {min % 60} dk</>;
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
      toast(way === "in" ? "Giriş kaydedildi" : `Çıkış kaydedildi: ${fmtH(r.hours ?? 0)}${r.break_minutes ? `, ${r.break_minutes} dk mola düşüldü` : ""}`);
    },
    onError: (e) => { refresh(); toast(errText(e), true); },
  });
  const d = q.data;
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      {d && !d.employee && (
        <div className="card empty">Hesabınıza bağlı bir personel kartı yok. Kartınızın hesabınıza bağlanması için yöneticinize başvurun.</div>
      )}
      {d?.employee && (
        <>
          <div className="card att-clock">
            <div>
              <b>{d.employee.name}</b>
              <div className="muted">
                {d.open
                  ? <>Giriş {new Date(d.open.clock_in).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}, <Elapsed since={d.open.clock_in} /> geçti</>
                  : "Şu an mesaide değilsiniz"}
              </div>
            </div>
            <button className={`btn att-btn${d.open ? "" : " primary"}`} disabled={clock.isPending} onClick={() => clock.mutate(d.open ? "out" : "in")}>
              {d.open ? <LogOut size={18} /> : <LogIn size={18} />}{d.open ? "Çıkış yap" : "Giriş yap"}
            </button>
          </div>
          <div className="row" style={{ margin: "10px 0" }}>
            <label className="row">Ay <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
          </div>
          <div className="grid stats">
            <Stat label="Çalışılan saat" value={fmtH(d.summary.hours)} />
            <Stat label="Fazla mesai" value={fmtH(d.summary.overtime)} sub={d.week_hours ? `Haftalık ${d.week_hours} saatin üstü` : undefined} />
            <Stat label="Çalışılan gün" value={d.summary.days} />
            {d.summary.forgot > 0 && <Stat label="Çıkış unutuldu" value={d.summary.forgot} tone="warn" sub="Yöneticiniz düzeltir" />}
          </div>
          <div className="card">
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>Tarih</th><th>Giriş</th><th>Çıkış</th><th className="num">Mola</th><th className="num">Saat</th><th className="num">Fazla</th><th>Durum</th><th>Not</th></tr></thead>
                <tbody>
                  {d.rows.map((s) => (
                    <tr key={s.id}>
                      <td>{fmtDay(s.work_date)}</td><td>{s.start}</td><td>{endText(s)}</td>
                      <td className="num">{s.break_minutes ? `${s.break_minutes} dk` : ""}</td>
                      <td className="num">{s.end ? fmtH(s.hours) : ""}</td>
                      <td className="num">{s.overtime ? fmtH(s.overtime) : ""}</td>
                      <td className={s.status === "forgot" ? "error" : ""}>{STATUS[s.status]}{s.corrected_by ? <span className="muted"> · düzeltildi</span> : null}</td>
                      <td className="muted">{s.note}</td>
                    </tr>
                  ))}
                  {!d.rows.length && <tr><td colSpan={8} className="muted empty">Bu ay kayıt yok.</td></tr>}
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
  const columns = useMemo<GridColumn<Shift>[]>(() => [
    { accessorKey: "employee_name", header: "Personel", size: 170, card: "title" },
    { id: "day", header: "Tarih", size: 105, card: "sub", accessorFn: (s) => fmtDay(s.work_date) },
    { accessorKey: "start", header: "Giriş", size: 75, card: "field" },
    { id: "end", header: "Çıkış", size: 85, card: "field", accessorFn: endText },
    { accessorKey: "break_minutes", header: "Mola (dk)", size: 85, card: "field" },
    { accessorKey: "hours", header: "Saat", size: 75, card: "field" },
    { accessorKey: "overtime", header: "Fazla Mesai", size: 95, card: "field" },
    { id: "status", header: "Durum", size: 130, card: "badge", accessorFn: (s) => STATUS[s.status] },
    { accessorKey: "note", header: "Not", size: 200, card: "field" },
    { accessorKey: "corrected_by", header: "Düzelten", size: 110, card: "hide" },
  ], []);
  return (
    <>
      <div className="row" style={{ margin: "10px 0", flexWrap: "wrap" }}>
        <label className="row">Başlangıç <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row">Bitiş <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <select aria-label="Personel" value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
          <option value="">Tüm personel</option>
          {people.data?.map((p) => <option key={p.employee_id} value={p.employee_id}>{p.name}</option>)}
        </select>
        {canEdit && <button className="btn primary" onClick={() => setEdit("new")}>Mesai ekle</button>}
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {d && (
        <>
          <div className="grid stats">
            <Stat label="Şu an içeride" value={d.inside} />
            <Stat label="Toplam saat" value={fmtH(d.total.hours)} />
            <Stat label="Fazla mesai" value={fmtH(d.total.overtime)} />
            <Stat label="Çıkış unutulan" value={d.total.forgot} tone={d.total.forgot ? "warn" : undefined} />
          </div>
          <div className="card">
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>Personel</th><th>Bölüm</th><th>Şimdi</th><th className="num">Gün</th><th className="num">Saat</th><th className="num">Fazla mesai</th><th className="num">Çıkış yok</th></tr></thead>
                <tbody>
                  {d.people.map((p) => (
                    <tr key={p.employee_id}>
                      <td><b>{p.name}</b></td><td className="muted">{p.department}</td>
                      <td>{p.inside ? "İçeride" : <span className="muted">Dışarıda</span>}</td>
                      <td className="num">{p.days}</td><td className="num">{fmtH(p.hours)}</td>
                      <td className="num">{p.overtime ? fmtH(p.overtime) : ""}</td>
                      <td className={`num${p.forgot ? " error" : ""}`}>{p.forgot || ""}</td>
                    </tr>
                  ))}
                  {!d.people.length && <tr><td colSpan={7} className="muted empty">Personel kartı yok.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
          <DataGrid data={d.rows} columns={columns} getRowId={(s) => String(s.id)} exportName={`mesai_${from}_${to}`} stateKey="attendance"
            emptyText="Bu aralıkta mesai kaydı yok." onRowClick={canEdit ? setEdit : undefined} openOnClick />
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
      return shift ? api.put(`/attendance/${shift.id}`, body) : api.post("/attendance", { ...body, employee_id: emp });
    },
    onSuccess: () => done("Mesai kaydedildi"),
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/attendance/${shift!.id}`),
    onSuccess: () => done("Mesai silindi"),
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={shift ? `${shift.employee_name} mesaisi` : "Mesai ekle"} onClose={onClose} footer={
      <>
        {shift && (
          <button className="btn" style={{ marginRight: "auto" }} disabled={del.isPending} onClick={() => (sure ? del.mutate() : setSure(true))}>
            {sure ? "Silmeyi onayla" : "Sil"}
          </button>
        )}
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || !day || !start || (!shift && !emp)} onClick={() => save.mutate()}>Kaydet</button>
      </>
    }>
      <div className="adm-form two">
        {!shift && (
          <Field label="Personel">
            <select value={emp} onChange={(e) => setEmp(numOrNull(e.target.value) ?? "")}>
              <option value="">Seçin</option>
              {people.data?.map((p) => <option key={p.employee_id} value={p.employee_id}>{p.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Tarih"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Giriş"><input type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Çıkış"><input type="time" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <Field label="Mola (dk)"><input type="number" min={0} value={pause} placeholder="Boşsa ayardan gelir" onChange={(e) => setPause(e.target.value)} /></Field>
        <Field label="Not"><input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <p className="muted">Çıkış girişten küçükse gece vardiyası sayılır ve ertesi güne yazılır.</p>
    </Modal>
  );
}
