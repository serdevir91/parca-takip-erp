import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { fmtDay } from "../erp/common";
import { Field, Loading } from "./shared";
import { LOCALE, tx } from "../../api/i18n";

type Holiday = { id: number; day: string; name: string; half_day: boolean };

/** Resmi tatiller: the expected hours of attendance and the leave day count skip these days. */
export default function HolidaysTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [day, setDay] = useState("");
  const [until, setUntil] = useState("");
  const [name, setName] = useState("");
  const [half, setHalf] = useState(false);
  const [del, setDel] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["holidays", year], queryFn: () => api.get<Holiday[]>(`/holidays?year=${year}`) });
  const done = (text: string) => {
    toast(text);
    for (const k of ["holidays", "attendance", "leave"]) void qc.invalidateQueries({ queryKey: [k] });
  };
  const add = useMutation({
    mutationFn: () => api.post<{ added: number }>("/holidays", { day, until: until || null, name: name.trim(), half_day: half }),
    onSuccess: (r) => { done(tx("{0} gün eklendi", r.added.toLocaleString(LOCALE))); setDay(""); setUntil(""); setName(""); setHalf(false); },
    onError: (e) => toast(errText(e), true),
  });
  const fixed = useMutation({
    mutationFn: () => api.post<{ added: number }>("/holidays/fixed", { year }),
    onSuccess: (r) => done(r.added ? tx("{0} sabit tatil eklendi", r.added.toLocaleString(LOCALE)) : tx("Sabit tatillerin hepsi zaten listede")),
    onError: (e) => toast(errText(e), true),
  });
  const toggle = useMutation({
    mutationFn: (h: Holiday) => api.put(`/holidays/${h.id}`, { name: h.name, half_day: !h.half_day }),
    onSuccess: () => done(tx("Kaydedildi")),
    onError: (e) => toast(errText(e), true),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/holidays/${id}`),
    onSuccess: () => { setDel(null); done(tx("Silindi")); },
    onError: (e) => toast(errText(e), true),
  });
  const total = useMemo(() => (q.data ?? []).reduce((s, h) => s + (h.half_day ? 0.5 : 1), 0), [q.data]);
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{tx("Resmi tatiller")}</h2>
      <p className="muted">
        {tx("Listedeki günler beklenen mesaiden ve izin gün sayısından düşer. Yarım gün, beklenen mesainin yarısını düşer. Dini bayramların tarihi her yıl değiştiği için onları burada elle girin.")}
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <label className="row">{tx("Yıl")}
          <input type="number" style={{ width: 90 }} min={2000} max={2100} value={year}
            onChange={(e) => { const y = Number(e.target.value); if (y >= 2000 && y <= 2100) setYear(y); }} />
        </label>
        <button className="btn" disabled={fixed.isPending} onClick={() => fixed.mutate()}>{tx("{0} sabit tatillerini ekle", year)}</button>
        <span className="muted">{tx("{0} kayıt · {1} gün", (q.data?.length ?? 0).toLocaleString(LOCALE), total.toLocaleString(LOCALE))}</span>
      </div>
      <div className="adm-form two">
        <Field label={tx("Tarih")}><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label={tx("Bitiş (birkaç günse)")} hint={tx("Bayram gibi aralıklar için. Tek gün için boş bırakın.")}>
          <input type="date" min={day || undefined} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <Field label={tx("Ad")}><input maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder={tx("Ramazan Bayramı")} /></Field>
        <label className="row" style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={half} onChange={(e) => setHalf(e.target.checked)} />{" "}{tx("Yarım gün (arife)")}
        </label>
      </div>
      <div className="row" style={{ margin: "10px 0 14px" }}>
        <button className="btn primary" disabled={add.isPending || !day || !name.trim()} onClick={() => add.mutate()}>{tx("Ekle")}</button>
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && (
        <div className="adm-scroll">
          <table className="simple">
            <thead><tr><th>{tx("Tarih")}</th><th>{tx("Ad")}</th><th>{tx("Süre")}</th><th></th></tr></thead>
            <tbody>
              {q.data.map((h) => (
                <tr key={h.id}>
                  <td>{fmtDay(h.day)}</td><td>{tx(h.name)}</td>
                  <td><button className="btn small" disabled={toggle.isPending} onClick={() => toggle.mutate(h)}>{h.half_day ? tx("Yarım gün") : tx("Tam gün")}</button></td>
                  <td>
                    {del === h.id
                      ? <span className="row"><button className="btn small danger" disabled={remove.isPending} onClick={() => remove.mutate(h.id)}>{tx("Silinsin")}</button>
                        <button className="btn small" onClick={() => setDel(null)}>{tx("Vazgeç")}</button></span>
                      : <button className="btn small" onClick={() => setDel(h.id)}>{tx("Sil")}</button>}
                  </td>
                </tr>
              ))}
              {!q.data.length && <tr><td colSpan={4} className="muted empty">{tx("Bu yıl için tatil girilmemiş.")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
