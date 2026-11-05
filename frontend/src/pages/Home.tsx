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
import { LOCALE, tx } from "../api/i18n";

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
  return h < 6 ? tx("İyi geceler") : h < 12 ? tx("Günaydın") : h < 18 ? tx("İyi günler") : tx("İyi akşamlar");
};
const ACTION: Record<string, string> = { create: tx("oluşturdu"), delete: "sildi", update: tx("güncelledi") };

const SHORTCUTS: { to: string; label: string; icon: LucideIcon; module: Module }[] = [
  { to: "/projects", label: tx("Projeler"), icon: FolderKanban, module: "projects" },
  { to: "/purchasing", label: tx("Satın alma"), icon: ShoppingCart, module: "purchasing" },
  { to: "/work-orders", label: tx("İş emirleri"), icon: Factory, module: "workorders" },
  { to: "/stock", label: tx("Stok"), icon: Boxes, module: "stock" },
  { to: "/sales", label: tx("Satış"), icon: TrendingUp, module: "sales" },
  { to: "/finance", label: tx("Fatura ve ödeme"), icon: Wallet, module: "finance" },
  { to: "/contacts", label: tx("Cari kartlar"), icon: Contact, module: "contacts" },
  { to: "/hr", label: tx("Personel ve zaman"), icon: Clock, module: "hr" },
];

/** Ana sayfa: what needs attention today, across every module the user may see. */
export default function Home() {
  const { can } = useAuth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview") });
  const o = q.data;
  const alerts: { text: string; to: string }[] = [];
  if (o?.purchasing?.overdue) alerts.push({ text: tx("{0} satın alma siparişinin termini geçti", o.purchasing.overdue), to: "/purchasing" });
  if (o?.workorders?.overdue) alerts.push({ text: tx("{0} iş emri gecikmede", o.workorders.overdue), to: "/work-orders" });
  if (o?.stock?.low) alerts.push({ text: tx("{0} stok kartı minimumun altında", o.stock.low), to: "/stock" });
  if (o?.finance?.overdue_receivable) alerts.push({ text: tx("Vadesi geçen alacak: {0}", fmtMoney(o.finance.overdue_receivable)), to: "/finance" });
  if (o?.finance?.overdue_payable) alerts.push({ text: tx("Vadesi geçen borç: {0}", fmtMoney(o.finance.overdue_payable)), to: "/finance" });
  if (o?.sales?.late) alerts.push({ text: tx("{0} satış siparişinin teslimi gecikti", o.sales.late), to: "/sales" });
  if (o?.projects?.pending_boms) alerts.push({ text: tx("{0} BOM sürümü onay bekliyor", o.projects.pending_boms), to: "/projects" });

  return (
    <Page>
      <PageHeader icon={House} title={`${greet()}${o ? `, ${o.user}` : ""}`}
        sub={new Date().toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" })} />
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
              <b className="row" style={{ gap: 6 }}><AlertTriangle size={16} className="warn" />{" "}{tx("Dikkat gerektirenler")}</b>
              <ul>{alerts.map((a) => <li key={a.text}><Link to={a.to}>{a.text}</Link></li>)}</ul>
            </div>
          )}
          <div className="grid stats">
            {o.projects && <Stat label={tx("Aktif proje")} value={o.projects.active} onClick={() => nav("/projects")} />}
            {o.purchasing && <Stat label={tx("Açık satın alma")} value={o.purchasing.open} sub={fmtMoney(o.purchasing.open_value)} tone={o.purchasing.overdue ? "warn" : undefined} onClick={() => nav("/purchasing")} />}
            {o.workorders && <Stat label={tx("Açık iş emri")} value={o.workorders.open} sub={tx("{0} üretimde", o.workorders.in_progress)} onClick={() => nav("/work-orders")} />}
            {o.stock && <Stat label={tx("Stok değeri")} value={fmtMoney(o.stock.value)} sub={tx("{0} kart · {1} kritik", o.stock.items, o.stock.low)} tone={o.stock.low ? "warn" : undefined} onClick={() => nav("/stock")} />}
            {o.sales && <Stat label={tx("Açık teklif")} value={o.sales.quotes} sub={fmtMoney(o.sales.quote_value)} onClick={() => nav("/sales")} />}
            {o.sales && <Stat label={tx("Onaylı sipariş")} value={o.sales.confirmed} sub={fmtMoney(o.sales.confirmed_value)} onClick={() => nav("/sales")} />}
            {o.finance && <Stat label={tx("Alacak")} value={fmtMoney(o.finance.receivable)} sub={o.finance.overdue_receivable ? tx("{0} vadesi geçti", fmtMoney(o.finance.overdue_receivable)) : tx("Vadesi geçen yok")} tone={o.finance.overdue_receivable ? "error" : "ok"} onClick={() => nav("/finance")} />}
            {o.finance && <Stat label={tx("Borç")} value={fmtMoney(o.finance.payable)} sub={o.finance.overdue_payable ? tx("{0} vadesi geçti", fmtMoney(o.finance.overdue_payable)) : tx("Vadesi geçen yok")} tone={o.finance.overdue_payable ? "warn" : undefined} onClick={() => nav("/finance")} />}
            {o.hr && <Stat label={tx("Bu ay çalışılan")} value={tx("{0} sa", o.hr.month_hours.toLocaleString(LOCALE))} onClick={() => nav("/hr")} />}
          </div>
          <div className="home-grid">
            <div className="card">
              <b>{tx("Son 30 gün işlem sayısı")}</b>
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
                    <Tooltip labelFormatter={(d) => fmtDay(String(d))} formatter={(v) => [v, tx("İşlem")]}
                      contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Area type="monotone" dataKey="count" stroke="var(--accent)" strokeWidth={2} fill="url(#act)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <b>{tx("Son işlemler")}</b>
              <ul className="feed">
                {o.recent.map((r, i) => (
                  <li key={i}>
                    <span className="avatar sm">{r.user.slice(0, 1).toLocaleUpperCase(LOCALE)}</span>
                    <div>
                      <div><b>{r.user}</b> {tx(r.entity).toLocaleLowerCase(LOCALE)} <span className="mono">{r.entity_id}</span> {ACTION[r.action] ?? r.action}
                        {r.action === "update" && r.field && <span className="muted"> ({r.field}{r.new ? `: ${r.new.slice(0, 40)}` : ""})</span>}</div>
                      <small className="muted">{new Date(r.ts).toLocaleString(LOCALE)}{r.project ? ` · ${r.project}` : ""}</small>
                    </div>
                  </li>
                ))}
                {!o.recent.length && <li className="muted">{tx("Henüz işlem yok.")}</li>}
              </ul>
            </div>
            {o.purchasing && !!o.purchasing.late.length && (
              <div className="card">
                <b>{tx("Termini geçen satın almalar")}</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.purchasing.late.map((p) => (
                    <tr key={p.id}><td><b>{p.no}</b></td><td>{p.firm_name}</td><td className="error">{fmtDay(p.due_date)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            {o.stock && !!o.stock.low_items.length && (
              <div className="card">
                <b>{tx("Kritik stok")}</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.stock.low_items.map((s) => (
                    <tr key={s.id}><td className="mono">{s.code}</td><td>{s.name}</td><td className="num warn">{fmtQty(s.qty)} / {fmtQty(s.min_qty)} {tx(s.unit)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            {o.finance && !!o.finance.due_soon.length && (
              <div className="card">
                <b>{tx("Vadesi gelen faturalar (7 gün)")}</b>
                <table className="simple" style={{ marginTop: 6 }}>
                  <tbody>{o.finance.due_soon.map((f) => (
                    <tr key={f.id}>
                      <td><span className={f.kind === "sales" ? "badge new" : "badge warn"}>{f.kind === "sales" ? tx("Alacak") : tx("Borç")}</span></td>
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
