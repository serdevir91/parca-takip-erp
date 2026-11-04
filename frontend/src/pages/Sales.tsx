import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { api, download } from "../api/client";
import { sys } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, PageHeader } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import { FirmSelect, ProjectSelect, addDays, fmtDay, fmtMoney, numOrNull, trIncludes, useFirms } from "./erp/common";
import {
  LinesEditor, LinesTable, SO_ACTIONS, SO_COLORS, Stat, emptyLine, lineSum, linesBody, type DocLine, type SalesOrder,
} from "./erp/commerce";

type ListResp = { rows: SalesOrder[]; statuses: Record<string, string> };

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["sales-orders", "sales-order", "invoices", "balances", "overview"]) void qc.invalidateQueries({ queryKey: [k] });
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
  const sum = (f: (r: SalesOrder) => boolean) => rows.filter(f).reduce((s, r) => s + r.total, 0);

  return (
    <Page>
      <PageHeader icon={TrendingUp} title="Satış ve teklif" sub="Müşteri teklifleri, satış siparişleri ve faturaya dönüştürme">
        {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>+ Yeni teklif</button>}
      </PageHeader>
      <div className="grid stats">
        <Stat label="Açık teklifler" value={rows.filter((r) => r.status === "draft" || r.status === "quoted").length}
          sub={fmtMoney(sum((r) => r.status === "draft" || r.status === "quoted"))} />
        <Stat label="Onaylı siparişler" value={rows.filter((r) => r.status === "confirmed").length}
          sub={fmtMoney(sum((r) => r.status === "confirmed"))} />
        <Stat label="Teslimi geciken" value={rows.filter((r) => r.late).length} tone={rows.some((r) => r.late) ? "error" : undefined} />
        <Stat label="Süresi dolan teklif" value={rows.filter((r) => r.expired).length} tone={rows.some((r) => r.expired) ? "warn" : undefined} />
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Durum">
            <option value="open">Açık (taslak, teklif, onaylı)</option>
            <option value="">Tümü</option>
            {Object.entries(list.data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input placeholder="Ara (no, müşteri, proje)…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{rows.length.toLocaleString("tr-TR")} kayıt · {fmtMoney(sum(() => true))}</span>
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr><th>No</th><th>Müşteri</th><th>Proje</th><th>Durum</th><th>Tarih</th><th>Geçerlilik</th><th>Teslim</th>
                  <th className="num">Tutar (KDV dahil)</th><th className="num">Faturalanan</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => setOpenId(r.id)}>
                    <td><b>{r.no}</b></td>
                    <td>{r.firm_name}</td>
                    <td>{r.project_name ?? <span className="muted">—</span>}</td>
                    <td><span className="badge" style={statusStyle(SO_COLORS[r.status])}>{r.status_label}</span></td>
                    <td>{fmtDay(r.order_date)}</td>
                    <td className={r.expired ? "warn" : undefined}>{fmtDay(r.valid_until)}{r.expired ? " (doldu)" : ""}</td>
                    <td className={r.late ? "error" : undefined}>{fmtDay(r.due_date)}{r.late ? " (gecikti)" : ""}</td>
                    <td className="num">{fmtMoney(r.total, r.currency)}</td>
                    <td className="num">{r.invoiced ? fmtMoney(r.invoiced, r.currency) : <span className="muted">—</span>}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={9} className="muted empty">Kayıt yok. “Yeni teklif” ile başlayın.</td></tr>}
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
  const q = useQuery({ queryKey: ["sales-order", id], queryFn: () => api.get<SalesOrder>(`/sales-orders/${id}`) });
  const so = q.data;
  const act = useMutation({
    mutationFn: (status: string) => api.post<SalesOrder>(`/sales-orders/${id}/status`, { status }),
    onSuccess: (r) => { toast(`${r.no}: ${r.status_label}`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const invoice = useMutation({
    mutationFn: () => api.post<{ no: string }>(`/sales-orders/${id}/invoice`),
    onSuccess: (r) => { toast(`Taslak fatura ${r.no} oluşturuldu. Fatura ve ödeme ekranından kesebilirsiniz.`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const copy = useMutation({
    mutationFn: () => api.post<SalesOrder>(`/sales-orders/${id}/copy`),
    onSuccess: (r) => { toast(`${r.no} kopya olarak oluşturuldu`); refresh(); onOpen(r.id); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/sales-orders/${id}`),
    onSuccess: () => { toast("Silindi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  if (editing && so) return <OrderEditor order={so} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  const busy = act.isPending || invoice.isPending || del.isPending || copy.isPending;
  const quoteDoc = so && ["draft", "quoted", "lost"].includes(so.status);
  return (
    <Modal wide title={so ? `${quoteDoc ? "Teklif" : "Sipariş"} ${so.no}` : "Satış"} onClose={onClose}
      footer={so && <>
        <button className="btn" onClick={() => void download(`/sales-orders/${id}/xlsx`, `${so.no}.xlsx`).catch((e) => toast(errText(e), true))}>
          {quoteDoc ? "Teklif formu (Excel)" : "Sipariş onayı (Excel)"}
        </button>
        {canEdit && <button className="btn" disabled={busy} onClick={() => copy.mutate()}>Kopyala</button>}
        <span style={{ flex: 1 }} />
        {canEdit && so.status === "draft" && <button className="btn danger" disabled={busy} onClick={() => confirm(`${so.no} silinsin mi?`) && del.mutate()}>Sil</button>}
        {canEdit && !["delivered", "cancelled"].includes(so.status) && <button className="btn" onClick={() => setEditing(true)}>Düzenle</button>}
        {canEdit && so.next_statuses.map((s) => (
          <button key={s} className={s === "cancelled" || s === "lost" ? "btn danger" : s === "draft" ? "btn" : "btn primary"} disabled={busy}
            onClick={() => (s !== "cancelled" || confirm(`${so.no} iptal edilsin mi?`)) && act.mutate(s)}>{SO_ACTIONS[s] ?? s}</button>
        ))}
        {can("finance", "edit") && ["confirmed", "delivered"].includes(so.status) && (
          <button className="btn primary" disabled={busy} onClick={() => invoice.mutate()}>Fatura oluştur</button>
        )}
      </>}>
      <Loading error={q.error} loading={q.isLoading} />
      {so && (
        <>
          <div className="erp-head">
            <div><span className="muted">Durum</span><span className="badge" style={statusStyle(SO_COLORS[so.status])}>{so.status_label}</span></div>
            <div><span className="muted">Müşteri</span><b>{so.firm_name}</b></div>
            <div><span className="muted">Proje</span>{so.project_name ?? "—"}</div>
            <div><span className="muted">Tarih</span>{fmtDay(so.order_date) || "—"}</div>
            <div><span className="muted">Teklif geçerlilik</span><span className={so.expired ? "warn" : undefined}>{fmtDay(so.valid_until) || "—"}</span></div>
            <div><span className="muted">Teslim tarihi</span><span className={so.late ? "error" : undefined}>{fmtDay(so.due_date) || "—"}</span></div>
            <div><span className="muted">Faturalanan</span>{fmtMoney(so.invoiced, so.currency)}</div>
            <div><span className="muted">Oluşturan</span>{so.created_by}</div>
          </div>
          {so.note && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{so.note}</p>}
          <LinesTable lines={so.lines ?? []} currency={so.currency} subtotal={so.subtotal} discount={so.discount}
            discountPct={so.discount_pct} tax={so.tax} taxRate={so.tax_rate} total={so.total} />
          {so.status === "confirmed" && <p className="muted">Onaylı siparişin fiyatları değişmez. Değişiklik için iptal edip kopyasını açın.</p>}
        </>
      )}
    </Modal>
  );
}

function OrderEditor({ order, onClose, onSaved }: { order?: SalesOrder; onClose: () => void; onSaved: (so: SalesOrder) => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const customers = useFirms("customer");
  const pricesLocked = order?.status === "confirmed";
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
  const sub = lineSum(lines, prices);
  const d = numOrNull(disc) ?? 0;
  const total = sub * (1 - d / 100) * (1 + (numOrNull(tax) ?? 0) / 100);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { firm_id: firmId, firm_name: firmName, project_id: project,
        valid_until: validUntil || null, due_date: due || null, note };
      if (!pricesLocked) Object.assign(body, { tax_rate: numOrNull(tax) ?? 0, discount_pct: d, lines: linesBody(lines, prices) });
      return order ? api.put<SalesOrder>(`/sales-orders/${order.id}`, body) : api.post<SalesOrder>("/sales-orders", body);
    },
    onSuccess: (so) => { toast(order ? "Kaydedildi" : `${so.no} oluşturuldu`); refresh(); onSaved(so); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal wide title={order ? `Düzenle: ${order.no}` : "Yeni teklif"} onClose={onClose}
      footer={<>
        {!pricesLocked && <span className="muted" style={{ marginRight: "auto" }}>Genel toplam (KDV dahil): <b>{fmtMoney(total)}</b></span>}
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || (!firmId && !firmName.trim())} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form two">
        <Field label="Müşteri" hint={customers.data && !customers.data.length ? "Henüz müşteri kartı yok: Cari kartlar ekranından “Müşteri” türünde ekleyin veya aşağıya adını yazın." : undefined}>
          <FirmSelect kind="customer" value={firmId} onChange={setFirmId} emptyLabel="(Kartı olmayan müşteri)" />
        </Field>
        {!firmId ? (
          <Field label="Müşteri adı (kartsız)"><input value={firmName} onChange={(e) => setFirmName(e.target.value)} /></Field>
        ) : <span />}
        <Field label="Proje"><ProjectSelect value={project} onChange={setProject} /></Field>
        <Field label="Teklif geçerlilik"><input type="date" value={validUntil ?? ""} onChange={(e) => setValidUntil(e.target.value)} /></Field>
        <Field label="Teslim tarihi"><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        <div className="row" style={{ gap: 12 }}>
          <Field label="KDV %"><input style={{ width: 80 }} inputMode="decimal" disabled={pricesLocked} value={tax} onChange={(e) => setTax(e.target.value)} /></Field>
          <Field label="İskonto %"><input style={{ width: 80 }} inputMode="decimal" disabled={pricesLocked} value={disc} onChange={(e) => setDisc(e.target.value)} /></Field>
        </div>
        <Field label="Not (teklif şartları, ödeme koşulu)"><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      {pricesLocked
        ? <p className="muted">Onaylı siparişin satırları ve fiyatları değişmez.</p>
        : <LinesEditor lines={lines} setLines={setLines} prices={prices} setPrices={setPrices} />}
    </Modal>
  );
}
