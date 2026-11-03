import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, Boxes, Clock, Contact, Factory, FolderKanban, House, ShoppingCart, TrendingUp, Wallet, type LucideIcon,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAuth, type Module } from "../api/auth";
import { Page, PageHeader } from "../components/Layout";
import { Loading } from "./admin/shared";
import { fmtDay, fmtMoney, fmtQty, type PurchaseOrder, type StockItem } from "./erp/common";
import { Stat, type Invoice } from "./erp/commerce";

type Overview = {
  user: string; today: string;
  projects?: { active: number; pending_boms: number };
  purchasing?: { open: number; overdue: number; open_value: number; late: PurchaseOrder[] };
  workorders?: { open: number; in_progress: number; overdue: number };
  stock?: { items: number; low: number; value: number; low_items: StockItem[] };
  sales?: { quotes: number; quote_value: number; confirmed: number; confirmed_value: number; late: number };
  finance?: { receivable: number; payable: number; overdue_receivable: number; overdue_payable: number; due_soon: Invoice[] };
  hr?: { month_hours: number };
  activity: { date: string; count: number }[];
  recent: { ts: string; user: string; entity: string; entity_id: string; field: string; action: string; new: string | null; project: string | null }[];
};

const greet = () => {
  const h = new Date().getHours();
  return h < 6 ? "İyi geceler" : h < 12 ? "Günaydın" : h < 18 ? "İyi günler" : "İyi akşamlar";
};
const ACTION: Record<string, string> = { create: "oluşturdu", delete: "sildi", update: "güncelledi" };

const SHORTCUTS: { to: string; label: string; icon: LucideIcon; module: Module }[] = [
  { to: "/projects", label: "Projeler", icon: FolderKanban, module: "projects" },
  { to: "/purchasing", label: "Satın alma", icon: ShoppingCart, module: "purchasing" },
  { to: "/work-orders", label: "İş emirleri", icon: Factory, module: "workorders" },
  { to: "/stock", label: "Stok", icon: Boxes, module: "stock" },
  { to: "/sales", label: "Satış", icon: TrendingUp, module: "sales" },
  { to: "/finance", label: "Fatura ve ödeme", icon: Wallet, module: "finance" },
  { to: "/contacts", label: "Cari kartlar", icon: Contact, module: "contacts" },
  { to: "/hr", label: "Personel ve zaman", icon: Clock, module: "hr" },
];

/** Ana sayfa: what needs attention today, across every module the user may see. */
export default function Home() {
  const { can } = useAuth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview") });
  const o = q.data;
  const alerts: { text: string; to: string }[] = [];
  if (o?.purchasing?.overdue) alerts.push({ text: `${o.purchasing.overdue} satın alma siparişinin termini geçti`, to: "/purchasing" });
  if (o?.workorders?.overdue) alerts.push({ text: `${o.workorders.overdue} iş emri gecikmede`, to: "/work-orders" });
  if (o?.stock?.low) alerts.push({ text: `${o.stock.low} stok kartı minimumun altında`, to: "/stock" });
  if (o?.finance?.overdue_receivable) alerts.push({ text: `Vadesi geçen alacak: ${fmtMoney(o.finance.overdue_receivable)}`, to: "/finance" });
  if (o?.finance?.overdue_payable) alerts.push({ text: `Vadesi geçen borç: ${fmtMoney(o.finance.overdue_payable)}`, to: "/finance" });
  if (o?.sales?.late) alerts.push({ text: `${o.sales.late} satış siparişinin teslimi gecikti`, to: "/sales" });
  if (o?.projects?.pending_boms) alerts.push({ text: `${o.projects.pending_boms} BOM sürümü onay bekliyor`, to: "/projects" });

  return (
    <Page>
      <PageHeader icon={House} title={`${greet()}${o ? `, ${o.user}` : ""}`}
        sub={new Date().toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long", year: "numeric" })} />
      <Loading error={q.error} loading={q.isLoading} />
      {o && (
        <>
          <div className="shortcuts">
            {SHORTCUTS.filter((s) => can(s.module)).map((s) => (
              <Link key={s.to} to={s.to} className="shortcut"><s.icon size={20} /><span>{s.label}</span></Link>
            ))}
          </div>
          {!!alerts.length && (
            <div className="card alerts">
              <b className="row" style={{ gap: 6 }}><AlertTriangle size={16} className="warn" /> Dikkat gerektirenler</b>
              <ul>{alerts.map((a) => <li key={a.text}><Link to={a.to}>{a.text}</Link></li>)}</ul>
            </div>
          )}
          <div className="grid stats">
            {o.projects && <Stat label="Aktif proje" value={o.projects.active} onClick={() => nav("/projects")} />}
            {o.purchasing && <Stat label="Açık satın alma" value={o.purchasing.open} sub={fmtMoney(o.purchasing.open_value)} tone={o.purchasing.overdue ? "warn" : undefined} onClick={() => nav("/purchasing")} />}
            {o.workorders && <Stat label="Açık iş emri" value={o.workorders.open} sub={`${o.workorders.in_progress} üretimde`} onClick={() => nav("/work-orders")} />}
            {o.stock && <Stat label="Stok değeri" value={fmtMoney(o.stock.value)} sub={`${o.stock.items} kart · ${o.stock.low} kritik`} tone={o.stock.low ? "warn" : undefined} onClick={() => nav("/stock")} />}
            {o.sales && <Stat label="Açık teklif" value={o.sales.quotes} sub={fmtMoney(o.sales.quote_value)} onClick={() => nav("/sales")} />}
            {o.sales && <Stat label="Onaylı sipariş" value={o.sales.confirmed} sub={fmtMoney(o.sales.confirmed_value)} onClick={() => nav("/sales")} />}
            {o.finance && <Stat label="Alacak" value={fmtMoney(o.finance.receivable)} sub={o.finance.overdue_receivable ? `${fmtMoney(o.finance.overdue_receivable)} vadesi geçti` : "Vadesi geçen yok"} tone={o.finance.overdue_receivable ? "error" : "ok"} onClick={() => nav("/finance")} />}
            {o.finance && <Stat label="Borç" value={fmtMoney(o.finance.payable)} sub={o.finance.overdue_payable ? `${fmtMoney(o.finance.overdue_payable)} vadesi geçti` : "Vadesi geçen yok"} tone={o.finance.overdue_payable ? "warn" : undefined} onClick={() => nav("/finance")} />}
            {o.hr && <Stat label="Bu ay çalışılan" value={`${o.hr.month_hours.toLocaleString("tr-TR")} sa`} onClick={() => nav("/hr")} />}
          </div>
          <div className="home-grid">
            <div className="card">
              <b>Son 30 gün işlem sayısı</b>
              <div style={{ height: 170, marginTop: 8 }}>
                <ResponsiveContainer>
                  <AreaChart data={o.activity} margin={{ top: 4, right: 8, bottom: 0, left: -24 }}>
                    <defs>
                      <linearGradient id="act" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(8, 10)} tick={{ fill: "var(--muted)", fontSize: 11 }} interval={4} />
                    <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 11 }} />
                    <Tooltip labelFormatter={(d) => fmtDay(String(d))} formatter={(v) => [v, "İşlem"]}
                      contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Area type="monotone" dataKey="count" stroke="var(--accent)" strokeWidth={2} fill="url(#act)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <b>Son işlemler</b>
              <ul className="feed">
                {o.recent.map((r, i) => (
                  <li key={i}>
                    <span className="avatar sm">{r.user.slice(0, 1).toLocaleUpperCase("tr-TR")}</span>
                    <div>
                      <div><b>{r.user}</b> {r.entity.toLocaleLowerCase("tr-TR")} <span className="mono">{r.entity_id}</span> {ACTION[r.action] ?? r.action}
                        {r.action === "update" && r.field && <span className="muted"> ({r.field}{r.new ? `: ${r.new.slice(0, 40)}` : ""})</span>}</div>
                      <small className="muted">{new Date(r.ts).toLocaleString("tr-TR")}{r.project ? ` · ${r.project}` : ""}</small>
                    </div>
                  </li>
                ))}
                {!o.recent.length && <li className="muted">Henüz işlem yok.</li>}
              </ul>
            </div>
            {o.purchasing && !!o.purchasing.late.length && (
              <div className="card">
                <b>Termini geçen satın almalar</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.purchasing.late.map((p) => (
                    <tr key={p.id}><td><b>{p.no}</b></td><td>{p.firm_name}</td><td className="error">{fmtDay(p.due_date)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            {o.stock && !!o.stock.low_items.length && (
              <div className="card">
                <b>Kritik stok</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.stock.low_items.map((s) => (
                    <tr key={s.id}><td className="mono">{s.code}</td><td>{s.name}</td><td className="num warn">{fmtQty(s.qty)} / {fmtQty(s.min_qty)} {s.unit}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            {o.finance && !!o.finance.due_soon.length && (
              <div className="card">
                <b>Vadesi gelen faturalar (7 gün)</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.finance.due_soon.map((f) => (
                    <tr key={f.id}>
                      <td><span className={f.kind === "sales" ? "badge new" : "badge warn"}>{f.kind === "sales" ? "Alacak" : "Borç"}</span></td>
                      <td><b>{f.no}</b> · {f.firm_name}</td>
                      <td className={f.pay_state === "overdue" ? "error" : undefined}>{fmtDay(f.due_date)}</td>
                      <td className="num">{fmtMoney(f.remaining, f.currency)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </Page>
  );
}
