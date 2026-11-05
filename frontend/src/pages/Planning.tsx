import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import { FirmSelect, MakerInput, addDays, fmtMoney, fmtQty, useFirms, type PurchaseOrder, type WorkOrder } from "./erp/common";
import { LOCALE, tx } from "../api/i18n";

// ---------- types (backend/app/services/erp.py requirements / project_costs) ----------
type Need = {
  code: string; kind: "part" | "fastener"; part_name?: string; description: string; unit: string; required: number; procurement: string;
  status: string; status_color: string; progress: string | null; main_group: string; material: string;
  manufacturer: string; unit_price: number | null; done: boolean; hidden?: boolean; issued: number; on_order: number;
  in_production: number; stock: number; net_need: number; from_stock: number; shortage: number;
  action: "" | "stock" | "purchase" | "work_order"; unit_cost: number | null;
  purchase_orders: string[]; work_orders: string[];
};
type NeedResp = { rows: Need[]; summary: { items: number; shortage: number; from_stock: number; covered: number } };
type CostRow = { name: string; committed: number; actual: number };
type Costs = {
  currency: string; committed: number; actual: number; missing_price: number; fastener_estimate: number;
  unconverted: { currency: string; committed: number; actual: number; documents: string[] }[];
  by_source: CostRow[]; by_firm: CostRow[]; by_group: CostRow[];
};

const ACTION_LABEL: Record<Need["action"], string> = { "": "", stock: tx("Stoktan karşıla"), purchase: tx("Satın al"), work_order: tx("İş emri aç") };
type Quick = "all" | "short" | "stock" | "covered";
const QUICK: { key: Quick; label: string; test: (r: Need) => boolean }[] = [
  { key: "all", label: tx("Tümü"), test: () => true },
  { key: "short", label: tx("Eksikler"), test: (r) => r.shortage > 0 },
  { key: "stock", label: tx("Stoktan karşılanabilir"), test: (r) => r.from_stock > 0 },
  { key: "covered", label: tx("Karşılananlar"), test: (r) => r.net_need <= 0 },
];
const num: CSSProperties = { textAlign: "right" };

/** İhtiyaç analizi (MRP) and project cost for one project. */
export default function Planning() {
  const [tab, setTab] = useState<"need" | "cost">("need");
  const { can } = useAuth();
  const canCost = can("finance") || can("purchasing");
  return (
    <Page full>
      <div className="toolbar">
        <div className="tabs" role="tablist" style={{ margin: 0 }}>
          <button role="tab" aria-selected={tab === "need"} className={tab === "need" ? "active" : ""} onClick={() => setTab("need")}>{tx("İhtiyaç analizi")}</button>
          {canCost && <button role="tab" aria-selected={tab === "cost"} className={tab === "cost" ? "active" : ""} onClick={() => setTab("cost")}>{tx("Maliyet")}</button>}
        </div>
      </div>
      {tab === "need" ? <NeedTab /> : <CostTab />}
    </Page>
  );
}

function NeedTab() {
  const { pid } = useProject();
  const canEdit = useAuth().can("purchasing", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [quick, setQuick] = useState<Quick>("short");
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [dialog, setDialog] = useState<"po" | "wo" | null>(null);
  const q = useQuery({ queryKey: ["requirements", pid], queryFn: () => api.get<NeedResp>(`/projects/${pid}/requirements`), enabled: !!pid });

  const rows = useMemo(() => (q.data?.rows ?? []).filter(QUICK.find((x) => x.key === quick)!.test), [q.data, quick]);
  const selected = useMemo(() => rows.filter((r) => selection[r.code]), [rows, selection]);
  const refresh = () => {
    setSelection({});
    for (const k of ["requirements", "costs", "stock", "parts", "fasteners", "purchase-orders", "work-orders"]) void qc.invalidateQueries({ queryKey: [k] });
  };

  const issue = useMutation({
    mutationFn: () => api.post<{ issued: number }>(`/projects/${pid}/requirements/issue`,
      selected.filter((r) => r.from_stock > 0).map((r) => ({ code: r.code }))),
    onSuccess: (r) => { toast(tx("{0} kalem stoktan projeye verildi", r.issued)); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<Need>[]>(() => [
    { accessorKey: "code", header: tx("Kod"), size: 190, cellStyle: () => ({ fontFamily: "var(--mono, monospace)" }) },
    { accessorKey: "part_name", header: tx("Parça Adı"), size: 170 },
    { accessorKey: "description", header: tx("Açıklama"), size: 210 },
    { id: "kind", accessorFn: (r) => (r.kind === "fastener" ? tx("Bağlantı elemanı") : tx("Parça")), header: tx("Tür"), size: 120 },
    { accessorKey: "procurement", header: tx("Temin"), size: 95 },
    { accessorKey: "main_group", header: tx("Ana grup"), size: 140 },
    { accessorKey: "status", header: tx("Durum"), size: 150, cellStyle: (r) => statusStyle(r.status_color) },
    { accessorKey: "required", header: tx("Gerekli"), size: 75, cellStyle: () => ({ ...num, fontWeight: 600 }), cell: (c) => fmtQty(c.row.original.required) },
    { accessorKey: "issued", header: tx("Verilen"), size: 75, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.issued || null) },
    {
      accessorKey: "on_order", header: tx("Siparişte"), size: 80, cellStyle: () => num,
      cell: (c) => <span title={c.row.original.purchase_orders.join(", ")}>{fmtQty(c.row.original.on_order || null)}</span>,
    },
    {
      accessorKey: "in_production", header: tx("Üretimde"), size: 80, cellStyle: () => num,
      cell: (c) => <span title={c.row.original.work_orders.join(", ")}>{fmtQty(c.row.original.in_production || null)}</span>,
    },
    { accessorKey: "stock", header: tx("Serbest stok"), size: 85, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.stock || null) },
    { accessorKey: "net_need", header: tx("Net ihtiyaç"), size: 85, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.net_need || null) },
    { accessorKey: "from_stock", header: tx("Stoktan"), size: 75, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.from_stock || null) },
    {
      accessorKey: "shortage", header: tx("Eksik"), size: 75,
      cellStyle: (r) => ({ ...num, fontWeight: 700, color: r.shortage > 0 ? "var(--danger)" : undefined }),
      cell: (c) => fmtQty(c.row.original.shortage || null),
    },
    { id: "action", accessorFn: (r) => ACTION_LABEL[r.action], header: tx("Önerilen işlem"), size: 125 },
  ], []);

  const s = q.data?.summary;
  const canPo = selected.some((r) => r.shortage > 0);
  const canWo = selected.some((r) => r.shortage > 0 && r.kind === "part");
  const canIssue = selected.some((r) => r.from_stock > 0);
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="grid kpis erp-kpis">
        <Kpi label={tx("Kalem")} value={fmtQty(s?.items ?? 0)} sub={tx("Satın alınan / imal edilen parça ve bağlantı elemanı")} />
        <Kpi label={tx("Eksik")} value={fmtQty(s?.shortage ?? 0)} sub={tx("Sipariş veya iş emri gerekiyor")} tone={s?.shortage ? "danger" : undefined} />
        <Kpi label={tx("Stoktan karşılanabilir")} value={fmtQty(s?.from_stock ?? 0)} sub={tx("Serbest stokta var")} />
        <Kpi label={tx("Karşılandı")} value={fmtQty(s?.covered ?? 0)} sub={tx("Verildi, siparişte veya üretimde")} tone="ok" />
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      <DataGrid<Need>
        stateKey="İhtiyaç listesi" exportName={tx("İhtiyaç listesi")}
        data={rows} columns={columns} getRowId={(r) => r.code}
        selectable={canEdit} selection={selection} onSelectionChange={setSelection}
        rowStyle={(r) => (r.hidden ? { opacity: 0.35 } : undefined)}
        emptyText={quick === "short" ? tx("Eksik yok.") : tx("Kayıt yok. Projenin onaylı bir BOM sürümü olmalı.")}
        toolbar={<>
          {QUICK.map((x) => (
            <button key={x.key} className={`chip${quick === x.key ? " on" : ""}`} aria-pressed={quick === x.key}
              onClick={() => { setQuick(x.key); setSelection({}); }}>{x.label}</button>
          ))}
          {canEdit && <>
            <span className="muted" style={{ marginLeft: 8 }}>{selected.length ? tx("{0} seçili:", selected.length) : tx("Satır seçin:")}</span>
            <button className="btn small" disabled={!canIssue || issue.isPending} onClick={() => issue.mutate()}>{tx("Stoktan karşıla")}</button>
            <button className="btn small primary" disabled={!canPo} onClick={() => setDialog("po")}>{tx("Sipariş oluştur")}</button>
            <button className="btn small" disabled={!canWo} onClick={() => setDialog("wo")}>{tx("İş emri aç")}</button>
          </>}
        </>}
      />
      {dialog === "po" && <PoDialog pid={pid} rows={selected.filter((r) => r.shortage > 0)} onClose={() => setDialog(null)} onDone={refresh} />}
      {dialog === "wo" && <WoDialog pid={pid} rows={selected.filter((r) => r.shortage > 0 && r.kind === "part")} onClose={() => setDialog(null)} onDone={refresh} />}
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "danger" | "ok" | "warn" }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

function PoDialog({ pid, rows, onClose, onDone }: { pid: number; rows: Need[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [firm, setFirm] = useState<number | null>(null);
  const [due, setDue] = useState("");
  const firms = useFirms("supplier");
  // Picking a supplier sets Termin to today + its lead time (still editable)
  const pickFirm = (id: number | null) => {
    setFirm(id);
    const lead = firms.data?.find((f) => f.id === id)?.lead_days;
    if (lead) setDue(addDays(lead));
  };
  const [created, setCreated] = useState<PurchaseOrder | null>(null);
  const save = useMutation({
    mutationFn: () => api.post<PurchaseOrder>(`/projects/${pid}/requirements/purchase-order`,
      { codes: rows.map((r) => r.code), firm_id: firm, due_date: due || null }),
    onSuccess: (po) => { setCreated(po); onDone(); },
    onError: (e) => toast(errText(e), true),
  });
  if (created) {
    return (
      <Modal title={tx("Sipariş oluşturuldu")} onClose={onClose} footer={<button className="btn primary" onClick={onClose}>{tx("Tamam")}</button>}>
        <p><b>{created.no}</b>{" "}{tx("taslak olarak açıldı: {0} satır, {1}.", created.line_count, fmtMoney(created.total))}</p>
        <p>{tx("Fiyatları girip göndermek için")}{" "}<Link to={`/p/${pid}/purchasing`} onClick={onClose}>{tx("Satın Alma")}</Link>{" "}{tx("ekranını açın.")}</p>
      </Modal>
    );
  }
  return (
    <Modal title={tx("Eksiklerden satın alma siparişi")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("Taslak sipariş oluştur")}</button>
      </>}>
      <p className="muted">{tx("{0} kalem, eksik miktarlar kadar. Bilinen fiyatlar (bağlantı elemanı fiyatı veya stok ortalaması) satıra yazılır.", rows.length)}</p>
      <div className="adm-form">
        <Field label={tx("Tedarikçi")}><FirmSelect kind="supplier" value={firm} onChange={pickFirm} /></Field>
        <Field label={tx("Termin")}><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
      <ul className="erp-pick">{rows.map((r) => <li key={r.code}><span className="mono">{r.code}</span> · {fmtQty(r.shortage)} {tx(r.unit)}</li>)}</ul>
    </Modal>
  );
}

function WoDialog({ pid, rows, onClose, onDone }: { pid: number; rows: Need[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [maker, setMaker] = useState("");
  const [due, setDue] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<WorkOrder[]>(`/projects/${pid}/requirements/work-orders`,
      { codes: rows.map((r) => r.code), firm_name: maker.trim(), due_date: due || null }),
    onSuccess: (ws) => { toast(tx("{0} iş emri açıldı: {1}", ws.length, ws.map((w) => w.no).join(", "))); onDone(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={tx("Eksiklerden iş emri")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("{0} iş emri aç", rows.length)}</button>
      </>}>
      <div className="adm-form">
        <Field label={tx("Yapan")}><MakerInput value={maker} onChange={setMaker} /></Field>
        <Field label={tx("Termin")}><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
      <ul className="erp-pick">{rows.map((r) => <li key={r.code}><span className="mono">{r.code}</span>{" "}{tx("· {0} adet", fmtQty(r.shortage))}</li>)}</ul>
    </Modal>
  );
}

function CostTab() {
  const { pid } = useProject();
  const q = useQuery({ queryKey: ["costs", pid], queryFn: () => api.get<Costs>(`/projects/${pid}/costs`), enabled: !!pid });
  const c = q.data;
  const chart = (c?.by_group ?? []).slice(0, 15).map((g) => ({ name: g.name, "Taahhüt": g.committed, "Gerçekleşen": g.actual }));
  return (
    <div className="content">
      <Loading error={q.error} loading={q.isLoading} />
      {c && (
        <>
          <div className="grid kpis">
            <Kpi label={tx("Taahhüt edilen")} value={fmtMoney(c.committed)} sub={tx("Sipariş + iş emri + stoktan verilen")} />
            <Kpi label={tx("Gerçekleşen")} value={fmtMoney(c.actual)} sub={tx("Teslim alınan + üretilen + stoktan verilen")} tone="ok" />
            <Kpi label={tx("Bağlantı elemanı tahmini")} value={fmtMoney(c.fastener_estimate)} sub={tx("Bağlantı Elemanları ekranındaki fiyatlarla")} />
            <Kpi label={tx("Fiyatsız kalem")} value={fmtQty(c.missing_price)} sub={tx("Maliyete dahil edilemedi")} tone={c.missing_price ? "warn" : undefined} />
          </div>
          {c.unconverted.length > 0 && (
            <div className="card" style={{ marginTop: 12 }} role="alert">
              <span className="badge warn">{tx("Kuru bilinmeyen tutarlar toplamda yok")}</span>
              {c.unconverted.map((u) => (
                <p key={u.currency} style={{ margin: "6px 0 0" }}>
                  {tx("Taahhüt {0}, gerçekleşen {1}: {2}", fmtMoney(u.committed, u.currency), fmtMoney(u.actual, u.currency), u.documents.join(", "))}
                </p>
              ))}
              <p className="muted" style={{ marginBottom: 0 }}>{tx("Kuru Fatura ve ödeme > Kurlar sekmesinden girin.")}</p>
            </div>
          )}
          {chart.length > 0 && (
            <div className="card" style={{ marginTop: 12 }}>
              <h3 style={{ marginTop: 0 }}>{tx("Ana gruplara göre maliyet")}</h3>
              <ResponsiveContainer width="100%" height={Math.max(160, chart.length * 34 + 40)}>
                <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={(v: number) => v.toLocaleString(LOCALE)} />
                  <YAxis type="category" dataKey="name" width={160} tick={{ fill: "var(--fg)", fontSize: 12 }} />
                  <Tooltip formatter={(v) => fmtMoney(Number(v))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--fg)" }} />
                  <Legend />
                  <Bar dataKey="Taahhüt" name={tx("Taahhüt")} fill="#9ab8f0" isAnimationActive={false} />
                  <Bar dataKey="Gerçekleşen" name={tx("Gerçekleşen")} fill="#2e7d32" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="grid erp-cost-tables" style={{ marginTop: 12 }}>
            <CostTable title={tx("Kaynağa göre")} rows={c.by_source} />
            <CostTable title={tx("Firmaya göre")} rows={c.by_firm} />
            <CostTable title={tx("Ana gruba göre")} rows={c.by_group} />
          </div>
        </>
      )}
    </div>
  );
}

function CostTable({ title, rows }: { title: string; rows: CostRow[] }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <table className="simple erp-table" style={{ width: "100%" }}>
        <thead><tr><th></th><th className="num">{tx("Taahhüt")}</th><th className="num">{tx("Gerçekleşen")}</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r.name}><td>{r.name}</td><td className="num">{fmtMoney(r.committed)}</td><td className="num">{fmtMoney(r.actual)}</td></tr>)}
          {!rows.length && <tr><td colSpan={3} className="muted">{tx("Henüz fiyatlı sipariş veya iş emri yok.")}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
