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

const TABS = [
  { id: "sales", label: "Satış faturaları" },
  { id: "purchase", label: "Alış faturaları" },
  { id: "payments", label: "Tahsilat ve ödemeler" },
  { id: "balances", label: "Cari bakiyeler" },
  { id: "rates", label: "Kurlar" },
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
      <PageHeader icon={Wallet} title="Fatura ve ödeme" sub="Satış ve alış faturaları, tahsilat, ödeme ve cari hesap takibi" />
      <div className="grid stats">
        <Stat label="Alacaklarımız" value={fmtMoney(sum("base_receivable"))} sub={`Müşterilerin bize borcu, ${BASIS_TEXT[shown]}`} onClick={() => setTab("balances")} />
        <Stat label="Vadesi geçen alacak" value={fmtMoney(sum("base_overdue_receivable"))} tone={sum("base_overdue_receivable") > 0 ? "error" : undefined} onClick={() => setTab("sales")} />
        <Stat label="Borçlarımız" value={fmtMoney(sum("base_payable"))} sub={`Tedarikçilere borcumuz, ${BASIS_TEXT[shown]}`} onClick={() => setTab("balances")} />
        <Stat label="Vadesi geçen borç" value={fmtMoney(sum("base_overdue_payable"))} tone={sum("base_overdue_payable") > 0 ? "warn" : undefined} onClick={() => setTab("purchase")} />
      </div>
      {noRate.length > 0 && <p><span className="badge warn">Kuru girilmemiş {noRate.join(", ")} bakiyeleri bu toplamlarda yok</span></p>}
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
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>+ {kind === "sales" ? "Satış faturası" : "Alış faturası"}</button>}
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Ödeme durumu">
          <option value="">Tümü</option>
          <option value="open">Ödenmemiş (açık)</option>
          <option value="overdue">Vadesi geçmiş</option>
          <option value="paid">Ödenmiş</option>
        </select>
        <input placeholder="Ara (no, firma)…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{rows.length.toLocaleString("tr-TR")} fatura · kalan {fmtMoney(sumMoney(rows.map((r) => r.base_remaining)))}</span>
        {rows.some((r) => r.base_remaining == null) && <span className="badge warn" title="Kuru bilinmediği için toplama katılmadı">{rows.filter((r) => r.base_remaining == null).length} belgede kur yok</span>}
      </div>
      <Loading error={list.error} loading={list.isLoading} />
      {list.data && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>Fatura no</th><th>{kind === "sales" ? "Müşteri" : "Tedarikçi"}</th><th>Proje</th><th>Durum</th><th>Tarih</th><th>Vade</th>
              <th className="num">Toplam</th><th className="num">Ödenen</th><th className="num">Kalan</th></tr></thead>
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
              {!rows.length && <tr><td colSpan={9} className="muted empty">Fatura yok.{kind === "sales" ? " Satış ekranında onaylı siparişten de fatura oluşturabilirsiniz." : " Satın alma siparişinden de alış faturası girebilirsiniz."}</td></tr>}
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
    onSuccess: () => { toast("Fatura silindi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const delPay = useMutation({
    mutationFn: (p: Payment) => api.del(`/payments/${p.id}`),
    onSuccess: () => { toast("Ödeme silindi"); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  if (editing && inv) return <InvoiceEditor kind={inv.kind} invoice={inv} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  if (paying && inv) return <PaymentEditor invoice={inv} onClose={() => setPaying(false)} />;
  const busy = status.isPending || del.isPending;
  return (
    <Modal wide title={inv ? `${inv.kind_label} ${inv.no}` : "Fatura"} onClose={onClose}
      footer={inv && <>
        <button className="btn" onClick={() => void download(`/invoices/${id}/xlsx`, `${inv.no}.xlsx`).catch((e) => toast(errText(e), true))}>Excel</button>
        <span style={{ flex: 1 }} />
        {canEdit && inv.status === "draft" && <>
          <button className="btn danger" disabled={busy} onClick={() => confirm(`${inv.no} silinsin mi?`) && del.mutate()}>Sil</button>
          <button className="btn" onClick={() => setEditing(true)}>Düzenle</button>
          <button className="btn primary" disabled={busy || !inv.lines?.length} onClick={() => status.mutate("issued")}>Faturayı kes</button>
        </>}
        {canEdit && inv.status === "issued" && <>
          <button className="btn danger" disabled={busy} onClick={() => confirm(`${inv.no} iptal edilsin mi?`) && status.mutate("cancelled")}>İptal et</button>
          {inv.remaining > 0 && !inv.is_credit && <button className="btn primary" onClick={() => setPaying(true)}>{inv.kind === "sales" ? "Tahsilat gir" : "Ödeme gir"}</button>}
        </>}
      </>}>
      <Loading error={q.error} loading={q.isLoading} />
      {inv && (
        <>
          <div className="erp-head">
            <div><span className="muted">Durum</span>
              {inv.pay_state
                ? <span className="badge" style={statusStyle(PAY_COLORS[inv.pay_state])}>{inv.pay_label}</span>
                : <span className="badge" style={statusStyle(INV_COLORS[inv.status])}>{inv.status_label}</span>}
            </div>
            <div><span className="muted">Firma</span><b>{inv.firm_name}</b></div>
            <div><span className="muted">Proje</span>{inv.project_name ?? "—"}</div>
            <div><span className="muted">Fatura tarihi</span>{fmtDay(inv.invoice_date)}</div>
            <div><span className="muted">Vade</span><span className={inv.pay_state === "overdue" ? "error" : undefined}>{fmtDay(inv.due_date) || "—"}</span></div>
            {inv.is_credit
              ? <div><span className="muted">İlgili fatura</span><b>{inv.credit_of_no ?? "—"}</b></div>
              : <div><span className="muted">Ödenen / kalan</span>{fmtMoney(inv.paid, inv.currency)} / <b>{fmtMoney(inv.remaining, inv.currency)}</b></div>}
            {!!inv.credited && <div><span className="muted">{inv.kind === "sales" ? "Alacak dekontu" : "İade faturası"}</span>{fmtMoney(inv.credited, inv.currency)}</div>}
            {inv.base_total !== inv.total && (
              <div><span className="muted">Kur</span>{inv.rate == null ? <span className="badge warn">kur yok</span> : `${fmtRate(inv.rate)} · ${fmtMoney(inv.base_total)}`}</div>
            )}
          </div>
          {inv.note && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{inv.note}</p>}
          <LinesTable lines={inv.lines ?? []} currency={inv.currency} subtotal={inv.subtotal} discount={inv.discount} discountPct={inv.discount_pct}
            tax={inv.tax} taxRate={inv.tax_rate} total={inv.total} />
          {!!inv.credits?.length && (
            <p className="muted">Bağlı belgeler: {inv.credits.map((c) => `${c.no} (${c.status_label}, ${fmtMoney(c.total, inv.currency)})`).join(" · ")}</p>
          )}
          {inv.is_credit && inv.status === "draft" && <p className="muted">Kesildiğinde cari bakiyeden düşer ve ilgili faturanın kalanını azaltır.</p>}
          {inv.status === "draft" && <p className="muted">Taslak fatura cari bakiyeye yansımaz. “Faturayı kes” ile kesinleştirin.</p>}
          {!!inv.payments?.length && (
            <>
              <h2>{inv.kind === "sales" ? "Tahsilatlar" : "Ödemeler"}</h2>
              <table className="simple erp-table">
                <thead><tr><th>Tarih</th><th>Yöntem</th><th>Not</th><th className="num">Tutar</th><th></th></tr></thead>
                <tbody>
                  {inv.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{fmtDay(p.pay_date)}</td><td>{p.method}</td><td className="muted">{p.note}</td>
                      <td className="num">{fmtMoney(p.amount, p.currency)}</td>
                      <td>{canEdit && <button className="btn small" disabled={delPay.isPending} onClick={() => confirm("Ödeme kaydı silinsin mi?") && delPay.mutate(p)}>Sil</button>}</td>
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
    onSuccess: (i) => { toast(invoice ? "Fatura kaydedildi" : `${i.no} oluşturuldu (taslak)`); refresh(); onSaved(i); },
    onError: (e) => toast(errText(e), true),
  });
  const invalid = !firmId || (kind === "purchase" && !no.trim());
  return (
    <Modal wide title={invoice ? `Faturayı düzenle: ${invoice.no}` : kind === "sales" ? "Yeni satış faturası" : "Yeni alış faturası"} onClose={onClose}
      footer={<>
        <span className="muted" style={{ marginRight: "auto" }}>Genel toplam (KDV dahil): <b>{fmtMoney(total, currency)}</b></span>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={invalid || save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form two">
        {kind === "purchase"
          ? <Field label="Tedarikçinin fatura no"><input value={no} onChange={(e) => setNo(e.target.value)} /></Field>
          : <Field label="Fatura no" hint="Kaydedince otomatik verilir (FT-yıl-sıra)."><input disabled value={invoice?.no ?? "otomatik"} /></Field>}
        <Field label={kind.startsWith("sales") ? "Müşteri" : "Tedarikçi"}>
          <FirmSelect kind={kind === "sales" ? "customer" : undefined} value={firmId} onChange={setFirmId} />
        </Field>
        <Field label="Proje"><ProjectSelect value={project} onChange={setProject} /></Field>
        <Field label="KDV %"><input style={{ width: 80 }} inputMode="decimal" value={tax} onChange={(e) => setTax(e.target.value)} /></Field>
        <Field label="Fatura tarihi"><input type="date" value={date ?? ""} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Vade"><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={date}
          currencyLocked={!!(invoice?.sales_order_id || invoice?.purchase_order_id)} />
        <Field label="Not"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
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
    <Modal title={invoice ? `${direction === "in" ? "Tahsilat" : "Ödeme"}: ${invoice.no}` : "Yeni tahsilat / ödeme"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={amt <= 0 || (!invoice && !firmId) || save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form">
        {!invoice && (
          <>
            <Field label="Tür">
              <div className="seg">
                <button className={direction === "in" ? "on" : ""} onClick={() => setDirection("in")}>Tahsilat (para girişi)</button>
                <button className={direction === "out" ? "on" : ""} onClick={() => setDirection("out")}>Ödeme (para çıkışı)</button>
              </div>
            </Field>
            <Field label="Firma" hint="Faturaya bağlı olmayan ödeme cari hesaba (avans / mahsup) işlenir."><FirmSelect value={firmId} onChange={setFirmId} /></Field>
          </>
        )}
        {invoice && <p className="muted">Kalan borç: <b>{fmtMoney(invoice.remaining, invoice.currency)}</b></p>}
        <Field label="Tutar"><input inputMode="decimal" autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Tarih"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={date} currencyLocked={!!invoice} />
        <Field label="Yöntem">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>{sys.pay_methods.map((m) => <option key={m}>{m}</option>)}</select>
        </Field>
        <Field label="Not (dekont no vb.)"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
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
    onSuccess: () => { toast("Silindi"); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const rows = list.data ?? [];
  const tot = (d: string) => rows.filter((r) => r.direction === d).reduce((s, r) => s + (r.base_amount ?? 0), 0);
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>+ Tahsilat / ödeme</button>}
        <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Tür">
          <option value="">Tümü</option><option value="in">Tahsilatlar</option><option value="out">Ödemeler</option>
        </select>
        <span className="muted">Giriş {fmtMoney(tot("in"))} · Çıkış {fmtMoney(tot("out"))}</span>
        {rows.some((r) => r.base_amount == null) && <span className="badge warn" title="Kuru bilinmediği için toplama katılmadı">{rows.filter((r) => r.base_amount == null).length} kayıtta kur yok</span>}
      </div>
      <Loading error={list.error} loading={list.isLoading} />
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>Tarih</th><th>Tür</th><th>Firma</th><th>Fatura</th><th>Yöntem</th><th>Not</th><th className="num">Tutar</th><th></th></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>{fmtDay(p.pay_date)}</td>
                <td><span className={p.direction === "in" ? "badge new" : "badge warn"}>{p.direction_label}</span></td>
                <td>{p.firm_name}</td><td className="mono">{p.invoice_no ?? <span className="muted">cari</span>}</td>
                <td>{p.method}</td><td className="muted">{p.note}</td>
                <td className="num"><b>{fmtMoney(p.amount, p.currency)}</b></td>
                <td>{canEdit && <button className="btn small" disabled={del.isPending} onClick={() => confirm("Kayıt silinsin mi?") && del.mutate(p)}>Sil</button>}</td>
              </tr>
            ))}
            {!rows.length && !list.isLoading && <tr><td colSpan={8} className="muted empty">Kayıt yok.</td></tr>}
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
        <input placeholder="Firma ara…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Değerleme kuru" value={basis} onChange={(e) => onBasis(e.target.value as BalanceBasis)}>
          <option value="today">Bugünkü kurla</option>
          <option value="doc">Belge tarihindeki kurla</option>
        </select>
        <span className="muted">Pozitif bakiye: firma bize borçlu. Negatif: biz firmaya borçluyuz. {base} karşılığı {BASIS_TEXT[basis]} hesaplanır. Kur farkı, belge kuruyla değer eksi bugünkü değerdir.</span>
      </div>
      <Loading error={bal.error} loading={bal.isLoading} />
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>Firma</th><th className="num">Satış</th><th className="num">Tahsilat</th><th className="num">Alış</th><th className="num">Ödeme</th>
            <th className="num">Bakiye</th><th className="num">{base} karşılığı</th><th className="num">Kur farkı</th><th className="num">Vadesi geçen</th><th></th></tr></thead>
          <tbody>
            {firms.map((group) => (
              <Fragment key={`${group[0].firm_id}-${group[0].firm_name}`}>
                {group.map((b, i) => (
                  <tr key={b.currency}>
                    <td>{i === 0 ? <b>{b.firm_name}</b> : <span className="muted">{b.currency}</span>}</td>
                    <td className="num">{fmtMoney(b.sales, b.currency)}</td><td className="num">{fmtMoney(b.collected, b.currency)}</td>
                    <td className="num">{fmtMoney(b.purchases, b.currency)}</td><td className="num">{fmtMoney(b.paid, b.currency)}</td>
                    <td className={`num ${b.balance > 0 ? "ok" : b.balance < 0 ? "warn" : ""}`}><b>{fmtMoney(b.balance, b.currency)}</b></td>
                    <td className="num">{b.base_balance == null ? <span className="badge warn">kur yok</span> : fmtMoney(b.base_balance, base)}</td>
                    <td className="num muted">{b.fx_diff ? fmtMoney(b.fx_diff, base) : ""}</td>
                    <td className="num error">{b.overdue_receivable || b.overdue_payable ? fmtMoney(b.overdue_receivable || b.overdue_payable, b.currency) : ""}</td>
                    <td>{i === 0 && b.firm_id && <button className="btn small" onClick={() => setLedger({ id: b.firm_id!, name: b.firm_name })}>Ekstre</button>}</td>
                  </tr>
                ))}
                {group.length > 1 && (
                  <tr>
                    <td colSpan={6} className="num muted">{group[0].firm_name} toplam</td>
                    <td className="num"><b>{fmtMoney(sumMoney(group.map((b) => b.base_balance)), base)}</b></td>
                    <td colSpan={3}></td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!rows.length && !bal.isLoading && <tr><td colSpan={10} className="muted empty">Kesilmiş fatura veya ödeme yok.</td></tr>}
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
    onSuccess: (r) => { toast(`${r.count} kur alındı (${fmtDay(r.rate_date)})`); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const add = useMutation({
    mutationFn: () => api.post("/rates", { currency: currency.trim().toUpperCase(), rate: numOrNull(rate), rate_date: day || null }),
    onSuccess: () => { toast("Kur kaydedildi"); setRate(""); done(); },
    onError: (e) => toast(errText(e), true),
  });
  const base = list.data?.base ?? sys.currency;
  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>Güncel kurlar</h3>
          {canEdit && <button className="btn primary" disabled={fetchNow.isPending} onClick={() => fetchNow.mutate()}>Merkez Bankası'ndan al</button>}
          <span className="muted">Sunucu günde bir kez kendisi de dener. İnternet yoksa kuru elle girin. 1 birim yabancı para = kaç {base}.</span>
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>Para birimi</th><th className="num">Kur ({base})</th><th>Tarih</th><th>Kaynak</th></tr></thead>
            <tbody>
              {(list.data?.latest ?? []).map((r) => (
                <tr key={r.id}><td><b>{r.currency}</b></td><td className="num">{fmtRate(r.rate)}</td><td>{fmtDay(r.rate_date)}</td><td>{r.source_label}</td></tr>
              ))}
              {list.data && !list.data.latest.length && <tr><td colSpan={4} className="muted empty">Henüz kur yok.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {canEdit && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>Elle kur gir</h3>
          <div className="adm-form two">
            <Field label="Para birimi"><input maxLength={3} placeholder="EUR" value={currency} onChange={(e) => setCurrency(e.target.value)} /></Field>
            <Field label={`Kur (1 birim = ? ${base})`}><input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} /></Field>
            <Field label="Tarih"><input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} /></Field>
            <div style={{ alignSelf: "end" }}>
              <button className="btn primary" disabled={add.isPending || currency.trim().length !== 3 || !((numOrNull(rate) ?? 0) > 0)} onClick={() => add.mutate()}>Kaydet</button>
            </div>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>Elle girilen kur, aynı günün Merkez Bankası kurunun üstüne yazılmaz; geçerli kalır.</p>
        </div>
      )}
      <div className="card" style={{ marginTop: 12 }}>
        <h3 style={{ marginTop: 0 }}>Geçmiş</h3>
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead><tr><th>Tarih</th><th>Para birimi</th><th className="num">Kur</th><th>Kaynak</th></tr></thead>
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
