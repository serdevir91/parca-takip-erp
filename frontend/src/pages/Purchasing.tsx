import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, download } from "../api/client";
import { sys } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import {
  CurrencyRate, FirmSelect, ITEM_KINDS, MoveHistory, PO_COLORS, ProjectSelect, QtyModal, fmtDay, fmtMoney, fmtQty, fmtRate, numOrNull, trIncludes,
  type PoLine, type PurchaseOrder,
} from "./erp/common";
import { Suppliers } from "./erp/suppliers";

type ListResp = { rows: PurchaseOrder[]; statuses: Record<string, string>; base: string };

/** Satın alma siparişleri: all projects at /purchasing, one project at /p/:pid/purchasing. */
export default function Purchasing() {
  const { pid, project } = useProject();
  const canEdit = useAuth().can("purchasing", "edit");
  const [status, setStatus] = useState("open");
  const [projectFilter, setProjectFilter] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"orders" | "suppliers">("orders");

  const projectId = pid || projectFilter;
  const list = useQuery({
    queryKey: ["purchase-orders", projectId ?? 0, status],
    queryFn: () => {
      const p = new URLSearchParams();
      if (projectId) p.set("project_id", String(projectId));
      if (status) p.set("status", status);
      return api.get<ListResp>(`/purchase-orders?${p}`);
    },
  });
  const rows = useMemo(
    () => (list.data?.rows ?? []).filter((r) => !q.trim() || trIncludes(`${r.no} ${r.firm_name} ${r.project_name ?? ""} ${r.note}`, q)),
    [list.data, q],
  );
  const total = rows.reduce((s, r) => s + (r.base_total ?? 0), 0);
  const noRate = rows.filter((r) => r.base_total == null).length;

  return (
    <Page>
      {!pid && (
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "orders"} className={tab === "orders" ? "active" : ""} onClick={() => setTab("orders")}>Siparişler</button>
          <button role="tab" aria-selected={tab === "suppliers"} className={tab === "suppliers" ? "active" : ""} onClick={() => setTab("suppliers")}>Tedarikçiler</button>
        </div>
      )}
      {tab === "suppliers" ? <Suppliers /> : <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, marginRight: 8 }}>Satın Alma Siparişleri{project ? ` · ${project.name}` : ""}</h2>
          {canEdit && <button className="btn primary" onClick={() => setCreating(true)}>+ Yeni sipariş</button>}
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Durum">
            <option value="open">Açık siparişler</option>
            <option value="">Tümü</option>
            {Object.entries(list.data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {!pid && <ProjectSelect value={projectFilter} onChange={setProjectFilter} emptyLabel="Tüm projeler" />}
          <input placeholder="Ara (no, firma, not)…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{rows.length.toLocaleString("tr-TR")} sipariş · {fmtMoney(total)}</span>
          {noRate > 0 && <span className="badge warn" title="Kuru bilinmediği için toplama katılmadı">{noRate} belgede kur yok</span>}
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr>
                  <th>Sipariş no</th><th>Firma</th>{!pid && <th>Proje</th>}<th>Durum</th><th>Sipariş tarihi</th>
                  <th>Termin</th><th className="num">Satır</th><th className="num">Tutar</th><th className="num">Teslim</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => setOpenId(r.id)}>
                    <td><b>{r.no}</b></td>
                    <td>{r.firm_name || <span className="muted">(firma yok)</span>}</td>
                    {!pid && <td>{r.project_name ?? <span className="muted">Stok</span>}</td>}
                    <td><span className="badge" style={statusStyle(PO_COLORS[r.status])}>{r.status_label}</span></td>
                    <td>{fmtDay(r.order_date)}</td>
                    <td className={r.overdue ? "error" : undefined}>{fmtDay(r.due_date)}{r.overdue ? " (gecikti)" : ""}</td>
                    <td className="num">{r.line_count}</td>
                    <td className="num">
                      {fmtMoney(r.total, r.currency)}
                      {r.missing_price > 0 && <span className="badge warn" title="Fiyatı girilmemiş satır" style={{ marginLeft: 4 }}>{r.missing_price}</span>}
                    </td>
                    <td className="num">%{r.received_pct.toLocaleString("tr-TR")}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={9} className="muted">Sipariş yok.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>}
      {openId !== null && <OrderModal id={openId} onClose={() => setOpenId(null)} />}
      {creating && (
        <OrderEditor projectId={pid || null} onClose={() => setCreating(false)} onSaved={(po) => { setCreating(false); setOpenId(po.id); }} />
      )}
    </Page>
  );
}

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
    void qc.invalidateQueries({ queryKey: ["purchase-order"] });
    void qc.invalidateQueries({ queryKey: ["requirements"] });
    void qc.invalidateQueries({ queryKey: ["costs"] });
    void qc.invalidateQueries({ queryKey: ["stock"] });
    void qc.invalidateQueries({ queryKey: ["parts"] });
    void qc.invalidateQueries({ queryKey: ["fasteners"] });
    void qc.invalidateQueries({ queryKey: ["invoices"] });
    void qc.invalidateQueries({ queryKey: ["suppliers"] });
  };
}

export function OrderModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { can } = useAuth();
  const canEdit = can("purchasing", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<"receive" | "reverse" | "close" | "invoice" | null>(null);
  const q = useQuery({ queryKey: ["purchase-order", id], queryFn: () => api.get<PurchaseOrder>(`/purchase-orders/${id}`) });
  const po = q.data;

  const setStatus = useMutation({
    mutationFn: (status: string) => api.post<PurchaseOrder>(`/purchase-orders/${id}/status`, { status }),
    onSuccess: (r) => { toast(`${r.no}: ${r.status_label}`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/purchase-orders/${id}`),
    onSuccess: () => { toast("Sipariş silindi"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });

  if (editing && po) return <OrderEditor order={po} projectId={po.project_id} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  const closeDialog = () => setDialog(null);
  if (dialog === "receive" && po) return <ReceiveModal order={po} onClose={closeDialog} />;
  if (dialog === "reverse" && po) return <ReverseModal order={po} onClose={closeDialog} />;
  if (dialog === "close" && po) return <CloseModal order={po} onClose={closeDialog} />;
  if (dialog === "invoice" && po) return <InvoiceModal order={po} onClose={closeDialog} />;

  const busy = setStatus.isPending || del.isPending;
  const s = po?.status;
  const lines = po?.lines ?? [];
  const received = lines.some((l) => (l.received_qty ?? 0) > 0);
  return (
    <Modal wide title={po ? `Sipariş ${po.no}` : "Sipariş"} onClose={onClose}
      footer={po && <>
        <button className="btn" onClick={() => void download(`/purchase-orders/${id}/xlsx`, `${po.no}.xlsx`).catch((e) => toast(errText(e), true))}>
          Sipariş formu (Excel)
        </button>
        {can("finance", "edit") && s && ["sent", "partial", "received", "closed"].includes(s) && lines.some((l) => (l.billable ?? 0) > 0) && (
          <button className="btn" onClick={() => setDialog("invoice")}>Alış faturası gir</button>
        )}
        <span style={{ flex: 1 }} />
        {canEdit && s === "draft" && <>
          <button className="btn danger" disabled={busy} onClick={() => confirm(`${po.no} silinsin mi?`) && del.mutate()}>Sil</button>
          <button className="btn" onClick={() => setEditing(true)}>Düzenle</button>
          <button className="btn primary" disabled={busy || !po.lines?.length} onClick={() => setStatus.mutate("sent")}>Gönderildi olarak işaretle</button>
        </>}
        {canEdit && received && <button className="btn" onClick={() => setDialog("reverse")}>Geri al / iade</button>}
        {canEdit && (s === "sent" || s === "partial") && <>
          {s === "sent" && <button className="btn danger" disabled={busy} onClick={() => confirm(`${po.no} iptal edilsin mi?`) && setStatus.mutate("cancelled")}>İptal et</button>}
          {s === "sent" && <button className="btn" disabled={busy} onClick={() => setStatus.mutate("draft")}>Taslağa al</button>}
          {s === "partial" && <button className="btn" onClick={() => setDialog("close")}>Eksik kapat</button>}
          <button className="btn" onClick={() => setEditing(true)}>Başlığı düzenle</button>
          <button className="btn primary" onClick={() => setDialog("receive")}>Mal kabul</button>
        </>}
      </>}>
      <Loading error={q.error} loading={q.isLoading} />
      {po && (
        <>
          <div className="erp-head">
            <div><span className="muted">Durum</span><span className="badge" style={statusStyle(PO_COLORS[po.status])}>{po.status_label}</span></div>
            <div><span className="muted">Firma</span><b>{po.firm_name || "—"}</b></div>
            <div><span className="muted">Proje</span>{po.project_name ?? "Stok (projesiz)"}</div>
            <div><span className="muted">Sipariş tarihi</span>{fmtDay(po.order_date) || "—"}</div>
            <div><span className="muted">Termin</span><span className={po.overdue ? "error" : undefined}>{fmtDay(po.due_date) || "—"}</span></div>
            <div><span className="muted">Oluşturan</span>{po.created_by}</div>
            {po.base_total !== po.total && (
              <div><span className="muted">Kur</span>{po.rate == null ? <span className="badge warn">kur yok</span> : `${fmtRate(po.rate)} · ${fmtMoney(po.base_total)}`}</div>
            )}
          </div>
          {po.note && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{po.note}</p>}
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead><tr><th>#</th><th>Kod</th><th>Tür</th><th>Açıklama</th><th className="num">Sipariş</th><th className="num">Teslim</th><th className="num">Faturalanan</th><th className="num">Kalan</th><th className="num">Birim fiyat</th><th className="num">Tutar</th></tr></thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.id}>
                    <td>{l.seq}</td><td className="mono">{l.code}</td><td>{l.kind_label}</td><td>{l.description}</td>
                    <td className="num">{fmtQty(l.qty)} {l.unit}</td><td className="num">{fmtQty(l.received_qty)}</td>
                    <td className="num">{fmtQty(l.billed_qty)}</td>
                    <td className="num">{!l.remaining ? "✓" : s === "closed" ? <span className="muted" title="Sipariş eksik kapatıldı, gelmeyecek">{fmtQty(l.remaining)} kapatıldı</span> : <b>{fmtQty(l.remaining)}</b>}</td>
                    <td className="num">{l.unit_price == null ? <span className="badge warn">fiyat yok</span> : fmtMoney(l.unit_price, po.currency)}</td>
                    <td className="num">{fmtMoney(l.amount, po.currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td colSpan={9} className="num"><b>Toplam</b></td><td className="num"><b>{fmtMoney(po.total, po.currency)}</b></td></tr></tfoot>
            </table>
          </div>
          {po.project_id && (s === "draft") && (
            <p className="muted">Gönderildiğinde projedeki parçalar "Sipariş Verildi", mal kabulden sonra "Sipariş Teslim Edildi" olur.</p>
          )}
          <MoveHistory title="Mal kabul hareketleri" backLabel="geri alındı" rows={(po.receipts ?? []).map((r) => ({ ...r, at: r.received_at }))} />
        </>
      )}
    </Modal>
  );
}

const emptyLine = (): PoLine => ({ code: "", kind: "part", description: "", unit: sys.unit, qty: 1, unit_price: null });

function OrderEditor({ order, projectId, onClose, onSaved }: {
  order?: PurchaseOrder; projectId: number | null; onClose: () => void; onSaved: (po: PurchaseOrder) => void;
}) {
  const toast = useToast();
  const refresh = useRefresh();
  const draft = !order || order.status === "draft";
  const [firmId, setFirmId] = useState<number | null>(order?.firm_id ?? null);
  const [project, setProject] = useState<number | null>(order ? order.project_id : projectId);
  const [due, setDue] = useState(order?.due_date ?? "");
  const [note, setNote] = useState(order?.note ?? "");
  const [currency, setCurrency] = useState(order?.currency ?? sys.currency);
  const [rate, setRate] = useState(order?.rate != null ? String(order.rate) : "");
  const rateLocked = (order?.lines ?? []).some((l) => (l.received_qty ?? 0) > 0);
  const [lines, setLines] = useState<PoLine[]>(() => order?.lines?.map((l) => ({ ...l })) ?? [emptyLine()]);
  const [prices, setPrices] = useState<string[]>(() => lines.map((l) => (l.unit_price == null ? "" : String(l.unit_price))));

  const upd = (i: number, patch: Partial<PoLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const total = lines.reduce((s, l, i) => s + (numOrNull(prices[i] ?? "") ?? 0) * (l.qty || 0), 0);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { firm_id: firmId, due_date: due || null, note };
      if (!rateLocked) Object.assign(body, { currency, rate: numOrNull(rate) });
      if (draft) {
        body.project_id = project;
        body.lines = lines
          .map((l, i) => ({ code: l.code.trim(), kind: l.kind, description: l.description.trim(), unit: l.unit || "Adet",
            qty: l.qty, unit_price: numOrNull(prices[i] ?? "") }))
          .filter((l) => l.code || l.description);
      }
      return order ? api.put<PurchaseOrder>(`/purchase-orders/${order.id}`, body) : api.post<PurchaseOrder>("/purchase-orders", body);
    },
    onSuccess: (po) => { toast(order ? "Sipariş güncellendi" : `${po.no} oluşturuldu`); refresh(); onSaved(po); },
    onError: (e) => toast(errText(e), true),
  });

  return (
    <Modal wide title={order ? `Siparişi düzenle: ${order.no}` : "Yeni satın alma siparişi"} onClose={onClose}
      footer={<>
        {draft && <span className="muted" style={{ marginRight: "auto" }}>Toplam: <b>{fmtMoney(total, currency)}</b></span>}
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form two">
        <Field label="Tedarikçi"><FirmSelect kind="supplier" value={firmId} onChange={setFirmId} /></Field>
        <Field label="Proje" hint={draft ? "Boş bırakılırsa mallar stoğa girer." : "Proje yalnızca taslakta değişir."}>
          {draft ? <ProjectSelect value={project} onChange={setProject} emptyLabel="(Stok için, projesiz)" /> : <input disabled value={order?.project_name ?? "Stok"} />}
        </Field>
        <Field label="Termin"><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        <CurrencyRate currency={currency} setCurrency={setCurrency} rate={rate} setRate={setRate} day={order?.order_date} locked={rateLocked} />
        <Field label="Not"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      {draft ? (
        <div className="adm-scroll" style={{ marginTop: 12 }}>
          <table className="simple erp-table erp-lines">
            <thead><tr><th>Kod (parça no)</th><th>Tür</th><th>Açıklama</th><th>Birim</th><th>Miktar</th><th>Birim fiyat ({currency})</th><th className="num">Tutar</th><th></th></tr></thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td><input value={l.code} onChange={(e) => upd(i, { code: e.target.value })} /></td>
                  <td>
                    <select value={l.kind} onChange={(e) => upd(i, { kind: e.target.value })}>
                      {ITEM_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </select>
                  </td>
                  <td><input value={l.description} onChange={(e) => upd(i, { description: e.target.value })} /></td>
                  <td><input style={{ width: 60 }} value={l.unit} onChange={(e) => upd(i, { unit: e.target.value })} /></td>
                  <td><input style={{ width: 80 }} type="number" min={0} step="any" value={l.qty}
                    onChange={(e) => upd(i, { qty: Number(e.target.value) })} /></td>
                  <td><input style={{ width: 100 }} inputMode="decimal" value={prices[i] ?? ""}
                    onChange={(e) => setPrices((p) => { const n = [...p]; n[i] = e.target.value; return n; })} /></td>
                  <td className="num">{fmtMoney((numOrNull(prices[i] ?? "") ?? 0) * (l.qty || 0), currency)}</td>
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
          <button className="btn small" style={{ marginTop: 6 }} onClick={() => { setLines((ls) => [...ls, emptyLine()]); setPrices((p) => [...p, ""]); }}>+ Satır ekle</button>
        </div>
      ) : (
        <p className="muted">Gönderilmiş siparişin satırları değiştirilemez; yalnızca firma, termin ve not güncellenir.</p>
      )}
    </Modal>
  );
}

function ReceiveModal({ order, onClose }: { order: PurchaseOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const save = useMutation({
    mutationFn: (body: { lines: { line_id: number; qty: number }[]; note: string }) => api.post<PurchaseOrder>(`/purchase-orders/${order.id}/receive`, body),
    onSuccess: (po) => { toast(`${po.no}: ${po.status_label}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <QtyModal title={`Mal kabul: ${order.no}`} qtyLabel="Bu teslimat" submit="Teslim al" noteLabel="Not (irsaliye no vb.)" busy={save.isPending}
      intro={order.project_id
        ? `Teslim alınan miktar stoğa girer ve aynı anda "${order.project_name}" projesine çıkılır.`
        : "Teslim alınan miktar stoğa girer."}
      heads={["Sipariş", "Teslim alınan"]}
      rows={(order.lines ?? []).filter((l) => (l.remaining ?? 0) > 0).map((l) => ({
        id: l.id!, code: l.code, description: l.description, unit: l.unit,
        cells: [`${fmtQty(l.qty)} ${l.unit}`, fmtQty(l.received_qty)], start: l.remaining ?? 0,
      }))}
      onSubmit={(lines, note) => save.mutate({ lines, note })} onClose={onClose} />
  );
}

function ReverseModal({ order, onClose }: { order: PurchaseOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const save = useMutation({
    mutationFn: (body: { lines: { line_id: number; qty: number }[]; note: string }) => api.post<PurchaseOrder>(`/purchase-orders/${order.id}/reverse`, body),
    onSuccess: (po) => { toast(`${po.no}: ${po.status_label}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <QtyModal danger title={`Geri al / iade: ${order.no}`} qtyLabel="Geri alınacak" submit="Geri al" noteLabel="Neden (hatalı kabul, kusurlu mal vb.)" busy={save.isPending}
      intro={`Mal stoktan geldiği maliyetle çıkar${order.project_id ? ", önce projeden geri alınır" : ""}. Stokta kalmadıysa işlem yapılmaz. Kesilmiş alış faturası kendiliğinden düzelmez.`}
      heads={["Sipariş", "Teslim alınan"]}
      rows={(order.lines ?? []).filter((l) => (l.received_qty ?? 0) > 0).map((l) => ({
        id: l.id!, code: l.code, description: l.description, unit: l.unit,
        cells: [`${fmtQty(l.qty)} ${l.unit}`, fmtQty(l.received_qty)], start: 0, max: l.received_qty,
      }))}
      onSubmit={(lines, note) => save.mutate({ lines, note })} onClose={onClose} />
  );
}

function CloseModal({ order, onClose }: { order: PurchaseOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<PurchaseOrder>(`/purchase-orders/${order.id}/close`, { note }),
    onSuccess: (po) => { toast(`${po.no}: ${po.status_label}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  const left = (order.lines ?? []).filter((l) => (l.remaining ?? 0) > 0);
  return (
    <Modal title={`Eksik kapat: ${order.no}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Siparişi kapat</button>
      </>}>
      <p className="muted">Teslim alınanlar kalır, gelmeyen miktar serbest kalır ve yeniden sipariş edilebilir. Proje maliyetinde yalnızca teslim alınan değer sayılır.</p>
      <ul>{left.map((l) => <li key={l.id}>{l.code || l.description}: {fmtQty(l.remaining)} {l.unit} gelmeyecek</li>)}</ul>
      <Field label="Not"><input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}

function InvoiceModal({ order, onClose }: { order: PurchaseOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [no, setNo] = useState("");
  const save = useMutation({
    mutationFn: (lines: { line_id: number; qty: number }[]) => api.post<{ no: string }>(`/purchase-orders/${order.id}/invoice`, { no: no.trim(), lines }),
    onSuccess: (r) => { toast(`Alış faturası ${r.no} taslak olarak oluşturuldu (Fatura ve ödeme)`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <QtyModal title={`Alış faturası: ${order.no}`} qtyLabel="Faturalanacak" submit="Taslak fatura oluştur" noteLabel={null} busy={save.isPending} ready={!!no.trim()}
      intro="Teslim alınıp faturalanmamış miktar hazır gelir."
      heads={["Sipariş", "Teslim alınan", "Faturalanan"]}
      rows={(order.lines ?? []).filter((l) => (l.billable ?? 0) > 0).map((l) => ({
        id: l.id!, code: l.code, description: l.description, unit: l.unit,
        cells: [`${fmtQty(l.qty)} ${l.unit}`, fmtQty(l.received_qty), fmtQty(l.billed_qty)], start: l.to_bill ?? 0, max: l.billable,
      }))}
      onSubmit={(lines) => save.mutate(lines)} onClose={onClose}>
      <div style={{ marginTop: 10 }}><Field label="Tedarikçi fatura numarası"><input autoFocus maxLength={40} value={no} onChange={(e) => setNo(e.target.value)} /></Field></div>
    </QtyModal>
  );
}
