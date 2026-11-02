import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Field, ListEditor, Loading, fmtNum } from "./shared";

type T35Rule = { field: string; all: string[]; value: string; priority: number; active?: boolean };
type T35Cfg = {
  rules: T35Rule[]; default_progress: string; skip_note: string[]; manufacturers: string[];
  fields: string[]; progress_choices: string[]; material_status_choices: string[]; mark_note: string;
};
/** Editable row: keywords kept as raw text so commas can be typed freely. */
type Draft = { key: number; field: string; kw: string; value: string; priority: number; active: boolean };

const QK = ["t35config"];
const FIELD_TR: Record<string, string> = { progress: "İlerleme", material_status: "Malzeme durumu" };
let seq = 0;

const toDrafts = (rules: T35Rule[]): Draft[] =>
  rules.map((r) => ({ key: ++seq, field: r.field, kw: (r.all ?? []).join(", "), value: r.value, priority: r.priority ?? 100, active: r.active ?? true }));
const kwList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const toRules = (d: Draft[]) => d.map((r) => ({ field: r.field, all: kwList(r.kw), value: r.value, priority: r.priority, active: r.active }));

export default function T35ConfigTab() {
  const q = useQuery({ queryKey: QK, queryFn: () => api.get<T35Cfg>("/t35/config") });
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && <T35Form data={q.data} />}
    </>
  );
}

function T35Form({ data }: { data: T35Cfg }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [rules, setRules] = useState(() => toDrafts(data.rules));
  const [defProg, setDefProg] = useState(data.default_progress);
  const [skip, setSkip] = useState(data.skip_note);

  const reset = () => {
    setRules(toDrafts(data.rules));
    setDefProg(data.default_progress);
    setSkip(data.skip_note);
  };
  useEffect(reset, [data]); // reset drafts whenever server data changes

  const save = useMutation({
    mutationFn: () => api.put<T35Cfg>("/t35/config", { rules: toRules(rules), default_progress: defProg, skip_note: skip }),
    onSuccess: (d) => {
      qc.setQueryData(QK, d);
      toast("T-35 ayarları kaydedildi");
    },
    onError: (e) => toast(errText(e), true),
  });

  const choices = (f: string) => (f === "progress" ? data.progress_choices : data.material_status_choices);
  const upd = (key: number, patch: Partial<Draft>) =>
    setRules((rs) => rs.map((r) => {
      if (r.key !== key) return r;
      const n = { ...r, ...patch };
      // Field changed: the old value may not exist in the new choice list.
      if (patch.field && !choices(n.field).includes(n.value)) n.value = choices(n.field)[0] ?? "";
      return n;
    }));
  const add = () => {
    const maxP = rules.reduce((m, r) => Math.max(m, r.priority), 0);
    setRules((rs) => [...rs, { key: ++seq, field: "progress", kw: "", value: data.progress_choices[0] ?? "", priority: maxP + 10, active: true }]);
  };

  const dirty =
    JSON.stringify(toRules(rules)) !== JSON.stringify(toRules(toDrafts(data.rules))) ||
    defProg !== data.default_progress || JSON.stringify(skip) !== JSON.stringify(data.skip_note);
  const badRow = rules.findIndex((r) => !kwList(r.kw).length || !choices(r.field).includes(r.value));
  const fields = data.fields?.length ? data.fields : ["progress", "material_status"];

  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="card">
        <h3>Anahtar kelime kuralları</h3>
        <p className="muted">
          T-35 listesindeki açıklama metni bir kuralın <b>tüm</b> anahtar kelimelerini içeriyorsa (büyük/küçük harf ve Türkçe karakter farkı gözetilmez)
          ilgili alan kuralın değerine ayarlanır. Her alan için düşük öncelikli kural önce denenir, ilk eşleşen kazanır.
        </p>
        <div className="adm-scroll">
          <table className="simple">
            <thead>
              <tr><th>Öncelik</th><th>Alan</th><th>Anahtar kelimeler (virgülle)</th><th>Değer</th><th>Aktif</th><th></th></tr>
            </thead>
            <tbody>
              {rules.map((r, i) => {
                const opts = choices(r.field);
                return (
                  <tr key={r.key} style={r.active ? undefined : { opacity: 0.55 }}>
                    <td><input type="number" style={{ width: 80 }} value={r.priority} onChange={(e) => upd(r.key, { priority: Number(e.target.value) || 0 })} /></td>
                    <td>
                      <select value={r.field} onChange={(e) => upd(r.key, { field: e.target.value })}>
                        {fields.map((f) => <option key={f} value={f}>{FIELD_TR[f] ?? f}</option>)}
                      </select>
                    </td>
                    <td>
                      <input style={{ width: "100%", minWidth: 240 }} value={r.kw} placeholder="örn. lazer, kesim"
                        onChange={(e) => upd(r.key, { kw: e.target.value })} />
                      {!kwList(r.kw).length && <div className="error adm-small">En az bir anahtar kelime gerekli</div>}
                    </td>
                    <td>
                      <select value={r.value} onChange={(e) => upd(r.key, { value: e.target.value })}>
                        {!opts.includes(r.value) && <option value={r.value}>{r.value || "—"} (geçersiz)</option>}
                        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </td>
                    <td><input type="checkbox" checked={r.active} onChange={(e) => upd(r.key, { active: e.target.checked })} /></td>
                    <td>
                      <button className="btn small danger" title={`${fmtNum(i + 1)}. kuralı kaldır`}
                        onClick={() => setRules((rs) => rs.filter((x) => x.key !== r.key))}>Sil</button>
                    </td>
                  </tr>
                );
              })}
              {!rules.length && <tr><td colSpan={6} className="muted">Kural yok.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn small" onClick={add}>+ Kural ekle</button>
          <button className="btn small" onClick={() => setRules((rs) => [...rs].sort((a, b) => a.priority - b.priority))}>Önceliğe göre sırala</button>
          <span className="muted">{fmtNum(rules.length)} kural</span>
        </div>
      </div>

      <div className="card">
        <h3>Genel</h3>
        <div className="adm-form">
          <Field label="Varsayılan ilerleme" hint="Hiçbir ilerleme kuralı eşleşmezse kullanılır.">
            <select value={defProg} onChange={(e) => setDefProg(e.target.value)} style={{ maxWidth: 320 }}>
              {!data.progress_choices.includes(defProg) && <option value={defProg}>{defProg}</option>}
              {data.progress_choices.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </Field>
          <div>
            <b>Yok sayılan not metinleri</b>
            <p className="muted" style={{ margin: "4px 0 8px" }}>Bu metinlerle birebir aynı olan T-35 notları takip listesine yazılmaz.</p>
            <ListEditor value={skip} onChange={setSkip} placeholder="Not metni" />
          </div>
          {data.mark_note && (
            <div className="muted">İşaretli satırlar için eklenen not: <b>{data.mark_note}</b></div>
          )}
          <div>
            <b>Tanınan üretici firmalar</b>
            <span className="muted"> (Firmalar sekmesindeki üretici firmalardan gelir)</span>
            <div className="row" style={{ gap: 4, marginTop: 6 }}>
              {data.manufacturers.map((m) => <span key={m} className="badge">{m}</span>)}
              {!data.manufacturers.length && <span className="muted">Üretici firma tanımlı değil.</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="row adm-sticky">
        <button className="btn primary" disabled={!dirty || badRow >= 0 || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Kaydediliyor…" : "Kaydet"}
        </button>
        <button className="btn" disabled={!dirty || save.isPending} onClick={reset}>Geri al</button>
        {badRow >= 0 && <span className="error">{fmtNum(badRow + 1)}. kuralda eksik veya geçersiz alan var</span>}
        {dirty && badRow < 0 && <span className="warn">Kaydedilmemiş değişiklik var</span>}
      </div>
    </div>
  );
}
