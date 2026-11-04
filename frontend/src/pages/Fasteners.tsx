import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { useMemo, useState, type CSSProperties } from "react";
import { api, download } from "../api/client";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import type { PartChoices } from "../components/PartDetail";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";

// backend/app/api/excel.py
const ORDER_FORM_PATH = (pid: number) => `/excel/${pid}/baglanti-siparis`;

// ---------- types (backend/app/services/state.py ProjectView.fasteners / row_view) ----------
type FastenerItem = {
  key: string; type: string | null; desc: string | null; std: string | null; size: string | null;
  total_qty: number; rows: number; groups: string[]; names: string[];
  spare_pct: number; spare_qty: number; order_qty: number;
  supplier: string; unit: string; unit_price: number | null; total_price: number | null;
  order_status: string; status_color: string; note: string; hidden?: boolean;
};
type FastenerSummary = {
  items: FastenerItem[]; statuses: string[]; colors: Record<string, string>;
  totals: { unique: number; total_qty: number; order_qty: number; total_price: number | null; by_status: Record<string, number> };
};
type FastenerRow = {
  id: number; seq: number; level: string; depth: number; file_name: string; part_no: string;
  qty: number; multiplier: number; total_qty: number; parent_part_no: string | null; main_group: string | null;
  in_purchased: boolean; hidden?: boolean; fastener_key: string; fastener_type: string | null; fastener_desc: string | null;
  fastener_std: string | null; fastener_size: string | null; status: string; status_color: string;
};
type SettingsBody = {
  keys: string[]; spare_pct?: number; supplier?: string; unit?: string; unit_price?: number;
  clear_price?: boolean; order_status?: string; note?: string; hidden?: boolean;
};

/** Pastel badge colours per fastener type (FASTENER_COLORS in the backend are per order status). */
const TYPE_COLORS: Record<string, string> = {
  "Cıvata": "DDEBF7", "Somun": "E2EFDA", "Pim": "FCE4D6", "Rondela": "EDE1F5", "Kama": "FFF2CC", "Segman": "DDF3F3",
};
const typeColor = (t: string | null) => {
  if (!t) return undefined;
  const base = Object.keys(TYPE_COLORS).find((k) => t.startsWith(k));
  return base ? TYPE_COLORS[base] : "EDEDED";
};
const IN_PURCHASED_COLOR = "D9D9D9";

const fmtInt = (n: number | null | undefined) => (n === null || n === undefined ? "" : n.toLocaleString("tr-TR"));
const fmtMoney = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const parseNum = (s: string): number | null => {
  const t = s.trim().replace(/\s/g, "");
  if (!t) return null;
  // Accept both "1.234,5" and "1234.5".
  const v = Number(t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t);
  return Number.isFinite(v) ? v : NaN;
};
const num: CSSProperties = { textAlign: "right" };

export default function Fasteners() {
  const { pid, project } = useProject();
  const canEdit = useAuth().can("fasteners", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"ozet" | "detay">("ozet");

  const summaryQ = useQuery({
    queryKey: ["fasteners", pid],
    queryFn: () => api.get<FastenerSummary>(`/projects/${pid}/fasteners`),
    enabled: !!pid,
  });
  const rowsQ = useQuery({
    queryKey: ["fastener-rows", pid],
    queryFn: () => api.get<FastenerRow[]>(`/projects/${pid}/fasteners/rows`),
    enabled: !!pid,
  });
  // Supplier names come from the shared choices endpoint, so every role gets the list.
  const choicesQ = useQuery({
    queryKey: ["partChoices", pid],
    queryFn: () => api.get<PartChoices>(`/projects/${pid}/parts/choices`),
    enabled: !!pid, staleTime: 60_000,
  });

  const save = useMutation({
    mutationFn: (body: SettingsBody) =>
      api.put<{ changed: number; items: FastenerItem[] }>(`/projects/${pid}/fasteners/settings`, body),
    onSuccess: (res) => {
      const byKey = new Map(res.items.map((i) => [i.key, i]));
      qc.setQueryData<FastenerSummary>(["fasteners", pid], (old) =>
        old ? { ...old, items: old.items.map((i) => byKey.get(i.key) ?? i) } : old);
      qc.invalidateQueries({ queryKey: ["fasteners", pid] });
      qc.invalidateQueries({ queryKey: ["fastener-rows", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
      toast(res.changed ? `${res.items.length.toLocaleString("tr-TR")} kalem güncellendi` : "Değişiklik yok");
    },
    onError: (e) => toast(errText(e), true),
  });

  const items = summaryQ.data?.items ?? [];
  const rows = rowsQ.data ?? [];
  const statuses = summaryQ.data?.statuses ?? ["Sipariş Verilmedi", "Sipariş Verildi", "Teslim Edildi"];

  const kpi = useMemo(() => {
    let total = 0, order = 0, price = 0, priced = 0, unpriced = 0;
    const byStatus: Record<string, number> = {};
    for (const i of items) {
      total += i.total_qty;
      order += i.order_qty;
      if (i.total_price !== null) { price += i.total_price; priced++; } else unpriced++;
      byStatus[i.order_status] = (byStatus[i.order_status] ?? 0) + 1;
    }
    const inPurchased = rows.filter((r) => r.in_purchased);
    return {
      unique: items.length, total, order, price, priced, unpriced, byStatus,
      rows: rows.length, inPurchased: inPurchased.length,
      inPurchasedQty: inPurchased.reduce((s, r) => s + r.total_qty, 0),
    };
  }, [items, rows]);

  const supplierOptions = useMemo(() => {
    const s = new Set<string>();
    for (const n of choicesQ.data?.suppliers ?? []) s.add(n);
    if (s.size === 0) return null; // no firm list available: free text
    for (const i of items) if (i.supplier) s.add(i.supplier);
    return ["", ...[...s].sort((a, b) => a.localeCompare(b, "tr-TR"))];
  }, [choicesQ.data, items]);

  const noBom = project && !project.current_version;
  const loading = summaryQ.isLoading || rowsQ.isLoading;
  const error = summaryQ.error || rowsQ.error;

  return (
    <Page full>
      <div style={{ padding: "12px 16px 0" }}>
        <div className="row" style={{ alignItems: "center", marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Bağlantı Elemanları</h2>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="btn" disabled={!items.length}
            onClick={() => download(ORDER_FORM_PATH(pid), "Bağlantı_Sipariş_Formu.xlsx").catch((e) => toast(errText(e), true))}>
            Sipariş formu (Excel)
          </button>
        </div>
        {!loading && !error && !noBom && (
          <div className="grid kpis" style={{ marginBottom: 10 }}>
            <Kpi label="Benzersiz kalem" value={fmtInt(kpi.unique)} />
            <Kpi label="Toplam adet (ihtiyaç)" value={fmtInt(kpi.total)} />
            <Kpi label="Sipariş adedi (yedek dahil)" value={fmtInt(kpi.order)} />
            <Kpi label="Bağlantı elemanı satırı" value={fmtInt(kpi.rows)} />
            <Kpi label="Satın alınan montaj içinde" value={fmtInt(kpi.inPurchased)}
              sub={`${fmtInt(kpi.inPurchasedQty)} adet, sayılmaz`} />
            <Kpi label="Toplam tutar" value={fmtMoney(kpi.price)}
              sub={kpi.unpriced ? `${fmtInt(kpi.unpriced)} kalemde fiyat yok` : "Tüm kalemler fiyatlı"} />
            <div className="card kpi">
              <div className="label">Sipariş durumu</div>
              <div className="row" style={{ gap: 4, marginTop: 6 }}>
                {statuses.map((s) => (
                  <span key={s} className="badge" style={statusStyle(summaryQ.data?.colors[s])}>
                    {s}: {fmtInt(kpi.byStatus[s] ?? 0)}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
        <div className="tabs" style={{ marginBottom: 0 }}>
          <button className={tab === "ozet" ? "active" : ""} onClick={() => setTab("ozet")}>
            Özet ({fmtInt(items.length)})
          </button>
          <button className={tab === "detay" ? "active" : ""} onClick={() => setTab("detay")}>
            Detay ({fmtInt(rows.length)})
          </button>
        </div>
      </div>

      {error ? (
        <div className="card" style={{ margin: 16 }}><span className="badge err">Hata</span> {errText(error)}</div>
      ) : loading ? (
        <div className="muted" style={{ padding: 16 }}>Yükleniyor…</div>
      ) : noBom ? (
        <div className="muted" style={{ padding: 16 }}>Bu projede onaylanmış BOM sürümü yok. Önce BOM yükleyip onaylayın.</div>
      ) : tab === "ozet" ? (
        <SummaryTab items={items} statuses={statuses} canEdit={canEdit} supplierOptions={supplierOptions}
          saving={save.isPending} onSave={(b) => save.mutate(b)} />
      ) : (
        <DetailTab rows={rows} statuses={statuses} canEdit={canEdit} onSave={(b) => save.mutate(b)} />
      )}
    </Page>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

// ---------- Özet ----------
function SummaryTab(p: {
  items: FastenerItem[]; statuses: string[]; canEdit: boolean; supplierOptions: string[] | null;
  saving: boolean; onSave: (b: SettingsBody) => void;
}) {
  const toast = useToast();
  const { items, statuses, canEdit, supplierOptions, onSave } = p;
  const [visible, setVisible] = useState<FastenerItem[]>(items);
  const [selection, setSelection] = useState<RowSelectionState>({});

  const columns = useMemo<GridColumn<FastenerItem>[]>(() => [
    {
      accessorKey: "type", header: "Tür", size: 110,
      cell: (c) => <span className="badge" style={statusStyle(typeColor(c.row.original.type))}>{c.row.original.type}</span>,
    },
    { accessorKey: "std", header: "Standart", size: 170 },
    { accessorKey: "size", header: "Ölçü", size: 100 },
    { accessorKey: "desc", header: "Açıklama", size: 160 },
    { accessorKey: "rows", header: "Satır", size: 60, cellStyle: () => num, cell: (c) => fmtInt(c.row.original.rows) },
    { id: "groups", accessorFn: (r) => r.groups.join(", "), header: "Kullanıldığı Ana Gruplar", size: 200 },
    {
      accessorKey: "total_qty", header: "Toplam Adet", size: 90, cellStyle: () => ({ ...num, fontWeight: 600 }),
      cell: (c) => fmtInt(c.row.original.total_qty),
    },
    {
      accessorKey: "spare_pct", header: "Yedek %", size: 75, cellStyle: () => num,
      cell: (c) => fmtInt(c.row.original.spare_pct),
      edit: canEdit ? { type: "number" } : undefined,
    },
    { accessorKey: "spare_qty", header: "Yedek Adet", size: 80, cellStyle: () => num, cell: (c) => fmtInt(c.row.original.spare_qty) },
    {
      accessorKey: "order_qty", header: "Sipariş Adedi", size: 95, cellStyle: () => ({ ...num, fontWeight: 600 }),
      cell: (c) => fmtInt(c.row.original.order_qty),
    },
    { accessorKey: "unit", header: "Birim", size: 65, edit: canEdit ? { type: "text" } : undefined },
    {
      accessorKey: "supplier", header: "Tedarikçi", size: 150,
      edit: canEdit ? (supplierOptions ? { type: "select", options: supplierOptions } : { type: "text" }) : undefined,
    },
    {
      accessorKey: "unit_price", header: "Birim Fiyat", size: 90, cellStyle: () => num,
      cell: (c) => fmtMoney(c.row.original.unit_price),
      edit: canEdit ? { type: "number" } : undefined,
    },
    {
      accessorKey: "total_price", header: "Tutar", size: 100, cellStyle: () => ({ ...num, fontWeight: 600 }),
      cell: (c) => fmtMoney(c.row.original.total_price),
    },
    {
      accessorKey: "order_status", header: "Sipariş Durumu", size: 135,
      cellStyle: (r) => statusStyle(r.status_color),
      edit: canEdit ? { type: "select", options: statuses } : undefined,
    },
    { accessorKey: "note", header: "Not", size: 180, edit: canEdit ? { type: "text" } : undefined },
  ], [canEdit, supplierOptions, statuses]);

  const onEdit = (row: FastenerItem, col: string, value: string) => {
    const body = fieldBody([row.key], col, value);
    if (typeof body === "string") toast(body, true);
    else if (body) onSave(body);
  };

  const foot = useMemo(() => {
    let total = 0, order = 0, price = 0, unpriced = 0;
    for (const i of visible) {
      total += i.total_qty;
      order += i.order_qty;
      if (i.total_price !== null) price += i.total_price; else unpriced++;
    }
    return { total, order, price, unpriced };
  }, [visible]);

  const selectedKeys = useMemo(() => Object.keys(selection).filter((k) => selection[k]), [selection]);
  const allHidden = selectedKeys.length > 0 && items.every((i) => !selection[i.key] || i.hidden);
  const targetKeys = selectedKeys.length ? selectedKeys : visible.map((i) => i.key);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {canEdit && (
        <BulkBar targetCount={targetKeys.length} selected={selectedKeys.length > 0} statuses={statuses}
          supplierOptions={supplierOptions} saving={p.saving}
          onApply={(b) => { onSave({ ...b, keys: targetKeys }); }}
          onClearSelection={() => setSelection({})} />
      )}
      <DataGrid<FastenerItem>
        exportName="Bağlantı elemanları"
        data={items} columns={columns} getRowId={(r) => r.key}
        onEdit={canEdit ? onEdit : undefined}
        selectable={canEdit} selection={selection} onSelectionChange={setSelection}
        rowStyle={(r) => (r.hidden ? { opacity: 0.35 } : undefined)}
        onVisibleRowsChange={setVisible}
        emptyText="Bağlantı elemanı yok."
        toolbar={<>
          {canEdit && (
            <button className="btn small" disabled={!selectedKeys.length || p.saving}
              title="Seçilenler listede kalır, yalnızca soluk görünür. Adet ve durumlar değişmez."
              onClick={() => { onSave({ keys: selectedKeys, hidden: !allHidden }); setSelection({}); }}>
              {allHidden ? "Gizlemeyi kaldır" : "Gizle"}
            </button>
          )}
          <span className="muted">Satın alınan montajların içindeki bağlantı elemanları özete dahil değildir.</span>
        </>}
      />
      <div className="toolbar fx-foot">
        <b>Genel toplam ({fmtInt(visible.length)} kalem)</b>
        <span className="spacer" style={{ flex: 1 }} />
        <span>Toplam adet: <b>{fmtInt(foot.total)}</b></span>
        <span>Sipariş adedi: <b>{fmtInt(foot.order)}</b></span>
        <span>Tutar: <b>{fmtMoney(foot.price)}</b></span>
        {foot.unpriced > 0 && <span className="badge warn">{fmtInt(foot.unpriced)} kalemde fiyat yok</span>}
      </div>
    </div>
  );
}

/** Build the PUT body for one edited column, or an error message. */
function fieldBody(keys: string[], col: string, value: string): SettingsBody | string | null {
  switch (col) {
    case "spare_pct": {
      const v = parseNum(value);
      if (v === null || Number.isNaN(v) || v < 0 || v > 1000) return "Yedek % 0 ile 1000 arasında bir sayı olmalı";
      return { keys, spare_pct: v };
    }
    case "unit_price": {
      const v = parseNum(value);
      if (v === null) return { keys, clear_price: true };
      if (Number.isNaN(v) || v < 0) return "Birim fiyat sıfır veya pozitif bir sayı olmalı";
      return { keys, unit_price: v };
    }
    case "unit":
      if (!value.trim()) return "Birim boş olamaz";
      return { keys, unit: value.trim() };
    case "supplier": return { keys, supplier: value.trim() };
    case "order_status": return { keys, order_status: value };
    case "note": return { keys, note: value };
    default: return null;
  }
}

function BulkBar(p: {
  targetCount: number; selected: boolean; statuses: string[]; supplierOptions: string[] | null; saving: boolean;
  onApply: (b: Omit<SettingsBody, "keys">) => void; onClearSelection: () => void;
}) {
  const toast = useToast();
  const [spare, setSpare] = useState("");
  const [status, setStatus] = useState("");
  const [supplier, setSupplier] = useState("");
  const [price, setPrice] = useState("");

  const apply = () => {
    const b: Omit<SettingsBody, "keys"> = {};
    if (spare.trim()) {
      const v = parseNum(spare);
      if (v === null || Number.isNaN(v) || v < 0 || v > 1000) return toast("Yedek % 0 ile 1000 arasında bir sayı olmalı", true);
      b.spare_pct = v;
    }
    if (price.trim()) {
      const v = parseNum(price);
      if (v === null || Number.isNaN(v) || v < 0) return toast("Birim fiyat sıfır veya pozitif bir sayı olmalı", true);
      b.unit_price = v;
    }
    if (status) b.order_status = status;
    if (supplier.trim()) b.supplier = supplier.trim();
    if (!Object.keys(b).length) return toast("Uygulanacak bir değer girin", true);
    if (!p.targetCount) return toast("Uygulanacak kalem yok", true);
    p.onApply(b);
    setSpare(""); setStatus(""); setSupplier(""); setPrice("");
  };

  return (
    <div className="toolbar fx-bulk">
      <b>Toplu düzenle</b>
      <label className="row" style={{ gap: 4 }}>Yedek %
        <input type="number" min={0} max={1000} value={spare} onChange={(e) => setSpare(e.target.value)} style={{ width: 70 }} />
      </label>
      <label className="row" style={{ gap: 4 }}>Durum
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">—</option>
          {p.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <label className="row" style={{ gap: 4 }}>Tedarikçi
        {p.supplierOptions ? (
          <select value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            {p.supplierOptions.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
          </select>
        ) : (
          <input value={supplier} onChange={(e) => setSupplier(e.target.value)} style={{ width: 140 }} />
        )}
      </label>
      <label className="row" style={{ gap: 4 }}>Birim fiyat
        <input type="number" min={0} step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} style={{ width: 90 }} />
      </label>
      <button className="btn small primary" disabled={p.saving} onClick={apply}>
        {p.selected ? "Seçili" : "Görünen"} {p.targetCount.toLocaleString("tr-TR")} kaleme uygula
      </button>
      {p.selected && <button className="btn small" onClick={p.onClearSelection}>Seçimi kaldır</button>}
    </div>
  );
}

// ---------- Detay ----------
function DetailTab(p: { rows: FastenerRow[]; statuses: string[]; canEdit: boolean; onSave: (b: SettingsBody) => void }) {
  const { rows, statuses, canEdit, onSave } = p;
  const [showPurchased, setShowPurchased] = useState(true);
  const [visible, setVisible] = useState<FastenerRow[]>(rows);
  const data = useMemo(() => (showPurchased ? rows : rows.filter((r) => !r.in_purchased)), [rows, showPurchased]);

  const columns = useMemo<GridColumn<FastenerRow>[]>(() => [
    { accessorKey: "level", header: "Seviye", size: 80 },
    { id: "main_group", accessorFn: (r) => r.main_group ?? "", header: "Ana Grup", size: 150 },
    { id: "parent", accessorFn: (r) => r.parent_part_no ?? "", header: "Üst Montaj", size: 160 },
    { accessorKey: "file_name", header: "Parça / Dosya Adı", size: 260 },
    {
      id: "type", accessorFn: (r) => r.fastener_type ?? "", header: "Tür", size: 110,
      cell: (c) => <span className="badge" style={statusStyle(typeColor(c.row.original.fastener_type))}>{c.row.original.fastener_type}</span>,
    },
    { id: "std", accessorFn: (r) => r.fastener_std ?? "", header: "Standart", size: 170 },
    { id: "size", accessorFn: (r) => r.fastener_size ?? "", header: "Ölçü (d×l)", size: 100 },
    { accessorKey: "qty", header: "Adet", size: 60, cellStyle: () => num, cell: (c) => fmtInt(c.row.original.qty) },
    { accessorKey: "multiplier", header: "Çarpan", size: 65, cellStyle: () => num, cell: (c) => fmtInt(c.row.original.multiplier) },
    {
      accessorKey: "total_qty", header: "Toplam Adet", size: 90, cellStyle: () => ({ ...num, fontWeight: 600 }),
      cell: (c) => fmtInt(c.row.original.total_qty),
    },
    {
      id: "in_purchased", accessorFn: (r) => (r.in_purchased ? "Evet" : "Hayır"), header: "Satın Alınan Montaj İçi", size: 120,
      cellStyle: (r) => (r.in_purchased ? statusStyle(IN_PURCHASED_COLOR) : undefined),
    },
    {
      accessorKey: "status", header: "Sipariş Durumu", size: 135,
      cellStyle: (r) => (r.in_purchased ? undefined : statusStyle(r.status_color)),
      cell: (c) => (c.row.original.in_purchased ? <span className="muted">Takip edilmez</span> : c.row.original.status),
      edit: canEdit ? { type: "select", options: statuses, canEdit: (r) => !r.in_purchased } : undefined,
    },
  ], [canEdit, statuses]);

  const counted = useMemo(() => {
    let qty = 0, n = 0;
    for (const r of visible) if (!r.in_purchased) { qty += r.total_qty; n++; }
    return { qty, n };
  }, [visible]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <DataGrid<FastenerRow>
        exportName="Bağlantı elemanı satırları"
        data={data} columns={columns} getRowId={(r) => String(r.id)}
        onEdit={canEdit ? (r, col, v) => { if (col === "status") onSave({ keys: [r.fastener_key], order_status: v }); } : undefined}
        rowStyle={(r) => ({ ...(r.in_purchased ? { color: "var(--muted)" } : {}), ...(r.hidden ? { opacity: 0.35 } : {}) })}
        onVisibleRowsChange={setVisible}
        emptyText="Bağlantı elemanı satırı yok."
        toolbar={
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={showPurchased} onChange={(e) => setShowPurchased(e.target.checked)} />
            Satın alınan montajların içindekileri göster
          </label>
        }
      />
      <div className="toolbar fx-foot">
        <span className="muted">Sayılan (satın alınan montaj dışı):</span>
        <span><b>{fmtInt(counted.n)}</b> satır</span>
        <span>Toplam adet: <b>{fmtInt(counted.qty)}</b></span>
      </div>
    </div>
  );
}
