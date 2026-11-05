import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { saveRev } from "../api/conflict";
import { curSign, sys } from "../api/system";
import { useAuth } from "../api/auth";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import LabelsModal, { type Label } from "../components/Labels";
import { Page } from "../components/Layout";
import Photos from "../components/Photos";
import { errText, useToast } from "../components/Toast";
import { Field, Loading, Modal, fmtDate } from "./admin/shared";
import { FirmSelect, ITEM_KINDS, ProjectSelect, fmtMoney, fmtQty, numOrNull, useFirms, type ReorderRow, type StockItem, type StockMove } from "./erp/common";

type ListResp = { rows: StockItem[]; total_value: number; low_count: number };

const num: CSSProperties = { textAlign: "right" };
const lowStyle = (r: StockItem): CSSProperties | undefined =>
  r.low ? { background: "color-mix(in srgb, var(--warn) 18%, transparent)" } : undefined;

/** Stok / depo: stock cards, manual moves and the ledger. */
export default function Stock() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"items" | "moves" | "reorder">("items");
  return (
    <Page full>
      <div className="toolbar">
        <div className="tabs" role="tablist" style={{ margin: 0 }}>
          <button role="tab" aria-selected={tab === "items"} className={tab === "items" ? "active" : ""} onClick={() => setTab("items")}>Stok kartları</button>
          <button role="tab" aria-selected={tab === "moves"} className={tab === "moves" ? "active" : ""} onClick={() => setTab("moves")}>Son hareketler</button>
          {can("purchasing") && <button role="tab" aria-selected={tab === "reorder"} className={tab === "reorder" ? "active" : ""} onClick={() => setTab("reorder")}>Sipariş önerileri</button>}
        </div>
      </div>
      {tab === "items" ? <Items /> : tab === "moves" ? <MovesTab /> : <Reorder />}
    </Page>
  );
}

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["stock", "stock-moves", "requirements", "costs", "parts"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

function Items() {
  const canEdit = useAuth().can("stock", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [low, setLow] = useState(false);
  const [editing, setEditing] = useState<StockItem | "new" | null>(null);
  const [moving, setMoving] = useState<StockItem | null>(null);
  const [ledger, setLedger] = useState<StockItem | null>(null);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [labels, setLabels] = useState<Label[] | null>(null);
  const list = useQuery({ queryKey: ["stock", low], queryFn: () => api.get<ListResp>(`/stock${low ? "?low=true" : ""}`) });
  const del = useMutation({
    mutationFn: (i: StockItem) => api.del(`/stock/${i.id}`),
    onSuccess: () => { toast("Stok kartı silindi"); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  const columns = useMemo<GridColumn<StockItem>[]>(() => [
    { accessorKey: "code", header: "Kod", size: 190, cellStyle: () => ({ fontFamily: "var(--mono, monospace)" }) },
    { accessorKey: "name", header: "Ad", size: 220 },
    { accessorKey: "kind_label", header: "Tür", size: 120 },
    { accessorKey: "unit", header: "Birim", size: 60 },
    { accessorKey: "qty", header: "Miktar", size: 90, cellStyle: (r) => ({ ...num, fontWeight: 600, ...(r.low ? { color: "var(--danger)" } : {}) }), cell: (c) => fmtQty(c.row.original.qty) },
    { accessorKey: "min_qty", header: "Min. stok", size: 80, cellStyle: () => num, cell: (c) => fmtQty(c.row.original.min_qty || null) },
    { accessorKey: "unit_cost", header: "Ort. maliyet", size: 100, cellStyle: () => num, cell: (c) => fmtMoney(c.row.original.unit_cost) },
    { accessorKey: "value", header: "Değer", size: 110, cellStyle: () => num, cell: (c) => fmtMoney(c.row.original.value) },
    { accessorKey: "location", header: "Konum", size: 110 },
    { accessorKey: "note", header: "Not", size: 160 },
    {
      id: "actions", header: "", size: canEdit ? 250 : 100, noFilter: true, enableSorting: false,
      cell: (c) => {
        const i = c.row.original;
        return (
          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
            {canEdit && <button className="btn small primary" onClick={() => setMoving(i)}>Hareket</button>}
            <button className="btn small" onClick={() => setLedger(i)}>Hareketler</button>
            {canEdit && <button className="btn small" onClick={() => setEditing(i)}>Düzenle</button>}
            {canEdit && <button className="btn small danger" disabled={del.isPending} onClick={() => confirm(`${i.code} stok kartı silinsin mi?`) && del.mutate(i)}>Sil</button>}
          </div>
        );
      },
    },
  ], [canEdit, del]);

  const d = list.data;
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Loading error={list.error} loading={list.isLoading} />
      <DataGrid<StockItem>
        exportName="Stok kartları"
        data={d?.rows ?? []} columns={columns} getRowId={(r) => String(r.id)} rowStyle={lowStyle}
        selectable selection={selection} onSelectionChange={setSelection}
        selectionActions={<button className="btn small" onClick={() => setLabels((d?.rows ?? []).filter((r) => selection[String(r.id)])
          .map((r) => ({ payload: `STK:${r.code}`, title: r.code, sub: [r.name, r.location].filter(Boolean).join(" · ") })))}>QR etiket</button>}
        emptyText={low ? "Kritik seviyenin altında stok yok." : "Stok kartı yok. Satın alma mal kabulü ve üretim girişleri kartları kendiliğinden açar."}
        toolbar={<>
          {canEdit && <button className="btn small primary" onClick={() => setEditing("new")}>+ Yeni stok kartı</button>}
          <span className="muted">{fmtQty(d?.rows.length ?? 0)} kart · stok değeri <b>{fmtMoney(d?.total_value ?? 0)}</b></span>
          <button className={`chip${low ? " on" : ""}`} aria-pressed={low} onClick={() => setLow((v) => !v)}>
            Kritik stok <span className="muted">{fmtQty(d?.low_count ?? 0)}</span>
          </button>
        </>}
      />
      {editing && <ItemForm item={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
      {moving && <MoveModal item={moving} onClose={() => setMoving(null)} />}
      {ledger && <LedgerModal item={ledger} onClose={() => setLedger(null)} />}
      {labels && <LabelsModal labels={labels} onClose={() => setLabels(null)} />}
    </div>
  );
}

function ItemForm({ item, onClose }: { item?: StockItem; onClose: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const refresh = useRefresh();
  const [code, setCode] = useState(item?.code ?? "");
  const [name, setName] = useState(item?.name ?? "");
  const [kind, setKind] = useState<string>(item?.kind ?? "part");
  const [unit, setUnit] = useState(item?.unit ?? sys.unit);
  const [minQty, setMinQty] = useState(item ? String(item.min_qty) : "0");
  const [cost, setCost] = useState(item?.unit_cost == null ? "" : String(item.unit_cost));
  const [location, setLocation] = useState(item?.location ?? "");
  const [note, setNote] = useState(item?.note ?? "");
  const [opening, setOpening] = useState("0");
  const [reorderQty, setReorderQty] = useState(item ? String(item.reorder_qty) : "0");
  const [firm, setFirm] = useState<number | null>(item?.preferred_firm_id ?? null);
  const firms = useFirms("supplier");
  const firmGone = firm !== null && firms.data !== undefined && !firms.data.some((f) => f.id === firm);
  const save = useMutation({
    mutationFn: () => {
      const body = { name, kind, unit, min_qty: numOrNull(minQty) ?? 0, unit_cost: numOrNull(cost), location, note,
        reorder_qty: numOrNull(reorderQty) ?? 0, preferred_firm_id: firm };
      // Only what changed: fields someone else edited meanwhile keep their value
      const changed = item && Object.fromEntries(Object.entries(body).filter(([k, v]) => v !== item[k as keyof typeof body]));
      return item ? saveRev(item.rev, (rev) => api.put<StockItem>(`/stock/${item.id}`, { ...changed, rev }))
        : api.post<StockItem>("/stock", { ...body, code: code.trim(), qty: numOrNull(opening) ?? 0 });
    },
    onSuccess: () => { toast(item ? "Stok kartı güncellendi" : "Stok kartı açıldı"); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={item ? `Stok kartı: ${item.code}` : "Yeni stok kartı"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || (!item && !code.trim())} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form two">
        <Field label="Kod" hint="Parça no veya bağlantı elemanı anahtarı (tür|standart|ölçü).">
          {item ? <input disabled value={item.code} /> : <input autoFocus value={code} onChange={(e) => setCode(e.target.value)} />}
        </Field>
        <Field label="Ad"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Tür">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {ITEM_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </Field>
        <Field label="Birim"><input value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
        <Field label="Minimum stok"><input inputMode="decimal" value={minQty} onChange={(e) => setMinQty(e.target.value)} /></Field>
        <Field label="Sipariş miktarı" hint="Stok minimumun altına düşünce önerilecek en az miktar. 0: minimuma tamamlar.">
          <input inputMode="decimal" value={reorderQty} onChange={(e) => setReorderQty(e.target.value)} />
        </Field>
        <Field label="Tercih edilen tedarikçi" hint={firmGone ? <span className="error">Kayıtlı firma silinmiş veya pasif; başka firma seçin.</span> : undefined}>
          <FirmSelect kind="supplier" value={firm} onChange={setFirm} />
        </Field>
        <Field label={`Birim maliyet (${curSign()})`}><input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>
        <Field label="Konum (raf/depo)"><input value={location} onChange={(e) => setLocation(e.target.value)} /></Field>
        {!item && <Field label="Açılış miktarı"><input inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} /></Field>}
      </div>
      <div style={{ marginTop: 10 }}><Field label="Not"><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
      {item && (
        <div style={{ marginTop: 12 }}>
          <h4 style={{ margin: "0 0 6px" }}>Fotoğraflar</h4>
          <Photos entity="stock" entityKey={String(item.id)} canEdit={can("stock", "edit")} />
        </div>
      )}
    </Modal>
  );
}

const MOVE_OPTIONS = [
  { value: "in", label: "Giriş" },
  { value: "out", label: "Çıkış" },
  { value: "count", label: "Sayım (miktarı düzelt)" },
  { value: "issue", label: "Projeye çıkış" },
];

function MoveModal({ item, onClose }: { item: StockItem; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [kind, setKind] = useState("in");
  const [qty, setQty] = useState("");
  const [cost, setCost] = useState("");
  const [project, setProject] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post<StockItem>(`/stock/${item.id}/moves`, {
      kind, qty: numOrNull(qty) ?? 0, unit_cost: kind === "in" ? numOrNull(cost) : null, project_id: project, note,
    }),
    onSuccess: (i) => { toast(`${i.code}: stok ${fmtQty(i.qty)} ${i.unit}`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={`Stok hareketi: ${item.code}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || numOrNull(qty) === null || (kind === "issue" && !project)} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <p className="muted">{item.name} · mevcut stok <b>{fmtQty(item.qty)} {item.unit}</b></p>
      <div className="adm-form">
        <Field label="Hareket">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {MOVE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
        <Field label={kind === "count" ? "Sayılan miktar" : "Miktar"}><input autoFocus inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        {kind === "in" && <Field label={`Birim maliyet (${curSign()})`} hint="Ortalama maliyeti günceller."><input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>}
        {(kind === "issue" || kind === "out") && (
          <Field label="Proje" hint={kind === "issue" ? "Projeye verilen miktar ihtiyaç analizinde karşılanmış sayılır." : undefined}>
            <ProjectSelect value={project} onChange={setProject} emptyLabel={kind === "issue" ? "(Proje seçin)" : "(Proje yok)"} />
          </Field>
        )}
        <Field label="Not"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

type Created = { id: number; no: string; firm_name: string; line_count: number };
type Pick = { on: boolean; qty: string; firm: number | null };

/** Sipariş önerileri: cards under their minimum, turned into draft purchase orders. */
function Reorder() {
  const canOrder = useAuth().can("purchasing", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [picks, setPicks] = useState<Record<number, Partial<Pick>>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [created, setCreated] = useState<Created[]>([]);
  const list = useQuery({ queryKey: ["stock", "reorder"], queryFn: () => api.get<{ rows: ReorderRow[] }>("/stock/reorder") });
  const rows = list.data?.rows ?? [];
  const pick = (r: ReorderRow): Pick => ({ on: false, qty: String(r.suggested_qty), firm: r.firm_id, ...picks[r.item_id] });
  const set = (id: number, patch: Partial<Pick>) => setPicks((p) => ({ ...p, [id]: { ...p[id], ...patch } }));
  const chosen = rows.filter((r) => pick(r).on);
  const allOn = rows.length > 0 && chosen.length === rows.length;
  const create = useMutation({
    mutationFn: () => api.post<{ orders: Created[] }>("/stock/reorder/orders", {
      items: chosen.map((r) => ({ item_id: r.item_id, qty: numOrNull(pick(r).qty) ?? 0, firm_id: pick(r).firm })),
    }),
    onSuccess: (d) => {
      toast(`${d.orders.length} taslak sipariş oluşturuldu`);
      setCreated(d.orders);
      setPicks({});
      setErrors({});
      void qc.invalidateQueries({ queryKey: ["stock"] });
      void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
    },
    onError: (e) => {
      toast(errText(e), true);
      const body = e instanceof ApiError ? e.body as { detail?: { errors?: { item_id: number; error: string }[] } } : undefined;
      setErrors(Object.fromEntries((body?.detail?.errors ?? []).map((x) => [x.item_id, x.error])));
    },
  });
  return (
    <div className="content">
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, marginRight: 8 }}>Sipariş önerileri</h2>
          <span className="muted">Stok ve açık stok siparişleri toplamı minimumun altında kalan kartlar.</span>
          <span style={{ flex: 1 }} />
          {canOrder && (
            <button className="btn primary" disabled={create.isPending || !chosen.length || chosen.some((r) => !numOrNull(pick(r).qty))} onClick={() => create.mutate()}>
              Taslak sipariş oluştur ({chosen.length})
            </button>
          )}
        </div>
        {created.length > 0 && (
          <p>Oluşturulan taslaklar: {created.map((o, i) => (
            <span key={o.id}>{i > 0 && ", "}<Link to={`/purchasing?po=${o.id}`}>{o.no}</Link> <span className="muted">({o.firm_name}, {o.line_count} kalem)</span></span>
          ))}</p>
        )}
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table erp-lines">
              <thead>
                <tr>
                  {canOrder && <th><input type="checkbox" aria-label="Tümünü seç" checked={allOn}
                    onChange={() => setPicks(Object.fromEntries(rows.map((r) => [r.item_id, { ...picks[r.item_id], on: !allOn }])))} /></th>}
                  <th>Kod</th><th>Ad</th><th className="num">Stok</th><th className="num">Siparişte</th><th className="num">Minimum</th>
                  <th className="num">Önerilen</th><th>Tedarikçi</th><th className="num">Son fiyat</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const p = pick(r);
                  return (
                    <tr key={r.item_id}>
                      {canOrder && <td><input type="checkbox" aria-label={`${r.code} seç`} checked={p.on} onChange={(e) => set(r.item_id, { on: e.target.checked })} /></td>}
                      <td className="mono">{r.code}</td>
                      <td>{r.name}</td>
                      <td className="num">{fmtQty(r.qty)} {r.unit}</td>
                      <td className="num">{fmtQty(r.on_order)}</td>
                      <td className="num">{fmtQty(r.min_qty)}</td>
                      <td className="num">
                        {canOrder ? <input style={{ width: 80 }} inputMode="decimal" aria-label={`${r.code} miktar`} value={p.qty} onChange={(e) => set(r.item_id, { qty: e.target.value })} /> : fmtQty(r.suggested_qty)}
                      </td>
                      <td style={{ minWidth: 180 }}>
                        {canOrder ? <FirmSelect kind="supplier" value={p.firm} onChange={(firm) => set(r.item_id, { firm })} /> : r.firm_name}
                        {errors[r.item_id] && <div className="error">{errors[r.item_id]}</div>}
                        {r.firm_missing && <div className="muted">Tercih edilen firma silinmiş veya pasif.</div>}
                      </td>
                      <td className="num">{r.last_price == null ? "" : fmtMoney(r.last_price, r.last_currency ?? undefined)}</td>
                    </tr>
                  );
                })}
                {!rows.length && <tr><td colSpan={9} className="muted">Öneri yok: tüm kartlar minimumun üstünde.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function MovesTable({ rows, showItem }: { rows: StockMove[]; showItem?: boolean }) {
  return (
    <table className="simple erp-table">
      <thead>
        <tr>
          <th>Tarih</th>{showItem && <th>Kod</th>}<th>Hareket</th><th className="num">Miktar</th><th className="num">Bakiye</th>
          <th className="num">Birim maliyet</th><th>Proje</th><th>Belge</th><th>Not</th><th>Kullanıcı</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => (
          <tr key={m.id}>
            <td>{fmtDate(m.ts)}</td>
            {showItem && <td className="mono" title={m.name ?? ""}>{m.code}</td>}
            <td>{m.kind_label}</td>
            <td className="num" style={{ color: m.qty < 0 ? "var(--danger)" : "var(--ok)" }}>{m.qty > 0 ? "+" : ""}{fmtQty(m.qty)}</td>
            <td className="num">{fmtQty(m.balance)}</td>
            <td className="num">{fmtMoney(m.unit_cost)}</td>
            <td>{m.project_name ?? ""}</td>
            <td>{m.ref}</td>
            <td className="muted">{m.note}</td>
            <td>{m.username}</td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={10} className="muted">Hareket yok.</td></tr>}
      </tbody>
    </table>
  );
}

function LedgerModal({ item, onClose }: { item: StockItem; onClose: () => void }) {
  const q = useQuery({ queryKey: ["stock-moves", item.id], queryFn: () => api.get<StockMove[]>(`/stock/${item.id}/moves`) });
  return (
    <Modal wide title={`Hareketler: ${item.code}`} onClose={onClose}>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && <div className="adm-scroll"><MovesTable rows={q.data} /></div>}
    </Modal>
  );
}

function MovesTab() {
  const [project, setProject] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["stock-moves", "all", project ?? 0],
    queryFn: () => api.get<StockMove[]>(`/stock-moves?limit=500${project ? `&project_id=${project}` : ""}`),
  });
  return (
    <div className="content">
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <ProjectSelect value={project} onChange={setProject} emptyLabel="Tüm projeler" />
          <span className="muted">Son 500 hareket</span>
        </div>
        <Loading error={q.error} loading={q.isLoading} />
        {q.data && <div className="adm-scroll"><MovesTable rows={q.data} showItem /></div>}
      </div>
    </div>
  );
}
