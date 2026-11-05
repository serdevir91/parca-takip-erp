import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { docTotals, money } from "../../api/num";
import { sys } from "../../api/system";
import { Loading, Modal } from "../admin/shared";
import { fmtDay, fmtMoney, fmtQty, fmtRate, numOrNull } from "./common";

// ---------- types (backend/app/services/commerce.py, api/hr.py) ----------
export type DocLine = {
  id?: number; seq?: number; code: string; description: string; unit: string; qty: number;
  unit_price: number | null; amount?: number | null; source_line_id?: number | null;
  delivered_qty?: number; remaining?: number; billed_qty?: number; billable?: number; to_bill?: number;
};
export type Delivery = {
  id: number; line_id: number | null; code: string; description: string; unit: string; qty: number;
  delivered_at: string | null; username: string; note: string;
};
type Totals = { subtotal: number; tax: number; total: number };
export type SalesOrder = Totals & {
  id: number; no: string; firm_id: number | null; firm_name: string; project_id: number | null; project_name: string | null;
  status: string; status_label: string; order_date: string | null; valid_until: string | null; due_date: string | null;
  expired: boolean; late: boolean; currency: string; rate: number | null; base_total: number | null; delivered_pct: number;
  tax_rate: number; discount_pct: number; discount: number; note: string; created_by: string; line_count: number;
  invoiced: number; missing_price: number; next_statuses: string[]; lines?: DocLine[]; deliveries?: Delivery[]; rev?: number;
};
export type Payment = {
  id: number; direction: "in" | "out"; direction_label: string; firm_id: number | null; firm_name: string;
  invoice_id: number | null; invoice_no: string | null; pay_date: string | null; amount: number; currency: string;
  rate: number | null; base_amount: number | null; method: string; note: string; created_by: string;
};
export type InvoiceKind = "sales" | "purchase" | "sales_credit" | "purchase_credit";
export type Invoice = Totals & {
  id: number; kind: InvoiceKind; kind_label: string; no: string; firm_id: number | null; firm_name: string;
  project_id: number | null; project_name: string | null; sales_order_id: number | null; purchase_order_id: number | null;
  status: string; status_label: string; pay_state: string | null; pay_label: string; invoice_date: string | null;
  due_date: string | null; currency: string; rate: number | null; base_total: number | null; base_remaining: number | null;
  tax_rate: number; note: string; created_by: string; line_count: number; paid: number; remaining: number; lines?: DocLine[]; payments?: Payment[];
  rev?: number; is_credit: boolean; credit_of_id: number | null; credit_of_no?: string | null; discount: number; discount_pct: number; credited: number;
  credits?: { id: number; no: string; status: string; status_label: string; total: number }[];
};
export type Balance = {
  firm_id: number | null; firm_name: string; firm_kind: string | null; currency: string; sales: number; collected: number;
  purchases: number; paid: number; balance: number; receivable: number; payable: number;
  overdue_receivable: number; overdue_payable: number; rate: number | null; base_balance: number | null;
  base_receivable: number | null; base_payable: number | null; base_overdue_receivable: number | null;
  base_overdue_payable: number | null; basis: BalanceBasis; fx_diff: number | null;
};
export type BalanceBasis = "today" | "doc";
export const BASIS_TEXT: Record<BalanceBasis, string> = { today: "bugünkü kurla", doc: "belge tarihindeki kurla" };
export type LedgerRow = {
  date: string | null; due_date: string | null; doc: "invoice" | "payment"; id: number; no: string; label: string;
  currency: string; debit: number; credit: number; balance: number; rate: number | null; base_amount: number | null;
};
type Ledger = { rows: LedgerRow[]; balance: Record<string, number>; base: string; basis: BalanceBasis; base_balance: number; fx_diff: number | null; unconverted: string[] };
export type Employee = {
  id: number; name: string; title: string; department: string; phone: string; email: string; hourly_cost: number | null;
  start_date: string | null; active: boolean; note: string; hours_30d: number; user_id: number | null; annual_leave_days: number | null; rev?: number;
};
export type TimeEntry = {
  rev?: number; id: number; employee_id: number; employee_name: string; work_date: string; hours: number; project_id: number | null;
  project_name: string | null; work_order_id: number | null; work_order_no: string | null; hourly_cost: number | null;
  cost: number | null; note: string; created_by: string;
};

export const SO_COLORS: Record<string, string> = {
  draft: "E7E6E6", quoted: "BDD7EE", confirmed: "FFEB9C", partial: "FFD9A0", delivered: "C6EFCE", closed: "C9DAF8", cancelled: "D9D9D9",
  lost: "F8CBAD",
};
export const INV_COLORS: Record<string, string> = { draft: "E7E6E6", issued: "BDD7EE", cancelled: "D9D9D9" };
export const PAY_COLORS: Record<string, string> = { unpaid: "FFEB9C", partial: "F8CBAD", paid: "C6EFCE", overdue: "FF9999" };
export const SO_ACTIONS: Record<string, string> = {
  quoted: "Teklif olarak gönder", confirmed: "Sipariş onaylandı", delivered: "Tümü teslim edildi", lost: "Kaybedildi",
  cancelled: "İptal et", draft: "Taslağa al",
};

export function useBalances(enabled = true, basis?: BalanceBasis) {
  return useQuery({
    queryKey: ["balances", basis ?? "setting"],
    queryFn: () => api.get<Balance[]>(`/balances${basis ? `?basis=${basis}` : ""}`),
    enabled,
  });
}

/** Totals of a form still being typed, by the same steps the server will use once it is saved. */
export const formTotals = (lines: { qty: number }[], prices: string[], taxRate = 0, discountPct = 0) =>
  docTotals(lines.map((l, i) => ({ qty: l.qty || 0, price: numOrNull(prices[i] ?? "") ?? 0 })), taxRate, discountPct);

/** Editable document lines (sales order, invoice). Prices are kept as text so "12,5" can be typed. */
export function LinesEditor({ lines, setLines, prices, setPrices, currency = sys.currency }: {
  lines: DocLine[]; setLines: (f: (l: DocLine[]) => DocLine[]) => void;
  prices: string[]; setPrices: (f: (p: string[]) => string[]) => void; currency?: string;
}) {
  const upd = (i: number, patch: Partial<DocLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div className="adm-scroll" style={{ marginTop: 12 }}>
      <table className="simple erp-table erp-lines">
        <thead><tr><th>Kod</th><th>Açıklama</th><th>Birim</th><th>Miktar</th><th>Birim fiyat</th><th className="num">Tutar</th><th></th></tr></thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td><input value={l.code} onChange={(e) => upd(i, { code: e.target.value })} /></td>
              <td><input value={l.description} onChange={(e) => upd(i, { description: e.target.value })} /></td>
              <td><input style={{ width: 60 }} value={l.unit} onChange={(e) => upd(i, { unit: e.target.value })} /></td>
              <td><input style={{ width: 80 }} type="number" min={0} step="any" value={l.qty} onChange={(e) => upd(i, { qty: Number(e.target.value) })} /></td>
              <td><input style={{ width: 110 }} inputMode="decimal" value={prices[i] ?? ""}
                onChange={(e) => setPrices((p) => { const n = [...p]; n[i] = e.target.value; return n; })} /></td>
              <td className="num">{fmtMoney(money((numOrNull(prices[i] ?? "") ?? 0) * (l.qty || 0)), currency)}</td>
              <td>
                <button className="btn small" aria-label="Satırı sil" onClick={() => {
                  setLines((ls) => ls.filter((_, j) => j !== i));
                  setPrices((p) => p.filter((_, j) => j !== i));
                }}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn small" style={{ marginTop: 6 }} onClick={() => {
        setLines((ls) => [...ls, emptyLine()]);
        setPrices((p) => [...p, ""]);
      }}>+ Satır ekle</button>
    </div>
  );
}

export const emptyLine = (): DocLine => ({ code: "", description: "", unit: sys.unit, qty: 1, unit_price: null });

export const linesBody = (lines: DocLine[], prices: string[]) =>
  lines
    .map((l, i) => ({ code: l.code.trim(), description: l.description.trim(), unit: l.unit || sys.unit, qty: l.qty,
      unit_price: numOrNull(prices[i] ?? ""), source_line_id: l.source_line_id ?? null }))
    .filter((l) => l.code || l.description);

/** Read-only lines with the totals block under them. */
export function LinesTable({ lines, currency, subtotal, discount, discountPct, tax, taxRate, total, progress }: {
  lines: DocLine[]; currency: string; subtotal: number; discount?: number; discountPct?: number; tax: number;
  taxRate: number; total: number; progress?: boolean;
}) {
  const span = progress ? 8 : 5;
  return (
    <div className="adm-scroll">
      <table className="simple erp-table">
        <thead><tr><th>#</th><th>Kod</th><th>Açıklama</th><th className="num">{progress ? "Sipariş" : "Miktar"}</th>
          {progress && <><th className="num">Teslim</th><th className="num">Faturalanan</th><th className="num">Kalan</th></>}
          <th className="num">Birim fiyat</th><th className="num">Tutar</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.id}>
              <td>{l.seq}</td><td className="mono">{l.code}</td><td>{l.description}</td>
              <td className="num">{fmtQty(l.qty)} {l.unit}</td>
              {progress && <>
                <td className="num">{fmtQty(l.delivered_qty)}</td><td className="num">{fmtQty(l.billed_qty)}</td>
                <td className="num">{l.remaining ? <b>{fmtQty(l.remaining)}</b> : "✓"}</td>
              </>}
              <td className="num">{l.unit_price == null ? <span className="badge warn">fiyat yok</span> : fmtMoney(l.unit_price, currency)}</td>
              <td className="num">{fmtMoney(l.amount, currency)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={span} className="num">Ara toplam</td><td className="num">{fmtMoney(subtotal, currency)}</td></tr>
          {!!discount && <tr><td colSpan={span} className="num">İskonto (%{discountPct})</td><td className="num">-{fmtMoney(discount, currency)}</td></tr>}
          <tr><td colSpan={span} className="num">KDV (%{taxRate})</td><td className="num">{fmtMoney(tax, currency)}</td></tr>
          <tr><td colSpan={span} className="num"><b>Genel toplam</b></td><td className="num"><b>{fmtMoney(total, currency)}</b></td></tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Cari ekstre: one firm's invoices and payments with a running balance. */
export function LedgerModal({ firmId, firmName, onClose }: { firmId: number; firmName: string; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["ledger", firmId],
    queryFn: () => api.get<Ledger>(`/firms/${firmId}/ledger`),
  });
  const rows = q.data?.rows ?? [];
  return (
    <Modal wide title={`Cari ekstre: ${firmName}`} onClose={onClose}
      footer={<button className="btn" onClick={onClose}>Kapat</button>}>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && (
        <>
          <div className="row" style={{ marginBottom: 8 }}>
            {Object.entries(q.data.balance).map(([cur, v]) => (
              <span key={cur} className={v > 0 ? "badge new" : v < 0 ? "badge warn" : "badge"}>
                {v > 0 ? "Firma borçlu" : v < 0 ? "Firmaya borçluyuz" : "Bakiye sıfır"}: {fmtMoney(Math.abs(v), cur)}
              </span>
            ))}
            {Object.keys(q.data.balance).some((c) => c !== q.data.base) && (
              <span className="badge">Toplam: {fmtMoney(q.data.base_balance, q.data.base)} ({BASIS_TEXT[q.data.basis]})</span>
            )}
            {!!q.data.fx_diff && <span className="badge" title="Belge kuruyla değer eksi bugünkü kurla değer">Kur farkı: {fmtMoney(q.data.fx_diff, q.data.base)}</span>}
            {!!q.data.unconverted.length && <span className="badge warn">Kuru olmayan: {q.data.unconverted.join(", ")} toplama katılmadı</span>}
            {!rows.length && <span className="muted">Kesilmiş fatura veya ödeme yok.</span>}
          </div>
          {!!rows.length && (
            <div className="adm-scroll">
              <table className="simple erp-table">
                <thead><tr><th>Tarih</th><th>Belge</th><th>No / yöntem</th><th>Vade</th><th className="num">Borç</th><th className="num">Alacak</th><th className="num">Bakiye</th><th className="num">Kur</th><th className="num">{q.data.base} karşılığı</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.doc}${r.id}`}>
                      <td>{fmtDay(r.date)}</td><td>{r.label}</td><td className="mono">{r.no}</td><td>{fmtDay(r.due_date)}</td>
                      <td className="num">{r.debit ? fmtMoney(r.debit, r.currency) : ""}</td>
                      <td className="num">{r.credit ? fmtMoney(r.credit, r.currency) : ""}</td>
                      <td className="num"><b>{fmtMoney(r.balance, r.currency)}</b></td>
                      <td className="num">{r.currency === q.data.base ? "" : r.rate == null ? <span className="badge warn">kur yok</span> : fmtRate(r.rate)}</td>
                      <td className="num">{fmtMoney(r.base_amount, q.data.base)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">Borç: firmanın bize borcunu artırır (satış faturası, bizim yaptığımız ödeme). Alacak: azaltır (alış faturası, tahsilat).</p>
        </>
      )}
    </Modal>
  );
}

/** KPI tile used on the home page and module headers. */
export function Stat({ label, value, sub, tone, onClick }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "ok" | "warn" | "error"; onClick?: () => void;
}) {
  return (
    <div className={`card stat${onClick ? " clickable" : ""}`} onClick={onClick} role={onClick ? "button" : undefined}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value${tone ? ` ${tone}` : ""}`}>{value}</div>
      {sub && <div className="stat-sub muted">{sub}</div>}
    </div>
  );
}
