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

// ---------- types (backend/app/services/erp.py requirements / project_costs) ----------
type Need = {
  code: string; kind: "part" | "fastener"; description: string; unit: string; required: number; procurement: string;
  status: string; status_color: string; progress: string | null; main_group: string; material: string;
  manufacturer: string; unit_price: number | null; done: boolean; issued: number; on_order: number;
  in_production: number; stock: number; net_need: number; from_stock: number; shortage: number;
  action: "" | "stock" | "purchase" | "work_order"; unit_cost: number | null;
  purchase_orders: string[]; work_orders: string[];
};
type NeedResp = { rows: Need[]; summary: { items: number; shortage: number; from_stock: number; covered: number } };
type CostRow = { name: string; committed: number; actual: number };
type Costs = {
  currency: string; committed: number; actual: number; missing_price: number; fastener_estimate: number;
  by_source: CostRow[]; by_firm: CostRow[]; by_group: CostRow[];
};

const ACTION_LABEL: Record<Need["action"], string> = { "": "", stock: "Stoktan karşıla", purchase: "Satın al", work_order: "İş emri aç" };
type Quick = "all" | "short" | "stock" | "covered";
const QUICK: { key: Quick; label: string; test: (r: Need) => boolean }[] = [
  { key: "all", label: "Tümü", test: () => true },
  { key: "short", label: "Eksikler", test: (r) => r.shortage > 0 },
  { key: "stock", label: "Stoktan karşılanabilir", test: (r) => r.from_stock > 0 },
  { key: "covered", label: "Karşılananlar", test: (r) => r.net_need <= 0 },
];
const num: CSSProperties = { textAlign: "right" };

/** İhtiyaç analizi (MRP) and project cost for one project. */
export default function Planning() {
  const [tab, setTab] = useState<"need" | "cost">("need");
  return (
    <Page full>
      <div className="toolbar">
        <div className="tabs" role="tablist" style={{ margin: 0 }}>
          <button role="tab" aria-selected={tab === "need"} className={tab === "need" ? "active" : ""} onClick={() => setTab("need")}>İhtiyaç analizi</button>
          <button role="tab" aria-selected={tab === "cost"} className={tab === "cost" ? "active" : ""} onClick={() => setTab("cost")}>Maliyet</button>
        </div>
      </div>
      {tab === "need" ? <NeedTab /> : <CostTab />}
    </Page>
  );
}

function NeedTab() {
  const { pid } = useProject();
  const { canEdit } = useAuth();
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
    onSuccess: (r) => { toast(`${r.issued} kalem stoktan projeye verildi`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<Need>[]>(() => [
    { accessorKey: "code", header: "Kod", size: 190, cellStyle: () => ({ fontFamily: "var(--mono, monospace)" }) },
    { accessorKey: "description", header: "Açıklama", size: 210 },
    { id: "kind", accessorFn: (r) => (r.kind === "fastener" ? "Bağlantı elemanı" : "Parça"), header: "Tür", size: 120 },
    { accessorKey: "procurement", header: "Temin", size: 95 },
    { accessorKey: "main_group", header: "Ana grup", size: 140 },
    { accessorKey: "status", header: "Durum", size: 150, cellStyle: (r) => statusStyle(r.status_color) },
    { accessorKey: "required", header: "Gerekli", size: 75, cellStyle: () => ({ ...num, fontWeight: 600 }), cell: (c) => fmtQty(c.row.original.required) },
    { accessorKey: "issued", header: "Verilen", size: 75, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.issued || null) },
    {
      accessorKey: "on_order", header: "Siparişte", size: 80, cellStyle: () => num,
      cell: (c) => <span title={c.row.original.purchase_orders.join(", ")}>{fmtQty(c.row.original.on_order || null)}</span>,
    },
    {
      accessorKey: "in_production", header: "Üretimde", size: 80, cellStyle: () => num,
      cell: (c) => <span title={c.row.original.work_orders.join(", ")}>{fmtQty(c.row.original.in_production || null)}</span>,
    },
    { accessorKey: "stock", header: "Serbest stok", size: 85, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.stock || null) },
    { accessorKey: "net_need", header: "Net ihtiyaç", size: 85, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.net_need || null) },
    { accessorKey: "from_stock", header: "Stoktan", size: 75, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.from_stock || null) },
    {
      accessorKey: "shortage", header: "Eksik", size: 75,
      cellStyle: (r) => ({ ...num, fontWeight: 700, color: r.shortage > 0 ? "var(--danger)" : undefined }),
      cell: (c) => fmtQty(c.row.original.shortage || null),
    },
    { id: "action", accessorFn: (r) => ACTION_LABEL[r.action], header: "Önerilen işlem", size: 125 },
  ], []);

  const s = q.data?.summary;
  const canPo = selected.some((r) => r.shortage > 0);
  const canWo = selected.some((r) => r.shortage > 0 && r.kind === "part");
  const canIssue = selected.some((r) => r.from_stock > 0);
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="grid kpis erp-kpis">
        <Kpi label="Kalem" value={fmtQty(s?.items ?? 0)} sub="Satın alınan / imal edilen parça ve bağlantı elemanı" />
        <Kpi label="Eksik" value={fmtQty(s?.shortage ?? 0)} sub="Sipariş veya iş emri gerekiyor" tone={s?.shortage ? "danger" : undefined} />
        <Kpi label="Stoktan karşılanabilir" value={fmtQty(s?.from_stock ?? 0)} sub="Serbest stokta var" />
        <Kpi label="Karşılandı" value={fmtQty(s?.covered ?? 0)} sub="Verildi, siparişte veya üretimde" tone="ok" />
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      <DataGrid<Need>
        data={rows} columns={columns} getRowId={(r) => r.code}
        selectable={canEdit} selection={selection} onSelectionChange={setSelection}
        emptyText={quick === "short" ? "Eksik yok." : "Kayıt yok. Projenin onaylı bir BOM sürümü olmalı."}
        toolbar={<>
          {QUICK.map((x) => (
            <button key={x.key} className={`chip${quick === x.key ? " on" : ""}`} aria-pressed={quick === x.key}
              onClick={() => { setQuick(x.key); setSelection({}); }}>{x.label}</button>
          ))}
          {canEdit && <>
            <span className="muted" style={{ marginLeft: 8 }}>{selected.length ? `${selected.length} seçili:` : "Satır seçin:"}</span>
            <button className="btn small" disabled={!canIssue || issue.isPending} onClick={() => issue.mutate()}>Stoktan karşıla</button>
            <button className="btn small primary" disabled={!canPo} onClick={() => setDialog("po")}>Sipariş oluştur</button>
            <button className="btn small" disabled={!canWo} onClick={() => setDialog("wo")}>İş emri aç</button>
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
      <Modal title="Sipariş oluşturuldu" onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Tamam</button>}>
        <p><b>{created.no}</b> taslak olarak açıldı: {created.line_count} satır, {fmtMoney(created.total)}.</p>
        <p>Fiyatları girip göndermek için <Link to={`/p/${pid}/purchasing`} onClick={onClose}>Satın Alma</Link> ekranını açın.</p>
      </Modal>
    );
  }
  return (
    <Modal title="Eksiklerden satın alma siparişi" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Taslak sipariş oluştur</button>
      </>}>
      <p className="muted">{rows.length} kalem, eksik miktarlar kadar. Bilinen fiyatlar (bağlantı elemanı fiyatı veya stok ortalaması) satıra yazılır.</p>
      <div className="adm-form">
        <Field label="Tedarikçi"><FirmSelect kind="supplier" value={firm} onChange={pickFirm} /></Field>
        <Field label="Termin"><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
      <ul className="erp-pick">{rows.map((r) => <li key={r.code}><span className="mono">{r.code}</span> · {fmtQty(r.shortage)} {r.unit}</li>)}</ul>
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
    onSuccess: (ws) => { toast(`${ws.length} iş emri açıldı: ${ws.map((w) => w.no).join(", ")}`); onDone(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title="Eksiklerden iş emri" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{rows.length} iş emri aç</button>
      </>}>
      <div className="adm-form">
        <Field label="Yapan"><MakerInput value={maker} onChange={setMaker} /></Field>
        <Field label="Termin"><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
      <ul className="erp-pick">{rows.map((r) => <li key={r.code}><span className="mono">{r.code}</span> · {fmtQty(r.shortage)} adet</li>)}</ul>
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
            <Kpi label="Taahhüt edilen" value={fmtMoney(c.committed)} sub="Sipariş + iş emri + stoktan verilen" />
            <Kpi label="Gerçekleşen" value={fmtMoney(c.actual)} sub="Teslim alınan + üretilen + stoktan verilen" tone="ok" />
            <Kpi label="Bağlantı elemanı tahmini" value={fmtMoney(c.fastener_estimate)} sub="Bağlantı Elemanları ekranındaki fiyatlarla" />
            <Kpi label="Fiyatsız kalem" value={fmtQty(c.missing_price)} sub="Maliyete dahil edilemedi" tone={c.missing_price ? "warn" : undefined} />
          </div>
          {chart.length > 0 && (
            <div className="card" style={{ marginTop: 12 }}>
              <h3 style={{ marginTop: 0 }}>Ana gruplara göre maliyet</h3>
              <ResponsiveContainer width="100%" height={Math.max(160, chart.length * 34 + 40)}>
                <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={(v: number) => v.toLocaleString("tr-TR")} />
                  <YAxis type="category" dataKey="name" width={160} tick={{ fill: "var(--fg)", fontSize: 12 }} />
                  <Tooltip formatter={(v) => fmtMoney(Number(v))} contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--fg)" }} />
                  <Legend />
                  <Bar dataKey="Taahhüt" fill="#9ab8f0" isAnimationActive={false} />
                  <Bar dataKey="Gerçekleşen" fill="#2e7d32" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="grid erp-cost-tables" style={{ marginTop: 12 }}>
            <CostTable title="Kaynağa göre" rows={c.by_source} />
            <CostTable title="Firmaya göre" rows={c.by_firm} />
            <CostTable title="Ana gruba göre" rows={c.by_group} />
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
        <thead><tr><th></th><th className="num">Taahhüt</th><th className="num">Gerçekleşen</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r.name}><td>{r.name}</td><td className="num">{fmtMoney(r.committed)}</td><td className="num">{fmtMoney(r.actual)}</td></tr>)}
          {!rows.length && <tr><td colSpan={3} className="muted">Henüz fiyatlı sipariş veya iş emri yok.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
