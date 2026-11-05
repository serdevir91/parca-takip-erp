import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { fmtDay } from "../erp/common";
import { Field, Loading } from "./shared";

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
    onSuccess: (r) => { done(`${r.added.toLocaleString("tr-TR")} gün eklendi`); setDay(""); setUntil(""); setName(""); setHalf(false); },
    onError: (e) => toast(errText(e), true),
  });
  const fixed = useMutation({
    mutationFn: () => api.post<{ added: number }>("/holidays/fixed", { year }),
    onSuccess: (r) => done(r.added ? `${r.added.toLocaleString("tr-TR")} sabit tatil eklendi` : "Sabit tatillerin hepsi zaten listede"),
    onError: (e) => toast(errText(e), true),
  });
  const toggle = useMutation({
    mutationFn: (h: Holiday) => api.put(`/holidays/${h.id}`, { name: h.name, half_day: !h.half_day }),
    onSuccess: () => done("Kaydedildi"),
    onError: (e) => toast(errText(e), true),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/holidays/${id}`),
    onSuccess: () => { setDel(null); done("Silindi"); },
    onError: (e) => toast(errText(e), true),
  });
  const total = useMemo(() => (q.data ?? []).reduce((s, h) => s + (h.half_day ? 0.5 : 1), 0), [q.data]);
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Resmi tatiller</h2>
      <p className="muted">
        Listedeki günler beklenen mesaiden ve izin gün sayısından düşer. Yarım gün, beklenen mesainin yarısını düşer.
        Dini bayramların tarihi her yıl değiştiği için onları burada elle girin.
      </p>
      <div className="row" style={{ marginBottom: 12 }}>
        <label className="row">Yıl
          <input type="number" style={{ width: 90 }} min={2000} max={2100} value={year}
            onChange={(e) => { const y = Number(e.target.value); if (y >= 2000 && y <= 2100) setYear(y); }} />
        </label>
        <button className="btn" disabled={fixed.isPending} onClick={() => fixed.mutate()}>{year} sabit tatillerini ekle</button>
        <span className="muted">{(q.data?.length ?? 0).toLocaleString("tr-TR")} kayıt · {total.toLocaleString("tr-TR")} gün</span>
      </div>
      <div className="adm-form two">
        <Field label="Tarih"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Bitiş (birkaç günse)" hint="Bayram gibi aralıklar için. Tek gün için boş bırakın.">
          <input type="date" min={day || undefined} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <Field label="Ad"><input maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ramazan Bayramı" /></Field>
        <label className="row" style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={half} onChange={(e) => setHalf(e.target.checked)} /> Yarım gün (arife)
        </label>
      </div>
      <div className="row" style={{ margin: "10px 0 14px" }}>
        <button className="btn primary" disabled={add.isPending || !day || !name.trim()} onClick={() => add.mutate()}>Ekle</button>
      </div>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && (
        <div className="adm-scroll">
          <table className="simple">
            <thead><tr><th>Tarih</th><th>Ad</th><th>Süre</th><th></th></tr></thead>
            <tbody>
              {q.data.map((h) => (
                <tr key={h.id}>
                  <td>{fmtDay(h.day)}</td><td>{h.name}</td>
                  <td><button className="btn small" disabled={toggle.isPending} onClick={() => toggle.mutate(h)}>{h.half_day ? "Yarım gün" : "Tam gün"}</button></td>
                  <td>
                    {del === h.id
                      ? <span className="row"><button className="btn small danger" disabled={remove.isPending} onClick={() => remove.mutate(h.id)}>Silinsin</button>
                        <button className="btn small" onClick={() => setDel(null)}>Vazgeç</button></span>
                      : <button className="btn small" onClick={() => setDel(h.id)}>Sil</button>}
                  </td>
                </tr>
              ))}
              {!q.data.length && <tr><td colSpan={4} className="muted empty">Bu yıl için tatil girilmemiş.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
