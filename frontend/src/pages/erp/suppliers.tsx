import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Loading } from "../admin/shared";
import { fmtDay, fmtMoney, fmtRate, trIncludes } from "./common";

type PerfRow = {
  firm_id: number | null; firm_name: string; orders: number; measured: number; left_out: number; on_time: number;
  on_time_pct: number | null; avg_delay_days: number | null; spend: number; unconverted: { currency: string; amount: number }[];
  received_qty: number; returned_qty: number; return_pct: number;
};
type PricePoint = {
  date: string; po_id: number; po_no: string; qty: number; unit_price: number; currency: string; rate: number | null; base_price: number | null;
};
type PriceFirm = {
  firm_id: number | null; firm_name: string; orders: number; points: PricePoint[]; last_price: number | null; lowest_price: number | null;
};
type History = { code: string; base: string; firms: PriceFirm[]; suggestions: string[] };

const pct = (n: number | null) => (n == null ? "—" : `%${n.toLocaleString("tr-TR")}`);

/** Tedarikçiler: delivery performance per firm and price comparison per code. */
export function Suppliers() {
  const q = useQuery({ queryKey: ["suppliers", "performance"], queryFn: () => api.get<{ base: string; rows: PerfRow[] }>("/suppliers/performance") });
  const [find, setFind] = useState("");
  const rows = (q.data?.rows ?? []).filter((r) => !find.trim() || trIncludes(r.firm_name, find));
  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, marginRight: 8 }}>Tedarikçi performansı</h2>
          <input placeholder="Firma ara…" value={find} onChange={(e) => setFind(e.target.value)} />
        </div>
        <Loading error={q.error} loading={q.isLoading} />
        {q.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr><th>Firma</th><th className="num">Sipariş</th><th className="num">Zamanında</th><th className="num">Ort. gecikme</th>
                  <th className="num">Ölçülmeyen</th><th className="num">Harcama ({q.data.base})</th><th className="num">İade oranı</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.firm_id}-${r.firm_name}`}>
                    <td><b>{r.firm_name}</b></td>
                    <td className="num">{r.orders}</td>
                    <td className="num">{pct(r.on_time_pct)}{r.measured > 0 && <span className="muted"> ({r.on_time}/{r.measured})</span>}</td>
                    <td className="num">{r.avg_delay_days == null ? "—" : `${r.avg_delay_days.toLocaleString("tr-TR")} gün`}</td>
                    <td className="num">{r.left_out || ""}</td>
                    <td className="num">
                      {fmtMoney(r.spend, q.data.base)}
                      {r.unconverted.map((u) => <div key={u.currency}><span className="badge warn">+ {fmtMoney(u.amount, u.currency)} kur yok</span></div>)}
                    </td>
                    <td className="num">{r.returned_qty ? pct(r.return_pct) : "—"}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={7} className="muted empty">Gönderilmiş sipariş yok.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ marginBottom: 0 }}>
          Son kabul termin günü veya öncesindeyse sipariş zamanındadır; termini geçmiş açık sipariş gecikmiş sayılır.
          Termini olmayan, mal kabulü olmayan veya termini henüz gelmemiş siparişler ölçülmez.
        </p>
      </div>
      <PriceHistory />
    </>
  );
}

function PriceHistory() {
  const [text, setText] = useState("");
  const [code, setCode] = useState("");
  const q = useQuery({
    queryKey: ["suppliers", "price-history", code],
    queryFn: () => api.get<History>(`/suppliers/price-history?${new URLSearchParams({ code })}`),
    enabled: !!code,
  });
  const d = q.data;
  const best = d?.firms.find((f) => f.last_price != null)?.last_price;
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <form className="row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); setCode(text.trim()); }}>
        <h2 style={{ margin: 0, marginRight: 8 }}>Fiyat karşılaştırma</h2>
        <input placeholder="Parça / malzeme kodu" aria-label="Kod" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn primary" disabled={!text.trim()}>Karşılaştır</button>
      </form>
      <Loading error={q.error} loading={q.isFetching} />
      {d && !d.firms.length && (
        <p className="muted">
          {d.code} için fiyatlı sipariş yok.
          {d.suggestions.map((c) => <button key={c} className="btn small" style={{ marginLeft: 6 }} onClick={() => { setText(c); setCode(c); }}>{c}</button>)}
        </p>
      )}
      {d && !!d.firms.length && (
        <div className="adm-scroll">
          <table className="simple erp-table">
            <thead>
              <tr><th>Firma</th><th className="num">Sipariş</th><th className="num">Son fiyat ({d.base})</th><th className="num">En düşük ({d.base})</th><th>Seyir</th></tr>
            </thead>
            <tbody>
              {d.firms.map((f) => (
                <tr key={`${f.firm_id}-${f.firm_name}`}>
                  <td><b>{f.firm_name}</b>{f.last_price === best && d.firms.length > 1 && <span className="badge new" style={{ marginLeft: 6 }}>en uygun</span>}</td>
                  <td className="num">{f.orders}</td>
                  <td className="num">{f.last_price == null ? <span className="badge warn">kur yok</span> : fmtMoney(f.last_price, d.base)}</td>
                  <td className="num">{f.lowest_price == null ? "" : fmtMoney(f.lowest_price, d.base)}</td>
                  <td><Sparkline points={f.points} base={d.base} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d && !!d.firms.length && (
        <details style={{ marginTop: 10 }}>
          <summary>Sipariş sipariş fiyatlar</summary>
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead><tr><th>Tarih</th><th>Firma</th><th>Sipariş</th><th className="num">Birim fiyat</th><th className="num">Kur</th><th className="num">{d.base} karşılığı</th></tr></thead>
              <tbody>
                {d.firms.flatMap((f) => f.points.map((p) => ({ ...p, firm: f.firm_name })))
                  .sort((a, b) => b.date.localeCompare(a.date))
                  .map((p) => (
                    <tr key={`${p.po_id}-${p.firm}-${p.unit_price}`}>
                      <td>{fmtDay(p.date)}</td><td>{p.firm}</td><td className="mono">{p.po_no}</td>
                      <td className="num">{fmtMoney(p.unit_price, p.currency)}</td>
                      <td className="num">{p.currency === d.base ? "" : p.rate == null ? <span className="badge warn">kur yok</span> : fmtRate(p.rate)}</td>
                      <td className="num">{fmtMoney(p.base_price, d.base)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

/** Price over the firm's own orders: one line per table row, so no legend or axis is needed; the exact numbers are in
 *  the row and in the order list below it, and each dot names its order on hover. */
function Sparkline({ points, base }: { points: PricePoint[]; base: string }) {
  const known = points.filter((p) => p.base_price != null);
  if (known.length < 2) return <span className="muted">{known.length ? "tek sipariş" : ""}</span>;
  const W = 140, H = 36, pad = 5;
  const prices = known.map((p) => p.base_price!);
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const x = (i: number) => pad + (i * (W - 2 * pad)) / (known.length - 1);
  const y = (v: number) => (hi === lo ? H / 2 : H - pad - ((v - lo) * (H - 2 * pad)) / (hi - lo));
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${fmtMoney(prices[0], base)} ile başladı, son ${fmtMoney(prices[prices.length - 1], base)}`}>
      <polyline fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
        points={known.map((p, i) => `${x(i)},${y(p.base_price!)}`).join(" ")} />
      {known.map((p, i) => (
        <g key={`${p.po_id}-${i}`}>
          <circle cx={x(i)} cy={y(p.base_price!)} r={3} fill="var(--accent)" stroke="var(--surface)" strokeWidth={1} />
          <circle cx={x(i)} cy={y(p.base_price!)} r={9} fill="transparent">
            <title>{`${fmtDay(p.date)} · ${p.po_no} · ${fmtMoney(p.base_price, base)}`}</title>
          </circle>
        </g>
      ))}
    </svg>
  );
}
