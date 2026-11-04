import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Field, ListEditor, Loading } from "./shared";

type StatusRules = { big_drop_ratio: number; [k: string]: unknown };
type Settings = {
  part_no_patterns: string[]; purchased_assemblies: string[]; status_rules: StatusRules; material_status_choices: string[];
};
type Key = keyof Settings;

/** JS RegExp is close enough to Python re for a first check; the server validates for real. */
function regexError(p: string): string | null {
  try {
    new RegExp(p.replace(/\(\?P</g, "(?<"));
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : "Geçersiz desen";
  }
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export default function SettingsTab() {
  const q = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api.get<Settings>("/admin/settings") });
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && <SettingsForm data={q.data} />}
    </>
  );
}

function SettingsForm({ data }: { data: Settings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [patterns, setPatterns] = useState(data.part_no_patterns);
  const [purchased, setPurchased] = useState(data.purchased_assemblies);
  const [pct, setPct] = useState(String(Math.round((data.status_rules?.big_drop_ratio ?? 0.1) * 1000) / 10));
  const [testNo, setTestNo] = useState("");
  const [materials, setMaterials] = useState(data.material_status_choices);

  // Server state changed (saved or refetched): reset drafts of that key.
  useEffect(() => setPatterns(data.part_no_patterns), [data.part_no_patterns]);
  useEffect(() => setPurchased(data.purchased_assemblies), [data.purchased_assemblies]);
  useEffect(() => setMaterials(data.material_status_choices), [data.material_status_choices]);
  useEffect(() => setPct(String(Math.round((data.status_rules?.big_drop_ratio ?? 0.1) * 1000) / 10)), [data.status_rules]);

  const save = useMutation({
    mutationFn: ({ key, value }: { key: Key; value: unknown }) => api.put<Settings>(`/admin/settings/${key}`, { value }),
    onSuccess: (d) => {
      qc.setQueryData(["admin", "settings"], d);
      void qc.invalidateQueries({ queryKey: ["project"] });
      toast("Ayar kaydedildi");
    },
    onError: (e) => toast(errText(e), true),
  });

  const pctNum = Number(pct.replace(",", "."));
  const pctErr = !isFinite(pctNum) || pctNum <= 0 || pctNum > 100 ? "0 ile 100 arasında bir yüzde girin" : null;
  const patErr = patterns.some((p) => regexError(p)) || !patterns.length;
  const tested = testNo.trim()
    ? patterns.filter((p) => !regexError(p)).some((p) => new RegExp(`^(?:${p.replace(/\(\?P</g, "(?<")})`).test(testNo.trim()))
    : null;

  return (
    <div className="grid adm-settings">
      <div className="card">
        <h3>Parça numarası desenleri</h3>
        <p className="muted">
          BOM satırındaki dosya adının parça numarası sayılması için başından eşleşmesi gereken düzenli ifadeler (regex).
          Hiçbir desene uymayan ve bağlantı elemanı olarak tanınmayan parçalar "standart dışı isim" uyarısı alır.
        </p>
        <ListEditor value={patterns} onChange={setPatterns} placeholder="örn. T\d{2}_\d{4}_\d{4}" validate={regexError} mono />
        <div className="row" style={{ marginTop: 8 }}>
          <input placeholder="Parça numarası dene…" value={testNo} onChange={(e) => setTestNo(e.target.value)} style={{ fontFamily: "ui-monospace, Consolas, monospace" }} />
          {tested !== null && (tested ? <span className="ok">✓ Desene uyuyor</span> : <span className="error">✗ Hiçbir desene uymuyor</span>)}
        </div>
        <SaveRow dirty={!same(patterns, data.part_no_patterns)} disabled={patErr} pending={save.isPending}
          onReset={() => setPatterns(data.part_no_patterns)} onSave={() => save.mutate({ key: "part_no_patterns", value: patterns })} />
      </div>

      <div className="card">
        <h3>Hazır alım montajları</h3>
        <p className="muted">
          Satın alınan montajların parça numaraları. Bu montajlar parça listesinde tek satır olarak görünür; alt parçaları imalat sayılmaz.
        </p>
        <ListEditor value={purchased} onChange={setPurchased} placeholder="Montaj parça numarası" mono />
        <SaveRow dirty={!same(purchased, data.purchased_assemblies)} pending={save.isPending}
          onReset={() => setPurchased(data.purchased_assemblies)} onSave={() => save.mutate({ key: "purchased_assemblies", value: purchased })} />
      </div>

      <div className="card">
        <h3>Malzeme durumları</h3>
        <p className="muted">
          Parça listesindeki Malzeme Durumu seçenekleri. Bir değeri silerseniz o değerdeki parçalar değişmez; durum listesi kuralları
          silinen değeri kullanıyorsa önce kuralı düzeltin.
        </p>
        <ListEditor value={materials} onChange={setMaterials} placeholder="Malzeme durumu" />
        <SaveRow dirty={!same(materials, data.material_status_choices)} disabled={!materials.length} pending={save.isPending}
          onReset={() => setMaterials(data.material_status_choices)}
          onSave={() => save.mutate({ key: "material_status_choices", value: materials })} />
      </div>

      <div className="card">
        <h3>Durum kuralları</h3>
        <Field label="Büyük bağlantı elemanı düşüşü eşiği (%)"
          hint="Yeni BOM sürümünde toplam bağlantı elemanı adedi bu oranda veya daha fazla azalırsa karşılaştırma ekranında uyarı gösterilir.">
          <input type="number" min={0.1} max={100} step={0.5} value={pct} onChange={(e) => setPct(e.target.value)} style={{ width: 120 }} />
        </Field>
        {pctErr && <div className="error">{pctErr}</div>}
        <SaveRow dirty={!pctErr && Math.abs(pctNum / 100 - (data.status_rules?.big_drop_ratio ?? 0.1)) > 1e-9} disabled={!!pctErr}
          pending={save.isPending}
          onReset={() => setPct(String(Math.round((data.status_rules?.big_drop_ratio ?? 0.1) * 1000) / 10))}
          onSave={() => save.mutate({ key: "status_rules", value: { ...data.status_rules, big_drop_ratio: pctNum / 100 } })} />
      </div>
    </div>
  );
}

function SaveRow({ dirty, disabled, pending, onSave, onReset }: {
  dirty: boolean; disabled?: boolean; pending: boolean; onSave: () => void; onReset: () => void;
}) {
  return (
    <div className="row" style={{ marginTop: 10 }}>
      <button className="btn primary" disabled={!dirty || disabled || pending} onClick={onSave}>Kaydet</button>
      <button className="btn" disabled={!dirty || pending} onClick={onReset}>Geri al</button>
      {dirty && <span className="warn">Kaydedilmemiş değişiklik var</span>}
    </div>
  );
}
