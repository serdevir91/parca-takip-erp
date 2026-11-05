import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api/client";
import { Page, useProject } from "../components/Layout";
import { errText } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import type { Project } from "../types";
import { LOCALE, tx } from "../api/i18n";

// ---------- API types (backend/app/services/state.py ProjectView.dashboard) ----------
type StatusCount = { status: string; count: number; qty: number; color: string };
type GroupRow = { group: string; total: number; done: number; pct: number; by_status: Record<string, number> };
type Kpi = {
  unique_parts: number; total_qty: number;
  imalat_count: number; imalat_qty: number; imalat_done: number; imalat_done_qty: number;
  imalat_todo: number; imalat_todo_qty: number;
  hazir_count: number; hazir_qty: number; hazir_delivered: number;
  montaj_count: number; montaj_done: number; no_temin: number;
  fastener_unique: number; fastener_qty: number; fastener_delivered: number;
  missing_rows: number; missing_qty: number; imalat_no_drawing: number; new_parts: number;
  progress_pct: number;
};
type DashboardData = {
  project: Project;
  version: { id: number; seq: number; filename: string; approved_at: string | null } | null;
  kpi: Kpi;
  imalat: StatusCount[]; hazir: StatusCount[]; montaj: StatusCount[];
  groups: GroupRow[];
  status_order: string[];
  status_colors: Record<string, string>;
  fastener_by_type: { type: string; count: number; qty: number }[];
};
// GET /projects/{pid}/fasteners (backend/app/api/fasteners.py summary); only totals/colors are used here
type FastenerSummary = {
  statuses: string[]; colors: Record<string, string>;
  totals: { unique: number; total_qty: number; by_status: Record<string, number> };
};

type Slice = { name: string; value: number; color: string; qty?: number };

// Categorical palette for fastener types (no backend colours); mid-tone, readable on light and dark.
const TYPE_PALETTE = ["#5B8DEF", "#F2A541", "#4CB79A", "#C77DDB", "#E86A6A", "#8C9BAB", "#D4B83A", "#47A8C9"];
const FALLBACK_COLOR = "#9AA3B2";

const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString(LOCALE);
const pctText = (n: number) => `%${n.toLocaleString(LOCALE, { maximumFractionDigits: 1 })}`;
const ratio = (a: number, b: number) => (b ? Math.round((1000 * a) / b) / 10 : 0);
const hex = (c: string | undefined) => (c ? `#${c}` : FALLBACK_COLOR);
const dateText = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(LOCALE) : "—");

export default function Dashboard() {
  const { pid } = useProject();
  const q = useQuery({
    queryKey: ["dashboard", pid],
    queryFn: () => api.get<DashboardData>(`/projects/${pid}/dashboard`),
    enabled: !!pid,
    refetchInterval: 60_000,
  });
  const hasBom = !!q.data?.version;
  const fq = useQuery({
    queryKey: ["fasteners", pid, "summary"],
    queryFn: () => api.get<FastenerSummary>(`/projects/${pid}/fasteners`),
    enabled: !!pid && hasBom,
    refetchInterval: 60_000,
  });

  if (q.isLoading) return <Page><div className="muted">{tx("Yükleniyor…")}</div></Page>;
  if (q.isError) return <Page><div className="card error">{tx("Proje özeti yüklenemedi: {0}", errText(q.error))}</div></Page>;
  const d = q.data;
  if (!d) return <Page><div className="muted">{tx("Veri yok.")}</div></Page>;

  return (
    <Page>
      <div className="dash">
        <div className="row dash-head">
          <h2 style={{ margin: 0 }}>{tx("{0} · Proje Özeti", d.project.name)}</h2>
          <span className="spacer" style={{ flex: 1 }} />
          {q.isFetching && <span className="muted">{tx("Güncelleniyor…")}</span>}
        </div>
        <VersionInfo pid={pid} d={d} />
        {d.version ? <Body pid={pid} d={d} fast={fq.data} fastErr={fq.isError ? errText(fq.error) : null} /> : (
          <div className="card dash-empty">
            <h3>{tx("Onaylanmış BOM sürümü yok")}</h3>
            <p className="muted">{tx("Bu projede henüz onaylanmış bir BOM sürümü bulunmuyor. Özet, BOM onaylandıktan sonra canlı veriden hesaplanır.")}</p>
            <Link className="btn primary" to={`/p/${pid}/bom`}>{tx("BOM Sürümleri")}</Link>
          </div>
        )}
      </div>
    </Page>
  );
}

function VersionInfo({ pid, d }: { pid: number; d: DashboardData }) {
  const cur = d.project.current_version;
  const pending = d.project.pending_versions || 0;
  return (
    <>
      {d.version && (
        <div className="card row dash-version">
          <span><b>{tx("Güncel BOM:")}</b>{" "}{tx("Sürüm {0}", fmt(d.version.seq))}</span>
          <span className="muted" title={d.version.filename}>{d.version.filename}</span>
          <span className="muted">
            {tx("Onaylayan:")}{" "}{cur?.approved_by ? String(cur.approved_by) : "—"} · {dateText(d.version.approved_at ?? cur?.approved_at)}
          </span>
          <span style={{ flex: 1 }} />
          <Link className="btn small" to={`/p/${pid}/bom`}>{tx("BOM Sürümleri")}</Link>
        </div>
      )}
      {pending > 0 && (
        <div className="card dash-pending">
          <span className="badge warn">{tx("Onay bekliyor")}</span>{" "}{tx("{0} BOM sürümü onay bekliyor. Onaylanana kadar özet güncel sürüme göre hesaplanır.", fmt(pending))}{" "}
          <Link to={`/p/${pid}/bom`}>{tx("BOM Sürümleri sayfasına git")}</Link>
        </div>
      )}
    </>
  );
}

function Body({ pid, d, fast, fastErr }: { pid: number; d: DashboardData; fast?: FastenerSummary; fastErr: string | null }) {
  const k = d.kpi;
  const imalatPct = ratio(k.imalat_done, k.imalat_count);

  const slices = useMemo(() => {
    const fromCounts = (rows: StatusCount[]): Slice[] =>
      rows.map((r) => ({ name: tx(r.status), value: r.count, qty: r.qty, color: hex(r.color) }));
    const types: Slice[] = d.fastener_by_type.map((t, i) => ({
      name: t.type ? tx(t.type) : tx("Diğer"), value: t.count, qty: t.qty, color: TYPE_PALETTE[i % TYPE_PALETTE.length],
    }));
    let order: Slice[];
    if (fast) {
      order = fast.statuses.map((s) => ({ name: tx(s), value: fast.totals.by_status[s] ?? 0, color: hex(fast.colors[s]) }));
    } else {
      // Fallback from KPI until the fastener summary arrives: delivered vs. not delivered.
      order = [
        { name: tx("Teslim Edilmedi"), value: k.fastener_unique - k.fastener_delivered, color: hex("FFC7CE") },
        { name: tx("Teslim Edildi"), value: k.fastener_delivered, color: hex("C6EFCE") },
      ];
    }
    return { imalat: fromCounts(d.imalat), hazir: fromCounts(d.hazir), montaj: fromCounts(d.montaj), types, order };
  }, [d, fast, k.fastener_unique, k.fastener_delivered]);

  return (
    <>
      <div className="grid kpis">
        <KpiCard label={tx("İmalat ilerlemesi")} value={pctText(imalatPct)} pct={imalatPct}
          sub={tx("Üretilen {0} / {1} parça · {2} / {3} adet", fmt(k.imalat_done), fmt(k.imalat_count), fmt(k.imalat_done_qty), fmt(k.imalat_qty))} />
        <KpiCard label={tx("Genel ilerleme")} value={pctText(k.progress_pct)} pct={k.progress_pct}
          sub={tx("İmalat + hazır alım + montaj tamamlanan")} />
        <KpiCard label={tx("Toplam parça")} value={fmt(k.unique_parts)} sub={`${fmt(k.total_qty)} adet`} to={`/p/${pid}/parts`} />
        <KpiCard label={tx("Hazır alım teslim")} value={`${fmt(k.hazir_delivered)} / ${fmt(k.hazir_count)}`}
          pct={ratio(k.hazir_delivered, k.hazir_count)} sub={`${fmt(k.hazir_qty)} adet`} />
        <KpiCard label={tx("Montaj")} value={`${fmt(k.montaj_done)} / ${fmt(k.montaj_count)}`}
          pct={ratio(k.montaj_done, k.montaj_count)} sub={tx("Montajlanan / toplam")} />
        <KpiCard label={tx("Bağlantı elemanı")} value={`${fmt(k.fastener_qty)} adet`}
          pct={ratio(k.fastener_delivered, k.fastener_unique)}
          sub={tx("{0} kalem · teslim {1} kalem", fmt(k.fastener_unique), fmt(k.fastener_delivered))} to={`/p/${pid}/fasteners`} />
        <KpiCard label={tx("Eksik")} value={`${fmt(k.missing_qty)} adet`} sub={tx("{0} satır", fmt(k.missing_rows))}
          tone={k.missing_rows ? "warn" : undefined} to={`/p/${pid}/parts`} />
        <KpiCard label={tx("Resmi olmayan imalat parçası")} value={fmt(k.imalat_no_drawing)}
          tone={k.imalat_no_drawing ? "warn" : undefined} to={`/p/${pid}/drawings`} />
        <KpiCard label={tx("Temin seçilmedi")} value={fmt(k.no_temin)} tone={k.no_temin ? "err" : undefined} to={`/p/${pid}/parts`} />
        <KpiCard label={tx("Yeni parça")} value={fmt(k.new_parts)} sub={tx("Son sürümle gelen")} />
      </div>

      <div className="dash-pies">
        <PieCard title={tx("İmalat durumu")} data={slices.imalat} unit={tx("parça")} />
        <PieCard title={tx("Hazır alım sipariş durumu")} data={slices.hazir} unit={tx("parça")} />
        <PieCard title={tx("Montaj durumu")} data={slices.montaj} unit="montaj" />
        <PieCard title={tx("Bağlantı elemanı türleri")} data={slices.types} unit="kalem" />
        <PieCard title={tx("Bağlantı elemanı sipariş durumu")} data={slices.order} unit="kalem"
          note={fastErr ? tx("Sipariş durumları alınamadı: {0}", fastErr) : !fast ? tx("Yükleniyor…") : undefined} />
      </div>

      <GroupSection d={d} />
    </>
  );
}

function KpiCard({ label, value, sub, pct, tone, to }: {
  label: string; value: string; sub?: string; pct?: number; tone?: "warn" | "err"; to?: string;
}) {
  const body = (
    <>
      <div className="label">{label}</div>
      <div className={`value${tone === "err" ? " error" : tone === "warn" ? " warn" : ""}`}>{value}</div>
      {pct !== undefined && <div className="progress" title={pctText(pct)}><div style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>}
      {sub && <div className="muted dash-sub">{sub}</div>}
    </>
  );
  return to ? <Link className="card kpi dash-kpi-link" to={to}>{body}</Link> : <div className="card kpi">{body}</div>;
}

const tooltipStyle: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--fg)",
};

function PieCard({ title, data, unit, note }: { title: string; data: Slice[]; unit: string; note?: string }) {
  const total = data.reduce((s, x) => s + x.value, 0);
  const shown = data.filter((x) => x.value > 0);
  return (
    <div className="card dash-pie">
      <div className="dash-card-title">{title}</div>
      {total === 0 ? <div className="muted dash-pie-empty">{note ?? tx("Veri yok")}</div> : (
        <div className="dash-pie-body">
          <div className="dash-pie-chart">
            <ResponsiveContainer width="100%" height={170}>
              <PieChart>
                <Pie data={shown} dataKey="value" nameKey="name" innerRadius={45} outerRadius={78}
                  stroke="var(--surface)" strokeWidth={2} isAnimationActive={false}>
                  {shown.map((x) => <Cell key={x.name} fill={x.color} />)}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: "var(--fg)" }}
                  formatter={(v: number, n: string) => [`${fmt(v)} ${unit} (${pctText(ratio(v, total))})`, n]} />
              </PieChart>
            </ResponsiveContainer>
            <div className="dash-pie-center"><b>{fmt(total)}</b><span className="muted">{unit}</span></div>
          </div>
          <ul className="dash-legend">
            {data.map((x) => (
              <li key={x.name}>
                <span className="dash-swatch" style={{ background: x.color }} />
                <span className="dash-legend-name">{x.name}</span>
                <span className="dash-legend-val">{fmt(x.value)} <span className="muted">({pctText(ratio(x.value, total))})</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {note && total > 0 && <div className="muted dash-sub">{note}</div>}
    </div>
  );
}

function GroupSection({ d }: { d: DashboardData }) {
  // Only statuses that occur in at least one main group, in backend order.
  const statuses = useMemo(() => {
    const present = new Set<string>();
    for (const g of d.groups) for (const [s, n] of Object.entries(g.by_status)) if (n) present.add(s);
    const ordered = d.status_order.filter((s) => present.has(s));
    for (const s of present) if (!ordered.includes(s)) ordered.push(s);
    return ordered;
  }, [d.groups, d.status_order]);

  const barData = useMemo(
    () => d.groups.map((g) => ({ group: tx(g.group), ...Object.fromEntries(statuses.map((s) => [s, g.by_status[s] ?? 0])) })),
    [d.groups, statuses],
  );

  const totals = useMemo(() => {
    const t: Record<string, number> = {};
    let total = 0, done = 0;
    for (const g of d.groups) {
      total += g.total; done += g.done;
      for (const s of statuses) t[s] = (t[s] ?? 0) + (g.by_status[s] ?? 0);
    }
    return { byStatus: t, total, done };
  }, [d.groups, statuses]);

  if (!d.groups.length) {
    return <div className="card"><div className="dash-card-title">{tx("Ana gruplar")}</div><div className="muted">{tx("Ana grup verisi yok.")}</div></div>;
  }

  const chartHeight = Math.max(160, d.groups.length * 30 + 60);

  return (
    <>
      <div className="card dash-groups">
        <div className="dash-card-title">{tx("Ana grup tablosu")}</div>
        <div className="dash-table-wrap">
          <table className="simple">
            <thead>
              <tr>
                <th>{tx("Ana Grup")}</th>
                <th className="num">{tx("Toplam")}</th>
                {statuses.map((s) => <th key={s} className="num" style={statusStyle(d.status_colors[s])}>{tx(s)}</th>)}
                <th className="num">{tx("Tamamlanan")}</th>
                <th style={{ minWidth: 160 }}>{tx("İlerleme")}</th>
              </tr>
            </thead>
            <tbody>
              {d.groups.map((g) => (
                <tr key={g.group}>
                  <td>{tx(g.group)}</td>
                  <td className="num">{fmt(g.total)}</td>
                  {statuses.map((s) => {
                    const n = g.by_status[s] ?? 0;
                    return <td key={s} className="num" style={n ? statusStyle(d.status_colors[s]) : undefined}>{n ? fmt(n) : <span className="muted">0</span>}</td>;
                  })}
                  <td className="num">{fmt(g.done)}</td>
                  <td><ProgressCell pct={g.pct} /></td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>{tx("Toplam")}</th>
                <th className="num">{fmt(totals.total)}</th>
                {statuses.map((s) => <th key={s} className="num">{fmt(totals.byStatus[s])}</th>)}
                <th className="num">{fmt(totals.done)}</th>
                <th><ProgressCell pct={ratio(totals.done, totals.total)} /></th>
              </tr>
            </tfoot>
          </table>
        </div>
        <div className="muted dash-sub">{tx("Bir parça birden fazla ana grupta kullanılıyorsa her grupta ayrı sayılır.")}</div>
      </div>

      <div className="card dash-bars">
        <div className="dash-card-title">{tx("Ana grup başına durum dağılımı")}</div>
        <div className="row dash-bar-legend">
          {statuses.map((s) => (
            <span key={s} className="row" style={{ gap: 4 }}>
              <span className="dash-swatch" style={{ background: hex(d.status_colors[s]) }} />{tx(s)}
            </span>
          ))}
        </div>
        <div className="dash-chart-text">
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart data={barData} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={6}>
              <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} tick={{ fill: "currentColor", fontSize: 12 }}
                stroke="currentColor" tickFormatter={(v: number) => fmt(v)} />
              <YAxis type="category" dataKey="group" width={170} interval={0} stroke="currentColor"
                tick={{ fill: "currentColor", fontSize: 12 }}
                tickFormatter={(v: string) => (v.length > 24 ? `${v.slice(0, 23)}…` : v)} />
              <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: "var(--fg)" }} labelStyle={{ color: "var(--fg)", fontWeight: 600 }}
                cursor={{ fill: "var(--surface-2)", opacity: 0.6 }} formatter={(v: number, n: string) => [fmt(v), n]} />
              {statuses.map((s) => (
                <Bar key={s} dataKey={s} name={tx(s)} stackId="st" fill={hex(d.status_colors[s])} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  );
}

function ProgressCell({ pct }: { pct: number }) {
  return (
    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      <div className="progress" style={{ flex: 1, minWidth: 80 }}><div style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>
      <span style={{ minWidth: 44, textAlign: "right" }}>{pctText(pct)}</span>
    </div>
  );
}
