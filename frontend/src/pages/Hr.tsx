import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { saveRev } from "../api/conflict";
import { curSign, sys } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal } from "./admin/shared";
import { ProjectSelect, addDays, fmtDay, fmtMoney, numOrNull, today, trIncludes, type WorkOrder } from "./erp/common";
import { Stat, type Employee, type TimeEntry } from "./erp/commerce";
import { LOCALE, tx } from "../api/i18n";

type HrUser = { id: number; username: string; full_name: string; email: string };
type TimeResp = { rows: TimeEntry[]; total_hours: number; total_cost: number; by_project: { name: string; hours: number; cost: number }[] };
const fmtH = (h: number) => tx("{0} sa", h.toLocaleString(LOCALE, { maximumFractionDigits: 2 }));

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["employees", "time-entries", "costs", "overview"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Personel kartları ve çalışma saatleri. Saatler projenin işçilik maliyetine yansır. */
export default function Hr() {
  const [tab, setTab] = useState<"time" | "people">("time");
  return (
    <Page>
      <PageHeader icon={Clock} title={tx("Personel ve zaman")} sub={tx("Çalışma saatleri projelere işçilik maliyeti olarak yansır")} />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "time"} className={tab === "time" ? "active" : ""} onClick={() => setTab("time")}>{tx("Zaman kayıtları")}</button>
        <button role="tab" aria-selected={tab === "people"} className={tab === "people" ? "active" : ""} onClick={() => setTab("people")}>{tx("Personel")}</button>
      </div>
      {tab === "time" ? <TimeTab /> : <PeopleTab />}
    </Page>
  );
}

function useEmployees() {
  return useQuery({ queryKey: ["employees"], queryFn: () => api.get<Employee[]>("/employees") });
}

function TimeTab() {
  const canEdit = useAuth().can("hr", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const emps = useEmployees();
  const [from, setFrom] = useState(addDays(-30));
  const [to, setTo] = useState(today());
  const [emp, setEmp] = useState<number | "">("");
  const [project, setProject] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [fixing, setFixing] = useState<TimeEntry | null>(null);
  const list = useQuery({
    queryKey: ["time-entries", from, to, emp, project],
    queryFn: () => {
      const p = new URLSearchParams();
      if (from) p.set("date_from", from);
      if (to) p.set("date_to", to);
      if (emp) p.set("employee_id", String(emp));
      if (project) p.set("project_id", String(project));
      return api.get<TimeResp>(`/time-entries?${p}`);
    },
  });
  const del = useMutation({
    mutationFn: (t: TimeEntry) => api.del(`/time-entries/${t.id}`),
    onSuccess: () => { toast(tx("Kayıt silindi")); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const d = list.data;
  return (
    <>
      <div className="grid stats">
        <Stat label={tx("Toplam saat")} value={d ? fmtH(d.total_hours) : "…"} />
        <Stat label={tx("İşçilik maliyeti")} value={d ? fmtMoney(d.total_cost) : "…"} />
        <Stat label={tx("En çok saat")} value={d?.by_project[0]?.name ?? "—"} sub={d?.by_project[0] ? fmtH(d.by_project[0].hours) : undefined} />
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          {canEdit && <button className="btn primary" disabled={!emps.data?.length} title={!emps.data?.length ? tx("Önce personel ekleyin") : undefined}
            onClick={() => setAdding(true)}>{tx("+ Saat gir")}</button>}
          <label className="row" style={{ gap: 4 }}>{tx("Tarih")}{" "}<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /> – <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <select value={emp} onChange={(e) => setEmp(e.target.value ? Number(e.target.value) : "")} aria-label={tx("Personel")}>
            <option value="">{tx("Tüm personel")}</option>
            {(emps.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <ProjectSelect value={project} onChange={setProject} emptyLabel={tx("Tüm projeler")} />
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {d && (
          <div className="hr-grid">
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>{tx("Tarih")}</th><th>{tx("Personel")}</th><th>{tx("Proje")}</th><th>{tx("İş emri")}</th><th className="num">{tx("Saat")}</th><th className="num">{tx("Maliyet")}</th><th>{tx("Not")}</th><th></th></tr></thead>
                <tbody>
                  {d.rows.map((t) => (
                    <tr key={t.id}>
                      <td>{fmtDay(t.work_date)}</td><td><b>{t.employee_name}</b></td>
                      <td>{t.project_name ?? <span className="muted">{tx("Proje dışı")}</span>}</td>
                      <td className="mono">{t.work_order_no ?? ""}</td>
                      <td className="num">{fmtH(t.hours)}</td>
                      <td className="num">{t.cost == null ? <span className="badge warn" title={tx("Personelin saat ücreti girilmemiş")}>{tx("ücret yok")}</span> : fmtMoney(t.cost)}</td>
                      <td className="muted">{t.note}</td>
                      <td>{canEdit && <div className="row">
                        <button className="btn small" onClick={() => setFixing(t)}>{tx("Düzelt")}</button>
                        <button className="btn small" disabled={del.isPending} onClick={() => confirm(tx("Kayıt silinsin mi?")) && del.mutate(t)}>{tx("Sil")}</button>
                      </div>}</td>
                    </tr>
                  ))}
                  {!d.rows.length && <tr><td colSpan={8} className="muted empty">{tx("Bu aralıkta kayıt yok.")}</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="card flat">
              <b>{tx("Projeye göre")}</b>
              <table className="simple" style={{ marginTop: 6 }}>
                <tbody>
                  {d.by_project.map((p) => (
                    <tr key={p.name}><td>{p.name}</td><td className="num">{fmtH(p.hours)}</td><td className="num">{fmtMoney(p.cost)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      {adding && <TimeForm employees={(emps.data ?? []).filter((e) => e.active)} onClose={() => setAdding(false)} />}
      {fixing && <TimeForm entry={fixing} employees={[]} onClose={() => setFixing(null)} />}
    </>
  );
}

function TimeForm({ employees, entry, onClose }: { employees: Employee[]; entry?: TimeEntry; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [emp, setEmp] = useState<number>(entry?.employee_id ?? employees[0]?.id ?? 0);
  const [date, setDate] = useState(entry?.work_date ?? today());
  const [hours, setHours] = useState(String(entry?.hours ?? sys.work_hours));
  const [project, setProject] = useState<number | null>(entry?.project_id ?? null);
  const [wo, setWo] = useState<number | null>(entry?.work_order_id ?? null);
  const [note, setNote] = useState(entry?.note ?? "");
  const wos = useQuery({
    enabled: useAuth().can("workorders"),
    queryKey: ["work-orders", project ?? 0, "open"],
    queryFn: () => api.get<{ rows: WorkOrder[] }>(`/work-orders?status=open${project ? `&project_id=${project}` : ""}`),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { work_date: date, hours: numOrNull(hours), project_id: project, work_order_id: wo, note };
      return entry ? saveRev(entry.rev, (rev) => api.put<TimeEntry>(`/time-entries/${entry.id}`, { ...body, rev })) : api.post<TimeEntry>("/time-entries", { ...body, employee_id: emp });
    },
    onSuccess: (t) => {
      toast(tx("{0}: {1} kaydedildi", t.employee_name, fmtH(t.hours)));
      refresh();
      if (entry) onClose();
      else { setNote(""); setWo(null); }
    },
    onError: (e) => toast(errText(e), true),
  });
  const h = numOrNull(hours) ?? 0;
  return (
    <Modal title={entry ? tx("Düzelt: {0}", entry.employee_name) : tx("Çalışma saati gir")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Kapat")}</button>
        <button className="btn primary" disabled={!emp || h <= 0 || h > 24 || save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form">
        {!entry && (
          <Field label={tx("Personel")}>
            <select value={emp} onChange={(e) => setEmp(Number(e.target.value))}>
              {employees.map((e) => <option key={e.id} value={e.id}>{e.name}{e.title ? ` · ${e.title}` : ""}</option>)}
            </select>
          </Field>
        )}
        <div className="adm-form two">
          <Field label={tx("Tarih")}><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label={tx("Saat")}><input inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} /></Field>
        </div>
        <Field label={tx("Proje")}><ProjectSelect value={project} onChange={(p) => { setProject(p); setWo(null); }} emptyLabel={tx("(Proje dışı / genel)")} /></Field>
        <Field label={tx("İş emri (isteğe bağlı)")}>
          <select value={wo ?? ""} onChange={(e) => setWo(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{tx("(Yok)")}</option>
            {entry?.work_order_id && !wos.data?.rows.some((w) => w.id === entry.work_order_id) && <option value={entry.work_order_id}>{entry.work_order_no}</option>}
            {(wos.data?.rows ?? []).map((w) => <option key={w.id} value={w.id}>{w.no} · {w.part_no}</option>)}
          </select>
        </Field>
        <Field label={tx("Not")}><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {!entry && <p className="muted">{tx("Kaydettikten sonra pencere açık kalır; aynı gün için başka personel girebilirsiniz.")}</p>}
      </div>
    </Modal>
  );
}

function PeopleTab() {
  const canEdit = useAuth().can("hr", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const emps = useEmployees();
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const toggle = useMutation({
    mutationFn: (e: Employee) => api.put(`/employees/${e.id}`, { active: !e.active }),
    onSuccess: refresh,
    onError: (e) => toast(errText(e), true),
  });
  const rows = (emps.data ?? []).filter((e) => !q.trim() || trIncludes(`${e.name} ${e.title} ${e.department}`, q));
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        {canEdit && <button className="btn primary" onClick={() => setEditing("new")}>{tx("+ Yeni personel")}</button>}
        <input placeholder={tx("Ara (ad, görev, bölüm)…")} value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{tx("{0} kişi", rows.length)}</span>
      </div>
      <Loading error={emps.error} loading={emps.isLoading} />
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>{tx("Ad Soyad")}</th><th>{tx("Görev")}</th><th>{tx("Bölüm")}</th><th>{tx("İletişim")}</th><th className="num">{tx("Saat ücreti")}</th><th className="num">{tx("Son 30 gün")}</th><th>{tx("Durum")}</th><th></th></tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} style={e.active ? undefined : { opacity: 0.6 }}>
                <td><b>{e.name}</b>{e.user_id != null && <span className="badge" style={{ marginLeft: 6 }} title={tx("Kullanıcı hesabına bağlı; kendi kartını görür")}>{tx("hesap")}</span>}</td><td>{e.title}</td><td>{e.department}</td>
                <td className="muted">{[e.phone, e.email].filter(Boolean).join(" · ")}</td>
                <td className="num">{e.hourly_cost == null ? <span className="muted">—</span> : fmtMoney(e.hourly_cost)}</td>
                <td className="num">{fmtH(e.hours_30d)}</td>
                <td>{canEdit
                  ? <label className="row" style={{ gap: 4 }}><input type="checkbox" checked={e.active} onChange={() => toggle.mutate(e)} />{e.active ? tx("Aktif") : tx("Pasif")}</label>
                  : e.active ? tx("Aktif") : tx("Pasif")}</td>
                <td>{canEdit && <button className="btn small" onClick={() => setEditing(e)}>{tx("Düzenle")}</button>}</td>
              </tr>
            ))}
            {!rows.length && !emps.isLoading && <tr><td colSpan={8} className="muted empty">{tx("Personel yok.")}</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="muted">{tx("Saat ücreti, kayıt girildiği andaki değerle saklanır; sonradan değiştirmek eski maliyetleri bozmaz. Bu ekranı yalnızca \"Personel ve zaman\" yetkisi olanlar görür; çalışanlar yalnızca kendi kartlarını \"Personel kartım\" ekranında görür.")}</p>
      {editing && <EmployeeForm emp={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function EmployeeForm({ emp, onClose }: { emp?: Employee; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [f, setF] = useState({
    name: emp?.name ?? "", title: emp?.title ?? "", department: emp?.department ?? "", phone: emp?.phone ?? "",
    email: emp?.email ?? "", rate: emp?.hourly_cost == null ? "" : String(emp.hourly_cost), start: emp?.start_date ?? "", note: emp?.note ?? "",
    user: emp?.user_id == null ? "" : String(emp.user_id), leave: emp?.annual_leave_days == null ? "" : String(emp.annual_leave_days),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const users = useQuery({ queryKey: ["hr-users"], queryFn: () => api.get<HrUser[]>("/hr/users") });
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), title: f.title, department: f.department, phone: f.phone, email: f.email,
        hourly_cost: numOrNull(f.rate), start_date: f.start || null, note: f.note, user_id: f.user ? Number(f.user) : null,
        annual_leave_days: numOrNull(f.leave) };
      return emp ? saveRev(emp.rev, (rev) => api.put<Employee>(`/employees/${emp.id}`, { ...body, rev })) : api.post<Employee>("/employees", body);
    },
    onSuccess: () => { toast(tx("Personel kaydedildi")); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={emp ? tx("Düzenle: {0}", emp.name) : tx("Yeni personel")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form">
        <Field label={tx("Ad Soyad")}><input autoFocus value={f.name} onChange={set("name")} /></Field>
        <div className="adm-form two">
          <Field label={tx("Görev")}><input value={f.title} onChange={set("title")} /></Field>
          <Field label={tx("Bölüm")}><input value={f.department} onChange={set("department")} /></Field>
          <Field label={tx("Telefon")}><input value={f.phone} onChange={set("phone")} /></Field>
          <Field label={tx("E-posta")}><input type="email" value={f.email} onChange={set("email")} /></Field>
          <Field label={tx("Saat ücreti ({0}, işveren maliyeti)", curSign())}><input inputMode="decimal" value={f.rate} onChange={set("rate")} /></Field>
          <Field label={tx("İşe giriş")}><input type="date" value={f.start} onChange={set("start")} /></Field>
          <Field label={tx("Yıllık izin hakkı (gün)")} hint={tx("Boşsa Sistem Ayarları'ndaki değer geçerli")}><input inputMode="decimal" value={f.leave} onChange={set("leave")} /></Field>
        </div>
        <Field label={tx("Kullanıcı hesabı (kendi kartını ve saatlerini görür)")}>
          <select value={f.user} onChange={set("user")}>
            <option value="">{tx("(Bağlı değil)")}</option>
            {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.full_name ? `${u.full_name} (${u.username})` : u.username}</option>)}
          </select>
        </Field>
        <Field label={tx("Not")}><textarea rows={2} value={f.note} onChange={set("note")} /></Field>
      </div>
    </Modal>
  );
}
