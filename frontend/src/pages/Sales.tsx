import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { api, download } from "../api/client";
import { sys } from "../api/system";
import { useAuth } from "../api/auth";
import { saveRev } from "../api/conflict";
import { sumMoney } from "../api/num";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import {
  CurrencyRate, FirmSelect, MoveHistory, ProjectSelect, QtyModal, addDays, fmtDay, fmtMoney, fmtQty, fmtRate, numOrNull, trIncludes, useFirms,
} from "./erp/common";
import {
  LinesEditor, LinesTable, SO_ACTIONS, SO_COLORS, Stat, emptyLine, formTotals, linesBody, type DocLine, type SalesOrder,
} from "./erp/commerce";
import { LOCALE, tx } from "../api/i18n";

type ListResp = { rows: SalesOrder[]; statuses: Record<string, string>; base: string };

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["sales-orders", "sales-order", "invoices", "balances", "overview", "stock", "costs"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

/** Satış: teklifler ve satış siparişleri. */
export default function Sales() {
  const { can } = useAuth();
  const canEdit = can("sales", "edit");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["sales-orders", status],
    queryFn: () => api.get<ListResp>(`/sales-orders${status ? `?status=${status}` : ""}`),
  });
  const rows = useMemo(
    () => (list.data?.rows ?? []).filter((r) => !q.trim() || trIncludes(`${r.no} ${r.firm_name} ${r.project_name ?? ""} ${r.note}`, q)),
    [list.data, q],
  );
  const sum = (f: (r: SalesOrder) => boolean) => sumMoney(rows.filter(f).map((r) => r.base_total));
  const noRate = rows.filter((r) => r.base_total == null).length;

  return (
    <Page>
      <PageHeader icon={TrendingUp} title={tx("Satış ve teklif")} sub={tx("Müşteri teklifleri, satış siparişleri ve faturaya dönüştürme")}>
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>{tx("+ Yeni teklif")}</button>}
      </PageHeader>
      <div className="grid stats">
        <Stat label={tx("Açık teklifler")} value={rows.filter((r) => r.status === "draft" || r.status === "quoted").length}
          sub={fmtMoney(sum((r) => r.status === "draft" || r.status === "quoted"))} />
        <Stat label={tx("Onaylı siparişler")} value={rows.filter((r) => r.status === "confirmed" || r.status === "partial").length}
          sub={fmtMoney(sum((r) => r.status === "confirmed" || r.status === "partial"))} />
        <Stat label={tx("Teslimi geciken")} value={rows.filter((r) => r.late).length} tone={rows.some((r) => r.late) ? "error" : undefined} />
        <Stat label={tx("Süresi dolan teklif")} value={rows.filter((r) => r.expired).length} tone={rows.some((r) => r.expired) ? "warn" : undefined} />
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={tx("Durum")}>
            <option value="open">{tx("Açık (taslak, teklif, onaylı, kısmi teslim)")}</option>
            <option value="">{tx("Tümü")}</option>
            {Object.entries(list.data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{tx(v)}</option>)}
          </select>
          <input placeholder={tx("Ara (no, müşteri, proje)…")} value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{tx("{0} kayıt · {1}", rows.length.toLocaleString(LOCALE), fmtMoney(sum(() => true)))}</span>
          {noRate > 0 && <span className="badge warn" title={tx("Kuru bilinmediği için toplama katılmadı")}>{tx("{0} belgede kur yok", noRate)}</span>}
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr><th>{tx("No")}</th><th>{tx("Müşteri")}</th><th>{tx("Proje")}</th><th>{tx("Durum")}</th><th>{tx("Tarih")}</th><th>{tx("Geçerlilik")}</th><th>{tx("Teslim")}</th>
                  <th className="num">{tx("Tutar (KDV dahil)")}</th><th className="num">{tx("Sevk")}</th><th className="num">{tx("Faturalanan")}</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => setOpenId(r.id)}>
                    <td><b>{r.no}</b></td>
                    <td>{r.firm_name}</td>
                    <td>{r.project_name ?? <span className="muted">—</span>}</td>
                    <td><span className="badge" style={statusStyle(SO_COLORS[r.status])}>{r.status_label}</span></td>
                    <td>{fmtDay(r.order_date)}</td>
                    <td className={r.expired ? "warn" : undefined}>{fmtDay(r.valid_until)}{r.expired ? tx(" (doldu)") : ""}</td>
                    <td className={r.late ? "error" : undefined}>{fmtDay(r.due_date)}{r.late ? tx(" (gecikti)") : ""}</td>
                    <td className="num">{fmtMoney(r.total, r.currency)}</td>
                    <td className="num">{r.delivered_pct ? `%${r.delivered_pct.toLocaleString(LOCALE)}` : <span className="muted">—</span>}</td>
                    <td className="num">{r.invoiced ? fmtMoney(r.invoiced, r.currency) : <span className="muted">—</span>}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={10} className="muted empty">{tx("Kayıt yok. “Yeni teklif” ile başlayın.")}</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {openId !== null && <OrderModal id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />}
      {creating && <OrderEditor onClose={() => setCreating(false)} onSaved={(so) => { setCreating(false); setOpenId(so.id); }} />}
    </Page>
  );
}

function OrderModal({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const { can } = useAuth();
  const canEdit = can("sales", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<"deliver" | "return" | "invoice" | "close" | null>(null);
  const q = useQuery({ queryKey: ["sales-order", id], queryFn: () => api.get<SalesOrder>(`/sales-orders/${id}`) });
  const so = q.data;
  const act = useMutation({
    mutationFn: (status: string) => api.post<SalesOrder>(`/sales-orders/${id}/status`, { status }),
    onSuccess: (r) => { toast(`${r.no}: ${r.status_label}`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const copy = useMutation({
    mutationFn: () => api.post<SalesOrder>(`/sales-orders/${id}/copy`),
    onSuccess: (r) => { toast(tx("{0} kopya olarak oluşturuldu", r.no)); refresh(); onOpen(r.id); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/sales-orders/${id}`),
    onSuccess: () => { toast(tx("Silindi")); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  if (editing && so) return <OrderEditor order={so} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  if (dialog === "invoice" && so) return <InvoiceDialog order={so} onClose={() => setDialog(null)} />;
  if (dialog === "close" && so) return <CloseDialog order={so} onClose={() => setDialog(null)} />;
  if (dialog && so) return <DeliverDialog order={so} back={dialog === "return"} onClose={() => setDialog(null)} />;
  const busy = act.isPending || del.isPending || copy.isPending;
  const lines = so?.lines ?? [];
  const shipping = so && ["confirmed", "partial"].includes(so.status);
  const shipped = lines.some((l) => (l.delivered_qty ?? 0) > 0);
  const quoteDoc = so && ["draft", "quoted", "lost"].includes(so.status);
  return (
    <Modal wide title={so ? `${quoteDoc ? tx("Teklif") : tx("Sipariş")} ${so.no}` : tx("Satış")} onClose={onClose}
      footer={so && <>
        <button className="btn" onClick={() => void download(`/sales-orders/${id}/xlsx`, `${so.no}.xlsx`).catch((e) => toast(errText(e), true))}>
          {quoteDoc ? tx("Teklif formu (Excel)") : tx("Sipariş onayı (Excel)")}
        </button>
        {canEdit && <button className="btn" disabled={busy} onClick={() => copy.mutate()}>{tx("Kopyala")}</button>}
        <span style={{ flex: 1 }} />
        {canEdit && so.status === "draft" && <button className="btn danger" disabled={busy} onClick={() => confirm(tx("{0} silinsin mi?", so.no)) && del.mutate()}>{tx("Sil")}</button>}
        {canEdit && !["delivered", "cancelled", "closed"].includes(so.status) && <button className="btn" onClick={() => setEditing(true)}>{tx("Düzenle")}</button>}
        {canEdit && so.next_statuses.map((s) => (
          <button key={s} className={s === "cancelled" || s === "lost" ? "btn danger" : s === "draft" ? "btn" : "btn primary"} disabled={busy}
            onClick={() => (s !== "cancelled" || confirm(tx("{0} iptal edilsin mi?", so.no))) && act.mutate(s)}>{SO_ACTIONS[s] ?? s}</button>
        ))}
        {canEdit && shipped && <button className="btn" disabled={busy} onClick={() => setDialog("return")}>{tx("İade al")}</button>}
        {canEdit && so.status === "partial" && <button className="btn" disabled={busy} onClick={() => setDialog("close")}>{tx("Eksik kapat")}</button>}
        {canEdit && shipping && <button className="btn primary" disabled={busy} onClick={() => setDialog("deliver")}>{tx("Sevk et")}</button>}
        {can("finance", "edit") && ["confirmed", "partial", "delivered", "closed"].includes(so.status) && lines.some((l) => (l.billable ?? 0) > 0) && (
          <button className="btn primary" disabled={busy} onClick={() => setDialog("invoice")}>{tx("Fatura oluştur")}</button>
        )}
      </>}>
      <Loading error={q.error} loading={q.isLoading} />
      {so && (
        <>
          <div className="erp-head">
            <div><span className="muted">{tx("Durum")}</span><span className="badge" style={statusStyle(SO_COLORS[so.status])}>{so.status_label}</span></div>
            <div><span className="muted">{tx("Müşteri")}</span><b>{so.firm_name}</b></div>
            <div><span className="muted">{tx("Proje")}</span>{so.project_name ?? "—"}</div>
            <div><span className="muted">{tx("Tarih")}</span>{fmtDay(so.order_date) || "—"}</div>
            <div><span className="muted">{tx("Teklif geçerlilik")}</span><span className={so.expired ? "warn" : undefined}>{fmtDay(so.valid_until) || "—"}</span></div>
            <div><span className="muted">{tx("Teslim tarihi")}</span><span className={so.late ? "error" : undefined}>{fmtDay(so.due_date) || "—"}</span></div>
            <div><span className="muted">{tx("Faturalanan")}</span>{fmtMoney(so.invoiced, so.currency)}</div>
            {so.base_total !== so.total && (
              <div><span className="muted">{tx("Kur")}</span>{so.rate == null ? <span className="badge warn">{tx("kur yok")}</span> : `${fmtRate(so.rate)} · ${fmtMoney(so.base_total)}`}</div>
            )}
            <div><span className="muted">{tx("Oluşturan")}</span>{so.created_by}</div>
          </div>
          {so.note && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{so.note}</p>}
          <LinesTable lines={lines} currency={so.currency} subtotal={so.subtotal} discount={so.discount}
            discountPct={so.discount_pct} tax={so.tax} taxRate={so.tax_rate} total={so.total}
            progress={["confirmed", "partial", "delivered", "closed"].includes(so.status)} />
          {shipping && <p className="muted">{tx("Onaylı siparişin fiyatları değişmez. Değişiklik için iptal edip kopyasını açın.")}</p>}
          <MoveHistory title={tx("Sevk ve iadeler")} backLabel="iade" rows={(so.deliveries ?? []).map((d) => ({ ...d, at: d.delivered_at }))} />
        </>
      )}
    </Modal>
  );
}

function CloseDialog({ order, onClose }: { order: SalesOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<SalesOrder>(`/sales-orders/${order.id}/close`, { note }),
    onSuccess: (r) => { toast(`${r.no}: ${r.status_label}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const left = (order.lines ?? []).filter((l) => (l.remaining ?? 0) > 0);
  return (
    <Modal title={tx("Eksik kapat: {0}", order.no)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("Siparişi kapat")}</button>
      </>}>
      <p className="muted">{tx("Sevk edilenler kalır, kalan miktar sevk edilmeyecek. Fatura yalnızca sevk edilen miktara kadar kesilebilir, iade almak yine mümkündür.")}</p>
      <ul>{left.map((l) => <li key={l.id}>{l.code || l.description}{tx(": {0} {1} sevk edilmeyecek", fmtQty(l.remaining), l.unit)}</li>)}</ul>
      <Field label={tx("Not")}><input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}

function DeliverDialog({ order, back, onClose }: { order: SalesOrder; back: boolean; onClose: () => void }) {
  const canBill = useAuth().can("finance", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [credit, setCredit] = useState(canBill);
  const save = useMutation({
    mutationFn: (body: { lines: { line_id: number; qty: number }[]; note: string; credit_note?: boolean }) =>
      api.post<SalesOrder & { credits?: { no: string }[] }>(`/sales-orders/${order.id}/${back ? "return" : "deliver"}`, body),
    onSuccess: (r) => {
      const made = (r.credits ?? []).map((c) => c.no).join(", ");
      toast(made ? tx("{0}: {1}. Taslak alacak dekontu: {2}", r.no, r.status_label, made) : `${r.no}: ${r.status_label}`);
      refresh();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const open = (order.lines ?? []).filter((l) => (back ? (l.delivered_qty ?? 0) > 0 : (l.remaining ?? 0) > 0));
  return (
    <QtyModal title={`${back ? tx("Müşteriden iade") : tx("Sevk")}: ${order.no}`} qtyLabel={back ? tx("İade") : tx("Bu sevk")} submit={back ? tx("İade al") : tx("Sevk et")}
      intro={back
        ? tx("Stoktan çıkmış mal stoğa geri girer. Faturalanmış miktar için aşağıdan taslak alacak dekontu oluşturabilirsiniz.")
        : tx("Stok kartı olan kod stoktan düşer. Projeye verilmiş mal için yeniden stok düşülmez.")}
      noteLabel={tx("Not (irsaliye no vb.)")} heads={[tx("Sipariş"), tx("Teslim"), tx("Kalan")]} busy={save.isPending}
      rows={open.map((l) => ({
        id: l.id!, code: l.code, description: l.description, unit: l.unit,
        cells: [`${fmtQty(l.qty)} ${tx(l.unit)}`, fmtQty(l.delivered_qty), fmtQty(l.remaining)],
        start: back ? 0 : l.remaining ?? 0, max: back ? l.delivered_qty : l.remaining,
      }))}
      onSubmit={(lines, note) => save.mutate(back ? { lines, note, credit_note: credit } : { lines, note })} onClose={onClose}>
      {back && canBill && (
        <label className="row" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={credit} onChange={(e) => setCredit(e.target.checked)} />
          {tx("Faturalanmış miktar için alacak dekontu oluştur (taslak olarak, Fatura ve ödeme ekranından kesilir)")}
        </label>
      )}
    </QtyModal>
  );
}

function InvoiceDialog({ order, onClose }: { order: SalesOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const save = useMutation({
    mutationFn: (lines: { line_id: number; qty: number }[]) => api.post<{ no: string }>(`/sales-orders/${order.id}/invoice`, { lines }),
    onSuccess: (r) => { toast(tx("Taslak fatura {0} oluşturuldu. Fatura ve ödeme ekranından kesebilirsiniz.", r.no)); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <QtyModal title={tx("Fatura: {0}", order.no)} qtyLabel={tx("Faturalanacak")} submit={tx("Taslak fatura oluştur")} noteLabel={null} busy={save.isPending}
      intro={tx("Teslim edilip faturalanmamış miktar hazır gelir. Sipariş miktarına kadar değiştirebilirsiniz.")}
      heads={[tx("Sipariş"), tx("Teslim"), tx("Faturalanan")]}
      rows={(order.lines ?? []).filter((l) => (l.billable ?? 0) > 0).map((l) => ({
        id: l.id!, code: l.code, description: l.description, unit: l.unit,
        cells: [`${fmtQty(l.qty)} ${tx(l.unit)}`, fmtQty(l.delivered_qty), fmtQty(l.billed_qty)], start: l.to_bill ?? 0, max: l.billable,
      }))}
      onSubmit={(lines) => save.mutate(lines)} onClose={onClose} />
  );
}

function OrderEditor({ order, onClose, onSaved }: { order?: SalesOrder; onClose: () => void; onSaved: (so: SalesOrder) => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const customers = useFirms("customer");
  const pricesLocked = order?.status === "confirmed" || order?.status === "partial";
  const [currency, setCurrency] = useState(order?.currency ?? sys.currency);
  const [rate, setRate] = useState(order?.rate != null ? String(order.rate) : "");
  const [firmId, setFirmId] = useState<number | null>(order?.firm_id ?? null);
  const [firmName, setFirmName] = useState(order && !order.firm_id ? order.firm_name : "");
  const [project, setProject] = useState<number | null>(order?.project_id ?? null);
  const [validUntil, setValidUntil] = useState(order?.valid_until ?? addDays(sys.quote_days));
  const [due, setDue] = useState(order?.due_date ?? "");
  const [tax, setTax] = useState(String(order?.tax_rate ?? sys.vat));
  const [disc, setDisc] = useState(String(order?.discount_pct ?? 0));
  const [note, setNote] = useState(order?.note ?? "");
  const [lines, setLines] = useState<DocLine[]>(() => order?.lines?.map((l) => ({ ...l })) ?? [emptyLine()]);
  const [prices, setPrices] = useState<string[]>(() => lines.map((l) => (l.unit_price == null ? "" : String(l.unit_price))));
  const d = numOrNull(disc) ?? 0;
  const { total } = formTotals(lines, prices, numOrNull(tax) ?? 0, d);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { firm_id: firmId, firm_name: firmName, project_id: project,
        valid_until: validUntil || null, due_date: due || null, note };
      if (!pricesLocked) Object.assign(body, { currency, rate: numOrNull(rate), tax_rate: numOrNull(tax) ?? 0, discount_pct: d, lines: linesBody(lines, prices) });
      return order ? saveRev(order.rev, (rev) => api.put<SalesOrder>(`/sales-orders/${order.id}`, { ...body, rev })) : api.post<SalesOrder>("/sales-orders", body);
    },
    onSuccess: (so) => { toast(order ? tx("Kaydedildi") : tx("{0} oluşturuldu", so.no)); refresh(); onSaved(so); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal wide title={order ? tx("Düzenle: {0}", order.no) : tx("Yeni teklif")} onClose={onClose}
      footer={<>
        {!pricesLocked && <span className="muted" style={{ marginRight: "auto" }}>{tx("Genel toplam (KDV dahil):")}{" "}<b>{fmtMoney(total, currency)}</b></span>}
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending || (!firmId && !firmName.trim())} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form two">
        <Field label={tx("Müşteri")} hint={customers.data && !customers.data.length ? tx("Henüz müşteri kartı yok: Cari kartlar ekranından “Müşteri” türünde ekleyin veya aşağıya adını yazın.") : undefined}>
          <FirmSelect kind="customer" value={firmId} onChange={setFirmId} emptyLabel={tx("(Kartı olmayan müşteri)")} />
        </Field>
        {!firmId ? (
          <Field label={tx("Müşteri adı (kartsız)")}><input value={firmName} onChange={(e) => setFirmName(e.target.value)} /></Field>
        ) : <span />}
        <Field label={tx("Proje")}><ProjectSelect value={project} onChange={setProject} /></Field>
        <Field label={tx("Teklif geçerlilik")}><input type="date" value={validUntil ?? ""} onChange={(e) => setValidUntil(e.target.value)} /></Field>
        <Field label={tx("Teslim tarihi")}><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        <div className="row" style={{ gap: 12 }}>
          <Field label={tx("KDV %")}><input style={{ width: 80 }} inputMode="decimal" disabled={pricesLocked} value={tax} onChange={(e) => setTax(e.target.value)} /></Field>
          <Field label={tx("İskonto %")}><input style={{ width: 80 }} inputMode="decimal" disabled={pricesLocked} value={disc} onChange={(e) => setDisc(e.target.value)} /></Field>
        </div>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={order?.order_date} locked={pricesLocked} />
        <Field label={tx("Not (teklif şartları, ödeme koşulu)")}><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      {pricesLocked
        ? <p className="muted">{tx("Onaylı siparişin satırları ve fiyatları değişmez.")}</p>
        : <LinesEditor lines={lines} setLines={setLines} prices={prices} setPrices={setPrices} currency={currency} />}
    </Modal>
  );
}
