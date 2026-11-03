import { useQuery } from "@tanstack/react-query";
import { IdCard } from "lucide-react";
import { api } from "../api/client";
import { Page, PageHeader } from "../components/Layout";
import { Loading } from "./admin/shared";
import { fmtDay, fmtMoney } from "./erp/common";
import { Stat, type Employee, type TimeEntry } from "./erp/commerce";

type MyResp = { employee: Employee | null; rows: TimeEntry[]; total_hours: number; month_hours?: number; total_cost: number };
const fmtH = (h: number) => `${h.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} sa`;

/** Çalışanın kendi personel kartı: yalnızca kendi bilgileri ve saatleri, diğer personel görünmez. */
export default function MyCard() {
  const q = useQuery({ queryKey: ["hr-me"], queryFn: () => api.get<MyResp>("/hr/me") });
  const d = q.data;
  const e = d?.employee;
  return (
    <Page>
      <PageHeader icon={IdCard} title="Personel kartım" sub="Yalnızca size ait bilgiler ve son 90 günün çalışma saatleri" />
      <Loading error={q.error} loading={q.isLoading} />
      {d && !e && (
        <div className="card empty">
          Hesabınıza bağlı bir personel kartı yok. Personel kartınızın hesabınıza bağlanması için yöneticinize başvurun.
        </div>
      )}
      {d && e && (
        <>
          <div className="grid stats">
            <Stat label="Bu ay" value={fmtH(d.month_hours ?? 0)} />
            <Stat label="Son 30 gün" value={fmtH(e.hours_30d)} />
            <Stat label="Saat ücreti" value={e.hourly_cost == null ? "—" : fmtMoney(e.hourly_cost)} />
          </div>
          <div className="card">
            <div className="adm-form two">
              <div><span className="muted">Ad Soyad</span><div><b>{e.name}</b></div></div>
              <div><span className="muted">Görev / bölüm</span><div>{[e.title, e.department].filter(Boolean).join(" · ") || "—"}</div></div>
              <div><span className="muted">İletişim</span><div>{[e.phone, e.email].filter(Boolean).join(" · ") || "—"}</div></div>
              <div><span className="muted">İşe giriş</span><div>{e.start_date ? fmtDay(e.start_date) : "—"}</div></div>
            </div>
          </div>
          <div className="card">
            <b>Çalışma saatlerim</b>
            <div className="adm-scroll" style={{ marginTop: 8 }}>
              <table className="simple erp-table">
                <thead><tr><th>Tarih</th><th>Proje</th><th>İş emri</th><th className="num">Saat</th><th>Not</th></tr></thead>
                <tbody>
                  {d.rows.map((t) => (
                    <tr key={t.id}>
                      <td>{fmtDay(t.work_date)}</td>
                      <td>{t.project_name ?? <span className="muted">Proje dışı</span>}</td>
                      <td className="mono">{t.work_order_no ?? ""}</td>
                      <td className="num">{fmtH(t.hours)}</td>
                      <td className="muted">{t.note}</td>
                    </tr>
                  ))}
                  {!d.rows.length && <tr><td colSpan={5} className="muted empty">Son 90 günde kayıt yok.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
