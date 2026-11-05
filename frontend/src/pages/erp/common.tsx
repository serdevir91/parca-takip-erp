import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { curSign, sys } from "../../api/system";
import type { Project } from "../../types";
import { Field, Modal } from "../admin/shared";
import { money, qty } from "../../api/num";
import { LOCALE, tx } from "../../api/i18n";

// ---------- types (backend/app/services/erp.py) ----------
export type ItemKind = "part" | "fastener" | "other";
export type PoLine = {
  id?: number; seq?: number; code: string; kind: ItemKind | string; kind_label?: string; description: string; unit: string;
  qty: number; received_qty?: number; remaining?: number; unit_price: number | null; amount?: number | null;
  billed_qty?: number; billable?: number; to_bill?: number;
};
export type Receipt = {
  id: number; line_id: number | null; code: string; description: string; unit: string; qty: number;
  received_at: string | null; username: string; note: string;
};
export type PurchaseOrder = {
  id: number; no: string; firm_id: number | null; firm_name: string; project_id: number | null; project_name: string | null;
  status: string; status_label: string; order_date: string | null; due_date: string | null; overdue: boolean;
  currency: string; rate: number | null; base_total: number | null; note: string; created_at: string | null;
  created_by: string; line_count: number; total: number; received_value: number; received_pct: number;
  missing_price: number; lines?: PoLine[]; receipts?: Receipt[]; rev?: number; needs_rate?: boolean;
};
export type WorkOrder = {
  rev?: number; id: number; no: string; project_id: number | null; project_name: string | null; part_no: string; description: string;
  qty: number; done_qty: number; remaining: number; firm_name: string; subcontract: boolean; status: string;
  status_label: string; start_date: string | null; due_date: string | null; overdue: boolean; unit_cost: number | null;
  total_cost: number | null; note: string; created_at: string | null; created_by: string; ops_done: number; ops_total: number;
};
/** What a completion could not take out of stock; the completion itself stands. */
export type WoWarning = { code: string; description: string; unit: string; needed: number; issued: number; short: number; message: string };
export type WoMaterial = {
  id: number; seq: number; code: string; description: string; unit: string; planned_qty: number; issued_qty: number;
  remaining: number; has_card: boolean; stock_qty: number | null;
};
export type WoOp = {
  id: number; seq: number; name: string; planned_hours: number | null; status: string; status_label: string;
  done_by: string; done_at: string | null; note: string;
};
export type StockItem = {
  rev?: number;
  id: number; code: string; name: string; kind: ItemKind | string; kind_label: string; unit: string; qty: number;
  min_qty: number; unit_cost: number | null; value: number | null; low: boolean; location: string; note: string;
  updated_at: string | null; reorder_qty: number; preferred_firm_id: number | null;
};
export type ReorderRow = {
  item_id: number; code: string; name: string; unit: string; qty: number; min_qty: number; on_order: number; available: number;
  reorder_qty: number; suggested_qty: number; firm_id: number | null; firm_name: string; firm_source: string; firm_missing: boolean;
  last_price: number | null; last_currency: string | null;
};
export type StockMove = {
  id: number; ts: string | null; kind: string; kind_label: string; qty: number; balance: number; unit_cost: number | null;
  project_id: number | null; project_name: string | null; ref: string; note: string; username: string;
  code: string | null; name: string | null;
};
export type FirmBrief = { id: number; name: string; kind: string; contact: string; phone: string; email: string; lead_days: number };

export const ITEM_KINDS: { value: ItemKind; label: string }[] = [
  { value: "part", label: tx("Parça") },
  { value: "fastener", label: tx("Bağlantı elemanı") },
  { value: "other", label: tx("Diğer") },
];

// Status colours: hex without '#', rendered through statusStyle like part statuses
export const PO_COLORS: Record<string, string> = {
  draft: "E7E6E6", sent: "FFEB9C", partial: "F8CBAD", received: "C6EFCE", closed: "BDD7EE", cancelled: "D9D9D9",
};
export const WO_COLORS: Record<string, string> = {
  planned: "E7E6E6", in_progress: "FFEB9C", done: "C6EFCE", closed: "BDD7EE", cancelled: "D9D9D9",
};
export const OP_COLORS: Record<string, string> = { pending: "E7E6E6", in_progress: "FFEB9C", done: "C6EFCE" };

export const fmtQty = (n: number | null | undefined) =>
  n == null ? "" : qty(n).toLocaleString(LOCALE, { maximumFractionDigits: 3 });
export const fmtMoney = (n: number | null | undefined, cur = sys.currency) =>
  n == null ? "" : `${money(n).toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${curSign(cur)}`;
export const fmtDay = (s: string | null | undefined) => {
  if (!s) return "";
  const d = new Date(tx("{0}T00:00:00", s.slice(0, 10)));
  return isNaN(d.getTime()) ? s : d.toLocaleDateString(LOCALE);
};
/** The local calendar day; toISOString would still say yesterday until 03:00 in Türkiye. */
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const addDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
export const trIncludes = (hay: string, needle: string) =>
  hay.toLocaleLowerCase(LOCALE).includes(needle.trim().toLocaleLowerCase(LOCALE));
/** Number input value -> number | null (empty = null). */
export const numOrNull = (v: string): number | null => {
  const t = v.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

/** Rate typed in a form: empty means "take it from the rate table". */
export const fmtRate = (n: number | null | undefined) =>
  n == null ? "" : n.toLocaleString(LOCALE, { maximumFractionDigits: 6 });

export type Rate = { id: number; rate_date: string; currency: string; rate: number; source: string; source_label: string };
export type RateList = { base: string; latest: Rate[]; rows: Rate[] };

export function useRates() {
  return useQuery({ queryKey: ["rates"], queryFn: () => api.get<RateList>("/rates"), staleTime: 60_000 });
}

/** Currency and document rate fields of a form. Changing the currency or the day fills the rate from the table;
 *  the user can overwrite it. */
export function CurrencyRate({ currency, setCurrency, rate, setRate, day, locked, currencyLocked }: {
  currency: string; setCurrency: (c: string) => void; rate: string; setRate: (r: string) => void;
  day?: string | null; locked?: boolean; currencyLocked?: boolean;
}) {
  const rates = useRates();
  const base = rates.data?.base ?? sys.currency;
  const options = [...new Set([base, "USD", "EUR", "GBP", ...(rates.data?.latest ?? []).map((r) => r.currency), currency])];
  const key = `${currency}|${day ?? ""}`;
  const seen = useRef(key);
  const [looking, setLooking] = useState(false);
  useEffect(() => {
    if (seen.current === key || locked) return;
    seen.current = key;
    if (currency === base) { setRate(""); return; }
    let live = true;
    setLooking(true);
    const p = new URLSearchParams({ currency });
    if (day) p.set("day", day);
    void api.get<{ rate: number | null }>(`/rates/on?${p}`)
      .then((r) => { if (live) setRate(r.rate == null ? "" : String(r.rate)); })
      .finally(() => { if (live) setLooking(false); });
    return () => { live = false; };
  }, [key, locked, base, currency, day, setRate]);
  const foreign = currency !== base;
  return (
    <>
      <Field label={tx("Para birimi")}>
        <select value={currency} disabled={locked || currencyLocked} onChange={(e) => setCurrency(e.target.value)}>
          {options.map((c) => <option key={c} value={c}>{tx(c)}</option>)}
        </select>
      </Field>
      {foreign ? (
        <Field label={tx("Kur (1 {0} = ? {1})", currency, base)}
          hint={locked ? tx("Mal kabulü veya onayı olan belgenin kuru değişmez.")
            : !rate.trim() && !looking ? tx("Bu tarih için kur yok. Buraya yazın veya Fatura ve ödeme > Kurlar'dan ekleyin; kursuz tutar toplamlara katılmaz.") : undefined}>
          <input inputMode="decimal" disabled={locked} value={rate} onChange={(e) => setRate(e.target.value)} />
        </Field>
      ) : <span />}
    </>
  );
}

/** One row of a quantity picker. max stops an entry on the screen too; the server checks it again. */
export type QtyRow = {
  id: number; code: string; description: string; unit: string; cells: React.ReactNode[]; start: number; max?: number;
};

/** Enter a quantity per order line: receipt, reversal, delivery, return, invoice. */
export function QtyModal({ title, intro, heads, rows, qtyLabel, submit, noteLabel = tx("Not"), danger, busy, children, ready = true, onSubmit, onClose }: {
  title: string; intro?: React.ReactNode; heads: string[]; rows: QtyRow[]; qtyLabel: string; submit: string;
  noteLabel?: string | null; danger?: boolean; busy?: boolean; children?: React.ReactNode; ready?: boolean;
  onSubmit: (lines: { line_id: number; qty: number }[], note: string) => void; onClose: () => void;
}) {
  const [qty, setQty] = useState<Record<number, string>>(() => Object.fromEntries(rows.map((r) => [r.id, r.start ? String(r.start) : ""])));
  const [note, setNote] = useState("");
  const val = (r: QtyRow) => numOrNull(qty[r.id] ?? "") ?? 0;
  const over = (r: QtyRow) => r.max != null && val(r) > r.max + 1e-6;
  const lines = rows.map((r) => ({ line_id: r.id, qty: val(r) })).filter((l) => l.qty > 0);
  return (
    <Modal wide title={title} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className={danger ? "btn danger" : "btn primary"} disabled={busy || !ready || !lines.length || rows.some(over)}
          onClick={() => onSubmit(lines, note)}>{submit}</button>
      </>}>
      {intro && <p className="muted">{intro}</p>}
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>{tx("Kalem")}</th>{heads.map((h) => <th key={h} className="num">{h}</th>)}<th className="erp-qty-cell">{qtyLabel}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.code && <div className="mono">{r.code}</div>}{r.description}</td>
                {r.cells.map((c, i) => <td key={i} className="num">{c}</td>)}
                <td className="erp-qty-cell">
                  <input style={{ width: 84 }} inputMode="decimal" aria-label={`${r.code || r.description} ${qtyLabel}`} aria-invalid={over(r)}
                    value={qty[r.id] ?? ""} onChange={(e) => setQty((q) => ({ ...q, [r.id]: e.target.value }))} />
                  {over(r) && <div className="error">{tx("En fazla {0} {1}", fmtQty(r.max), r.unit)}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {children}
      {noteLabel && <div style={{ marginTop: 10 }}><Field label={noteLabel}><input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>}
    </Modal>
  );
}

/** Movement history of an order: receipts or deliveries, reversals in their own wording. */
export function MoveHistory({ title, rows, backLabel }: {
  title: string; backLabel: string;
  rows: { id: number; code: string; description: string; unit: string; qty: number; at: string | null; username: string; note: string }[];
}) {
  if (!rows.length) return null;
  return (
    <>
      <h2>{title}</h2>
      <div className="adm-scroll">
        <table className="simple erp-table">
          <thead><tr><th>{tx("Tarih")}</th><th>{tx("Kalem")}</th><th className="num">{tx("Miktar")}</th><th>{tx("Kullanıcı")}</th><th>{tx("Not")}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{fmtDay(r.at)}</td><td>{r.code || r.description}</td>
                <td className="num">{r.qty < 0 ? <span className="badge warn">{backLabel} {fmtQty(-r.qty)}</span> : fmtQty(r.qty)} {tx(r.unit)}</td>
                <td>{r.username}</td><td className="muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function useFirms(kind?: "supplier" | "manufacturer" | "customer") {
  return useQuery({
    queryKey: ["firms", kind ?? ""],
    queryFn: () => api.get<FirmBrief[]>(`/firms${kind ? `?kind=${kind}` : ""}`),
    staleTime: 60_000,
  });
}

export function useProjects() {
  return useQuery({ queryKey: ["projects", "picker"], queryFn: () => api.get<Project[]>("/projects"), staleTime: 60_000 });
}

export function FirmSelect({ value, onChange, kind, emptyLabel = tx("(Firma seçilmedi)") }: {
  value: number | null; onChange: (id: number | null) => void; kind?: "supplier" | "manufacturer" | "customer"; emptyLabel?: string;
}) {
  const firms = useFirms(kind);
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{tx(emptyLabel)}</option>
      {(firms.data ?? []).map((f) => (
        <option key={f.id} value={f.id}>{f.name}{f.lead_days ? tx(" (termin {0} gün)", f.lead_days) : ""}</option>
      ))}
    </select>
  );
}

export function ProjectSelect({ value, onChange, emptyLabel = tx("(Proje yok)") }: {
  value: number | null; onChange: (id: number | null) => void; emptyLabel?: string;
}) {
  const projects = useProjects();
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{tx(emptyLabel)}</option>
      {(projects.data ?? []).filter((p) => !p.archived || p.id === value).map((p) => (
        <option key={p.id} value={p.id}>{p.name}</option>
      ))}
    </select>
  );
}

/** Firm name picker for work orders: "" = iç üretim, otherwise a manufacturer (free text allowed). */
export function MakerInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const firms = useFirms("manufacturer");
  const sub = value !== "";
  return (
    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      <select value={sub ? "sub" : "in"} onChange={(e) => onChange(e.target.value === "sub" ? (firms.data?.[0]?.name ?? " ") : "")}>
        <option value="in">{tx("İç üretim")}</option>
        <option value="sub">{tx("Fason")}</option>
      </select>
      {sub && (
        <>
          <input list="erp-makers" value={value.trim() ? value : ""} placeholder={tx("Fason firma")} onChange={(e) => onChange(e.target.value || " ")} />
          <datalist id="erp-makers">{(firms.data ?? []).map((f) => <option key={f.id} value={f.name} />)}</datalist>
        </>
      )}
    </div>
  );
}
