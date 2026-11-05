import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { api, download } from "../api/client";
import { saveRev } from "../api/conflict";
import { sumMoney } from "../api/num";
import { sys } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import {
  CurrencyRate, FirmSelect, ProjectSelect, addDays, fmtDay, fmtMoney, fmtRate, numOrNull, today, trIncludes, useRates,
} from "./erp/common";
import {
  BASIS_TEXT, INV_COLORS, LedgerModal, LinesEditor, LinesTable, PAY_COLORS, Stat, emptyLine, formTotals, linesBody,
  useBalances, type Balance, type BalanceBasis, type DocLine, type Invoice, type InvoiceKind, type Payment,
} from "./erp/commerce";
import { LOCALE, tx } from "../api/i18n";

const TABS = [
  { id: "sales", label: tx("Satış faturaları") },
  { id: "purchase", label: tx("Alış faturaları") },
  { id: "payments", label: tx("Tahsilat ve ödemeler") },
  { id: "balances", label: tx("Cari bakiyeler") },
  { id: "rates", label: tx("Kurlar") },
] as const;
type Tab = (typeof TABS)[number]["id"];

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["invoices", "invoice", "payments", "balances", "ledger", "overview", "sales-orders", "sales-order"])
      void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Finans: faturalar, tahsilat / ödeme ve cari bakiyeler. */
export default function Finance() {
  const [tab, setTab] = useState<Tab>("sales");
  const [basis, setBasis] = useState<BalanceBasis | undefined>(undefined);
  const bal = useBalances(true, basis);
  const shown: BalanceBasis = bal.data?.[0]?.basis ?? basis ?? "today";
  const sum = (k: "base_receivable" | "base_payable" | "base_overdue_receivable" | "base_overdue_payable") =>
    sumMoney((bal.data ?? []).map((b) => b[k]));
  const noRate = [...new Set((bal.data ?? []).filter((b) => b.base_balance == null).map((b) => b.currency))];
  return (
    <Page>
      <PageHeader icon={Wallet} title={tx("Fatura ve ödeme")} sub={tx("Satış ve alış faturaları, tahsilat, ödeme ve cari hesap takibi")} />
      <div className="grid stats">
        <Stat label={tx("Alacaklarımız")} value={fmtMoney(sum("base_receivable"))} sub={tx("Müşterilerin bize borcu, {0}", BASIS_TEXT[shown])} onClick={() => setTab("balances")} />
        <Stat label={tx("Vadesi geçen alacak")} value={fmtMoney(sum("base_overdue_receivable"))} tone={sum("base_overdue_receivable") > 0 ? "error" : undefined} onClick={() => setTab("sales")} />
        <Stat label={tx("Borçlarımız")} value={fmtMoney(sum("base_payable"))} sub={tx("Tedarikçilere borcumuz, {0}", BASIS_TEXT[shown])} onClick={() => setTab("balances")} />
        <Stat label={tx("Vadesi geçen borç")} value={fmtMoney(sum("base_overdue_payable"))} tone={sum("base_overdue_payable") > 0 ? "warn" : undefined} onClick={() => setTab("purchase")} />
      </div>
      {noRate.length > 0 && <p><span className="badge warn">{tx("Kuru girilmemiş {0} bakiyeleri bu toplamlarda yok", noRate.join(", "))}</span></p>}
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      {(tab === "sales" || tab === "purchase") && <Invoices key={tab} kind={tab} />}
      {tab === "payments" && <Payments />}
      {tab === "balances" && <Balances basis={shown} onBasis={setBasis} />}
      {tab === "rates" && <Rates />}
    </Page>
  );
}

function Invoices({ kind }: { kind: "sales" | "purchase" }) {
  const canEdit = useAuth().can("finance", "edit");
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["invoices", kind, state],
    queryFn: () => api.get<Invoice[]>(`/invoices?kind=${kind}${state ? `&pay_state=${state}` : ""}`),
  });
  const rows = useMemo(
    () => (list.data ?? []).filter((r) => !q.trim() || trIncludes(`${r.no} ${r.firm_name} ${r.project_name ?? ""} ${r.note}`, q)),
    [list.data, q],
  );
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>+ {kind === "sales" ? tx("Satış faturası") : tx("Alış faturası")}</button>}
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label={tx("Ödeme durumu")}>
          <option value="">{tx("Tümü")}</option>
          <option value="open">{tx("Ödenmemiş (açık)")}</option>
          <option value="overdue">{tx("Vadesi geçmiş")}</option>
          <option value="paid">{tx("Ödenmiş")}</option>
        </select>
        <input placeholder={tx("Ara (no, firma)…")} value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{tx("{0} fatura · kalan {1}", rows.length.toLocaleString(LOCALE), fmtMoney(sumMoney(rows.map((r) => r.base_remaining))))}</span>
        {rows.some((r) => r.base_remaining == null) && <span className="badge warn" title={tx("Kuru bilinmediği için toplama katılmadı")}>{tx("{0} belgede kur yok", rows.filter((r) => r.base_remaining == null).length)}</span>}
      </div>
      <Loading error={list.error} loading={list.isLoading} />
      {list.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>{tx("Fatura no")}</th><th>{kind === "sales" ? tx("Müşteri") : tx("Tedarikçi")}</th><th>{tx("Proje")}</th><th>{tx("Durum")}</th><th>{tx("Tarih")}</th><th>{tx("Vade")}</th>
              <th className="num">{tx("Toplam")}</th><th className="num">{tx("Ödenen")}</th><th className="num">{tx("Kalan")}</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => setOpenId(r.id)}>
                  <td><b>{r.no}</b>{r.is_credit && <span className="badge warn" style={{ marginLeft: 6 }}>{r.kind_label}</span>}</td><td>{r.firm_name}</td><td>{r.project_name ?? <span className="muted">—</span>}</td>
                  <td>
                    {r.pay_state
                      ? <span className="badge" style={statusStyle(PAY_COLORS[r.pay_state])}>{r.pay_label}</span>
                      : <span className="badge" style={statusStyle(INV_COLORS[r.status])}>{r.status_label}</span>}
                  </td>
                  <td>{fmtDay(r.invoice_date)}</td>
                  <td className={r.pay_state === "overdue" ? "error" : undefined}>{fmtDay(r.due_date)}</td>
                  <td className="num">{fmtMoney(r.total, r.currency)}</td>
                  <td className="num">{r.paid ? fmtMoney(r.paid, r.currency) : ""}</td>
                  <td className="num">{r.remaining ? <b>{fmtMoney(r.remaining, r.currency)}</b> : ""}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={9} className="muted empty">{tx("Fatura yok.")}{kind === "sales" ? tx(" Satış ekranında onaylı siparişten de fatura oluşturabilirsiniz.") : tx(" Satın alma siparişinden de alış faturası girebilirsiniz.")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {openId !== null && <InvoiceModal id={openId} onClose={() => setOpenId(null)} />}
      {creating && <InvoiceEditor kind={kind} onClose={() => setCreating(false)} onSaved={(i) => { setCreating(false); setOpenId(i.id); }} />}
    </div>
  );
}

function InvoiceModal({ id, onClose }: { id: number; onClose: () => void }) {
  const canEdit = useAuth().can("finance", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [editing, setEditing] = useState(false);
  const [paying, setPaying] = useState(false);
  const q = useQuery({ queryKey: ["invoice", id], queryFn: () => api.get<Invoice>(`/invoices/${id}`) });
  const inv = q.data;
  const status = useMutation({
    mutationFn: (s: string) => api.post<Invoice>(`/invoices/${id}/status`, { status: s }),
    onSuccess: (r) => { toast(`${r.no}: ${r.status_label}`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/invoices/${id}`),
    onSuccess: () => { toast(tx("Fatura silindi")); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const delPay = useMutation({
    mutationFn: (p: Payment) => api.del(`/payments/${p.id}`),
    onSuccess: () => { toast(tx("Ödeme silindi")); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  if (editing && inv) return <InvoiceEditor kind={inv.kind} invoice={inv} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  if (paying && inv) return <PaymentEditor invoice={inv} onClose={() => setPaying(false)} />;
  const busy = status.isPending || del.isPending;
  return (
    <Modal wide title={inv ? `${inv.kind_label} ${inv.no}` : tx("Fatura")} onClose={onClose}
      footer={inv && <>
        <button className="btn" onClick={() => void download(`/invoices/${id}/xlsx`, `${inv.no}.xlsx`).catch((e) => toast(errText(e), true))}>{tx("Excel")}</button>
        <span style={{ flex: 1 }} />
        {canEdit && inv.status === "draft" && <>
          <button className="btn danger" disabled={busy} onClick={() => confirm(tx("{0} silinsin mi?", inv.no)) && del.mutate()}>{tx("Sil")}</button>
          <button className="btn" onClick={() => setEditing(true)}>{tx("Düzenle")}</button>
          <button className="btn primary" disabled={busy || !inv.lines?.length} onClick={() => status.mutate("issued")}>{tx("Faturayı kes")}</button>
        </>}
        {canEdit && inv.status === "issued" && <>
          <button className="btn danger" disabled={busy} onClick={() => confirm(tx("{0} iptal edilsin mi?", inv.no)) && status.mutate("cancelled")}>{tx("İptal et")}</button>
          {inv.remaining > 0 && !inv.is_credit && <button className="btn primary" onClick={() => setPaying(true)}>{inv.kind === "sales" ? tx("Tahsilat gir") : tx("Ödeme gir")}</button>}
        </>}
      </>}>
      <Loading error={q.error} loading={q.isLoading} />
      {inv && (
        <>
          <div className="erp-head">
            <div><span className="muted">{tx("Durum")}</span>
              {inv.pay_state
                ? <span className="badge" style={statusStyle(PAY_COLORS[inv.pay_state])}>{inv.pay_label}</span>
                : <span className="badge" style={statusStyle(INV_COLORS[inv.status])}>{inv.status_label}</span>}
            </div>
            <div><span className="muted">{tx("Firma")}</span><b>{inv.firm_name}</b></div>
            <div><span className="muted">{tx("Proje")}</span>{inv.project_name ?? "—"}</div>
            <div><span className="muted">{tx("Fatura tarihi")}</span>{fmtDay(inv.invoice_date)}</div>
            <div><span className="muted">{tx("Vade")}</span><span className={inv.pay_state === "overdue" ? "error" : undefined}>{fmtDay(inv.due_date) || "—"}</span></div>
            {inv.is_credit
              ? <div><span className="muted">{tx("İlgili fatura")}</span><b>{inv.credit_of_no ?? "—"}</b></div>
              : <div><span className="muted">{tx("Ödenen / kalan")}</span>{fmtMoney(inv.paid, inv.currency)} / <b>{fmtMoney(inv.remaining, inv.currency)}</b></div>}
            {!!inv.credited && <div><span className="muted">{inv.kind === "sales" ? tx("Alacak dekontu") : tx("İade faturası")}</span>{fmtMoney(inv.credited, inv.currency)}</div>}
            {inv.base_total !== inv.total && (
              <div><span className="muted">{tx("Kur")}</span>{inv.rate == null ? <span className="badge warn">{tx("kur yok")}</span> : `${fmtRate(inv.rate)} · ${fmtMoney(inv.base_total)}`}</div>
            )}
          </div>
          {inv.note && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{inv.note}</p>}
          <LinesTable lines={inv.lines ?? []} currency={inv.currency} subtotal={inv.subtotal} discount={inv.discount} discountPct={inv.discount_pct}
            tax={inv.tax} taxRate={inv.tax_rate} total={inv.total} />
          {!!inv.credits?.length && (
            <p className="muted">{tx("Bağlı belgeler: {0}", inv.credits.map((c) => `${c.no} (${c.status_label}, ${fmtMoney(c.total, inv.currency)})`).join(" · "))}</p>
          )}
          {inv.is_credit && inv.status === "draft" && <p className="muted">{tx("Kesildiğinde cari bakiyeden düşer ve ilgili faturanın kalanını azaltır.")}</p>}
          {inv.status === "draft" && <p className="muted">{tx("Taslak fatura cari bakiyeye yansımaz. “Faturayı kes” ile kesinleştirin.")}</p>}
          {!!inv.payments?.length && (
            <>
              <h2>{inv.kind === "sales" ? tx("Tahsilatlar") : tx("Ödemeler")}</h2>
              <table className="simple erp-table">
                <thead><tr><th>{tx("Tarih")}</th><th>{tx("Yöntem")}</th><th>{tx("Not")}</th><th className="num">{tx("Tutar")}</th><th></th></tr></thead>
                <tbody>
                  {inv.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{fmtDay(p.pay_date)}</td><td>{tx(p.method)}</td><td className="muted">{p.note}</td>
                      <td className="num">{fmtMoney(p.amount, p.currency)}</td>
                      <td>{canEdit && <button className="btn small" disabled={delPay.isPending} onClick={() => confirm(tx("Ödeme kaydı silinsin mi?")) && delPay.mutate(p)}>{tx("Sil")}</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

function InvoiceEditor({ kind, invoice, onClose, onSaved }: {
  kind: InvoiceKind; invoice?: Invoice; onClose: () => void; onSaved: (i: Invoice) => void;
}) {
  const toast = useToast();
  const refresh = useRefresh();
  const [no, setNo] = useState(invoice?.no ?? "");
  const [firmId, setFirmId] = useState<number | null>(invoice?.firm_id ?? null);
  const [project, setProject] = useState<number | null>(invoice?.project_id ?? null);
  const [date, setDate] = useState(invoice?.invoice_date ?? today());
  const [due, setDue] = useState(invoice?.due_date ?? addDays(sys.payment_days));
  const [tax, setTax] = useState(String(invoice?.tax_rate ?? sys.vat));
  const [note, setNote] = useState(invoice?.note ?? "");
  const [currency, setCurrency] = useState(invoice?.currency ?? sys.currency);
  const [rate, setRate] = useState(invoice?.rate != null ? String(invoice.rate) : "");
  const [lines, setLines] = useState<DocLine[]>(() => invoice?.lines?.map((l) => ({ ...l })) ?? [emptyLine()]);
  const [prices, setPrices] = useState<string[]>(() => lines.map((l) => (l.unit_price == null ? "" : String(l.unit_price))));
  const { total } = formTotals(lines, prices, numOrNull(tax) ?? 0, invoice?.discount_pct ?? 0);
  const save = useMutation({
    mutationFn: () => {
      const body = { kind, no, firm_id: firmId, project_id: project, invoice_date: date || null, due_date: due || null,
        currency, rate: numOrNull(rate), tax_rate: numOrNull(tax) ?? 0, note, lines: linesBody(lines, prices).map((l) => ({ ...l, unit_price: l.unit_price ?? 0 })) };
      return invoice ? saveRev(invoice.rev, (rev) => api.put<Invoice>(`/invoices/${invoice.id}`, { ...body, rev })) : api.post<Invoice>("/invoices", body);
    },
    onSuccess: (i) => { toast(invoice ? tx("Fatura kaydedildi") : tx("{0} oluşturuldu (taslak)", i.no)); refresh(); onSaved(i); },
    onError: (e) => toast(errText(e), true),
  });
  const invalid = !firmId || (kind === "purchase" && !no.trim());
  return (
    <Modal wide title={invoice ? tx("Faturayı düzenle: {0}", invoice.no) : kind === "sales" ? tx("Yeni satış faturası") : tx("Yeni alış faturası")} onClose={onClose}
      footer={<>
        <span className="muted" style={{ marginRight: "auto" }}>{tx("Genel toplam (KDV dahil):")}{" "}<b>{fmtMoney(total, currency)}</b></span>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={invalid || save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form two">
        {kind === "purchase"
          ? <Field label={tx("Tedarikçinin fatura no")}><input value={no} onChange={(e) => setNo(e.target.value)} /></Field>
          : <Field label={tx("Fatura no")} hint={tx("Kaydedince otomatik verilir (FT-yıl-sıra).")}><input disabled value={invoice?.no ?? "otomatik"} /></Field>}
        <Field label={kind.startsWith("sales") ? tx("Müşteri") : tx("Tedarikçi")}>
          <FirmSelect kind={kind === "sales" ? "customer" : undefined} value={firmId} onChange={setFirmId} />
        </Field>
        <Field label={tx("Proje")}><ProjectSelect value={project} onChange={setProject} /></Field>
        <Field label={tx("KDV %")}><input style={{ width: 80 }} inputMode="decimal" value={tax} onChange={(e) => setTax(e.target.value)} /></Field>
        <Field label={tx("Fatura tarihi")}><input type="date" value={date ?? ""} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label={tx("Vade")}><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={date}
          currencyLocked={!!(invoice?.sales_order_id || invoice?.purchase_order_id)} />
        <Field label={tx("Not")}><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <LinesEditor lines={lines} setLines={setLines} prices={prices} setPrices={setPrices} currency={currency} />
    </Modal>
  );
}

function PaymentEditor({ invoice, onClose }: { invoice?: Invoice; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [direction, setDirection] = useState<"in" | "out">(invoice ? (invoice.kind === "sales" ? "in" : "out") : "in");
  const [firmId, setFirmId] = useState<number | null>(invoice?.firm_id ?? null);
  const [amount, setAmount] = useState(invoice ? String(invoice.remaining) : "");
  const [date, setDate] = useState(today());
  const [method, setMethod] = useState(sys.pay_methods[0]);
  const [note, setNote] = useState("");
  const [currency, setCurrency] = useState(invoice?.currency ?? sys.currency);
  const [rate, setRate] = useState(invoice?.rate != null ? String(invoice.rate) : "");
  const save = useMutation({
    mutationFn: () => api.post<Payment>("/payments", { direction, firm_id: firmId, invoice_id: invoice?.id ?? null,
      amount: numOrNull(amount), currency, rate: numOrNull(rate), pay_date: date || null, method, note }),
    onSuccess: (p) => { toast(`${p.direction_label} kaydedildi: ${fmtMoney(p.amount, p.currency)}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const amt = numOrNull(amount) ?? 0;
  return (
    <Modal title={invoice ? `${direction === "in" ? tx("Tahsilat") : tx("Ödeme")}: ${invoice.no}` : tx("Yeni tahsilat / ödeme")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={amt <= 0 || (!invoice && !firmId) || save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form">
        {!invoice && (
          <>
            <Field label={tx("Tür")}>
              <div className="seg">
                <button className={direction === "in" ? "on" : ""} onClick={() => setDirection("in")}>{tx("Tahsilat (para girişi)")}</button>
                <button className={direction === "out" ? "on" : ""} onClick={() => setDirection("out")}>{tx("Ödeme (para çıkışı)")}</button>
              </div>
            </Field>
            <Field label={tx("Firma")} hint={tx("Faturaya bağlı olmayan ödeme cari hesaba (avans / mahsup) işlenir.")}><FirmSelect value={firmId} onChange={setFirmId} /></Field>
          </>
        )}
        {invoice && <p className="muted">{tx("Kalan borç:")}{" "}<b>{fmtMoney(invoice.remaining, invoice.currency)}</b></p>}
        <Field label={tx("Tutar")}><input inputMode="decimal" autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label={tx("Tarih")}><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={date} currencyLocked={!!invoice} />
        <Field label={tx("Yöntem")}>
          <select value={method} onChange={(e) => setMethod(e.target.value)}>{sys.pay_methods.map((m) => <option key={m}>{tx(m)}</option>)}</select>
        </Field>
        <Field label={tx("Not (dekont no vb.)")}><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function Payments() {
  const canEdit = useAuth().can("finance", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [direction, setDirection] = useState("");
  const [creating, setCreating] = useState(false);
  const list = useQuery({ queryKey: ["payments", direction], queryFn: () => api.get<Payment[]>(`/payments${direction ? `?direction=${direction}` : ""}`) });
  const del = useMutation({
    mutationFn: (p: Payment) => api.del(`/payments/${p.id}`),
    onSuccess: () => { toast(tx("Silindi")); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const rows = list.data ?? [];
  const tot = (d: string) => rows.filter((r) => r.direction === d).reduce((s, r) => s + (r.base_amount ?? 0), 0);
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>{tx("+ Tahsilat / ödeme")}</button>}
        <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label={tx("Tür")}>
          <option value="">{tx("Tümü")}</option><option value="in">{tx("Tahsilatlar")}</option><option value="out">{tx("Ödemeler")}</option>
        </select>
        <span className="muted">{tx("Giriş {0} · Çıkış {1}", fmtMoney(tot("in")), fmtMoney(tot("out")))}</span>
        {rows.some((r) => r.base_amount == null) && <span className="badge warn" title={tx("Kuru bilinmediği için toplama katılmadı")}>{tx("{0} kayıtta kur yok", rows.filter((r) => r.base_amount == null).length)}</span>}
      </div>
      <Loading error={list.error} loading={list.isLoading} />
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>{tx("Tarih")}</th><th>{tx("Tür")}</th><th>{tx("Firma")}</th><th>{tx("Fatura")}</th><th>{tx("Yöntem")}</th><th>{tx("Not")}</th><th className="num">{tx("Tutar")}</th><th></th></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>{fmtDay(p.pay_date)}</td>
                <td><span className={p.direction === "in" ? "badge new" : "badge warn"}>{p.direction_label}</span></td>
                <td>{p.firm_name}</td><td className="mono">{p.invoice_no ?? <span className="muted">{tx("cari")}</span>}</td>
                <td>{tx(p.method)}</td><td className="muted">{p.note}</td>
                <td className="num"><b>{fmtMoney(p.amount, p.currency)}</b></td>
                <td>{canEdit && <button className="btn small" disabled={del.isPending} onClick={() => confirm(tx("Kayıt silinsin mi?")) && del.mutate(p)}>{tx("Sil")}</button>}</td>
              </tr>
            ))}
            {!rows.length && !list.isLoading && <tr><td colSpan={8} className="muted empty">{tx("Kayıt yok.")}</td></tr>}
          </tbody>
        </table>
      </div>
      {creating && <PaymentEditor onClose={() => setCreating(false)} />}
    </div>
  );
}

export function Balances({ basis, onBasis }: { basis: BalanceBasis; onBasis: (b: BalanceBasis) => void }) {
  const bal = useBalances(true, basis);
  const rates = useRates();
  const base = rates.data?.base ?? sys.currency;
  const [ledger, setLedger] = useState<{ id: number; name: string } | null>(null);
  const [q, setQ] = useState("");
  const rows = (bal.data ?? []).filter((b) => !q.trim() || trIncludes(b.firm_name, q));
  // One firm's currencies stay together, with a base total when there is more than one
  const firms = useMemo(() => {
    const by = new Map<string, Balance[]>();
    for (const b of rows) by.set(`${b.firm_id}|${b.firm_name}`, [...(by.get(`${b.firm_id}|${b.firm_name}`) ?? []), b]);
    return [...by.values()];
  }, [rows]);
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <input placeholder={tx("Firma ara…")} value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label={tx("Değerleme kuru")} value={basis} onChange={(e) => onBasis(e.target.value as BalanceBasis)}>
          <option value="today">{tx("Bugünkü kurla")}</option>
          <option value="doc">{tx("Belge tarihindeki kurla")}</option>
        </select>
        <span className="muted">{tx("Pozitif bakiye: firma bize borçlu. Negatif: biz firmaya borçluyuz. {0} karşılığı {1} hesaplanır. Kur farkı, belge kuruyla değer eksi bugünkü değerdir.", base, BASIS_TEXT[basis])}</span>
      </div>
      <Loading error={bal.error} loading={bal.isLoading} />
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>{tx("Firma")}</th><th className="num">{tx("Satış")}</th><th className="num">{tx("Tahsilat")}</th><th className="num">{tx("Alış")}</th><th className="num">{tx("Ödeme")}</th>
            <th className="num">{tx("Bakiye")}</th><th className="num">{tx("{0} karşılığı", base)}</th><th className="num">{tx("Kur farkı")}</th><th className="num">{tx("Vadesi geçen")}</th><th></th></tr></thead>
          <tbody>
            {firms.map((group) => (
              <Fragment key={`${group[0].firm_id}-${group[0].firm_name}`}>
                {group.map((b, i) => (
                  <tr key={b.currency}>
                    <td>{i === 0 ? <b>{b.firm_name}</b> : <span className="muted">{b.currency}</span>}</td>
                    <td className="num">{fmtMoney(b.sales, b.currency)}</td><td className="num">{fmtMoney(b.collected, b.currency)}</td>
                    <td className="num">{fmtMoney(b.purchases, b.currency)}</td><td className="num">{fmtMoney(b.paid, b.currency)}</td>
                    <td className={`num ${b.balance > 0 ? "ok" : b.balance < 0 ? "warn" : ""}`}><b>{fmtMoney(b.balance, b.currency)}</b></td>
                    <td className="num">{b.base_balance == null ? <span className="badge warn">{tx("kur yok")}</span> : fmtMoney(b.base_balance, base)}</td>
                    <td className="num muted">{b.fx_diff ? fmtMoney(b.fx_diff, base) : ""}</td>
                    <td className="num error">{b.overdue_receivable || b.overdue_payable ? fmtMoney(b.overdue_receivable || b.overdue_payable, b.currency) : ""}</td>
                    <td>{i === 0 && b.firm_id && <button className="btn small" onClick={() => setLedger({ id: b.firm_id!, name: b.firm_name })}>{tx("Ekstre")}</button>}</td>
                  </tr>
                ))}
                {group.length > 1 && (
                  <tr>
                    <td colSpan={6} className="num muted">{tx("{0} toplam", group[0].firm_name)}</td>
                    <td className="num"><b>{fmtMoney(sumMoney(group.map((b) => b.base_balance)), base)}</b></td>
                    <td colSpan={3}></td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!rows.length && !bal.isLoading && <tr><td colSpan={10} className="muted empty">{tx("Kesilmiş fatura veya ödeme yok.")}</td></tr>}
          </tbody>
        </table>
      </div>
      {ledger && <LedgerModal firmId={ledger.id} firmName={ledger.name} onClose={() => setLedger(null)} />}
    </div>
  );
}

function Rates() {
  const canEdit = useAuth().can("finance", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const list = useRates();
  const [currency, setCurrency] = useState("");
  const [rate, setRate] = useState("");
  const [day, setDay] = useState(today());
  const done = () => { for (const k of ["rates", "balances", "invoices", "payments", "ledger", "costs"]) void qc.invalidateQueries({ queryKey: [k] }); };
  const fetchNow = useMutation({
    mutationFn: () => api.post<{ rate_date: string; count: number }>("/rates/fetch"),
    onSuccess: (r) => { toast(tx("{0} kur alındı ({1})", r.count, fmtDay(r.rate_date))); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const add = useMutation({
    mutationFn: () => api.post("/rates", { currency: currency.trim().toUpperCase(), rate: numOrNull(rate), rate_date: day || null }),
    onSuccess: () => { toast(tx("Kur kaydedildi")); setRate(""); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const base = list.data?.base ?? sys.currency;
  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>{tx("Güncel kurlar")}</h3>
          {canEdit && <button className="btn primary" disabled={fetchNow.isPending} onClick={() => fetchNow.mutate()}>{tx("Merkez Bankası'ndan al")}</button>}
          <span className="muted">{tx("Sunucu günde bir kez kendisi de dener. İnternet yoksa kuru elle girin. 1 birim yabancı para = kaç {0}.", base)}</span>
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>{tx("Para birimi")}</th><th className="num">{tx("Kur ({0})", base)}</th><th>{tx("Tarih")}</th><th>{tx("Kaynak")}</th></tr></thead>
            <tbody>
              {(list.data?.latest ?? []).map((r) => (
                <tr key={r.id}><td><b>{r.currency}</b></td><td className="num">{fmtRate(r.rate)}</td><td>{fmtDay(r.rate_date)}</td><td>{r.source_label}</td></tr>
              ))}
              {list.data && !list.data.latest.length && <tr><td colSpan={4} className="muted empty">{tx("Henüz kur yok.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {canEdit && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>{tx("Elle kur gir")}</h3>
          <div className="adm-form two">
            <Field label={tx("Para birimi")}><input maxLength={3} placeholder="EUR" value={currency} onChange={(e) => setCurrency(e.target.value)} /></Field>
            <Field label={tx("Kur (1 birim = ? {0})", base)}><input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} /></Field>
            <Field label={tx("Tarih")}><input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} /></Field>
            <div style={{ alignSelf: "end" }}>
              <button className="btn primary" disabled={add.isPending || currency.trim().length !== 3 || !((numOrNull(rate) ?? 0) > 0)} onClick={() => add.mutate()}>{tx("Kaydet")}</button>
            </div>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>{tx("Elle girilen kur, aynı günün Merkez Bankası kurunun üstüne yazılmaz; geçerli kalır.")}</p>
        </div>
      )}
      <div className="card" style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>{tx("Geçmiş")}</h3>
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>{tx("Tarih")}</th><th>{tx("Para birimi")}</th><th className="num">{tx("Kur")}</th><th>{tx("Kaynak")}</th></tr></thead>
            <tbody>
              {(list.data?.rows ?? []).map((r) => (
                <tr key={r.id}><td>{fmtDay(r.rate_date)}</td><td>{r.currency}</td><td className="num">{fmtRate(r.rate)}</td><td>{r.source_label}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
