import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal, fmtNum } from "./shared";

type Maps = Record<string, Record<string, string>>;
type Rule = {
  id: number; name: string; pattern: string; type: string; desc: string; std: string; size: string;
  d: string | null; l: string | null; maps: Maps; priority: number; active: boolean;
};
type RuleBody = Omit<Rule, "id" | "d" | "l"> & { d: string; l: string };
type Match = { type: string; desc: string; std: string; size: string; d: number | null; l: number | null; key: string; rule: string; orig: string };
type TestResult = { results: { text: string; match: Match | null }[]; matched: number; total: number };

const QK = ["admin", "fastener-rules"];
const TYPES = ["Cıvata", "Somun", "Pim", "Rondela", "Kama", "Segman"];
const mono = { fontFamily: "ui-monospace, Consolas, monospace" };

const toBody = (r: Rule): RuleBody => ({
  name: r.name, pattern: r.pattern, type: r.type, desc: r.desc ?? "", std: r.std ?? "", size: r.size ?? "",
  d: r.d ?? "", l: r.l ?? "", maps: r.maps ?? {}, priority: r.priority, active: r.active,
});

export default function FastenerRulesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const rules = useQuery({ queryKey: QK, queryFn: () => api.get<Rule[]>("/fastener-rules") });
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [q, setQ] = useState("");

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: QK });
    void qc.invalidateQueries({ queryKey: ["fasteners"] });
  };
  const reorder = useMutation({
    mutationFn: (ids: number[]) => api.post<Rule[]>("/fastener-rules/reorder", { ids }),
    onSuccess: (d) => {
      qc.setQueryData(QK, d);
      void qc.invalidateQueries({ queryKey: ["fasteners"] });
    },
    onError: (e) => toast(errText(e), true),
  });
  const update = useMutation({
    mutationFn: (r: RuleBody & { id: number }) => api.put<Rule>(`/fastener-rules/${r.id}`, { ...r, id: undefined }),
    onSuccess: invalidate,
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: (r: Rule) => api.del(`/fastener-rules/${r.id}`),
    onSuccess: () => {
      toast("Kural silindi");
      invalidate();
    },
    onError: (e) => toast(errText(e), true),
  });

  const all = rules.data ?? [];
  const move = (idx: number, dir: -1 | 1) => {
    const ids = all.map((r) => r.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    reorder.mutate(ids);
  };
  const filtered = useMemo(() => {
    const s = q.trim().toLocaleLowerCase("tr-TR");
    return all.map((r, i) => ({ r, i })).filter(({ r }) => !s || `${r.name} ${r.pattern} ${r.type} ${r.std} ${r.desc}`.toLocaleLowerCase("tr-TR").includes(s));
  }, [all, q]);

  return (
    <div className="grid" style={{ gap: 12 }}>
      <TestBox />
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <button className="btn primary" onClick={() => setEditing("new")}>+ Yeni kural</button>
          <input placeholder="Kurallarda ara…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{fmtNum(all.length)} kural · düşük öncelik önce çalışır, ilk eşleşen kural kullanılır.</span>
        </div>
        <Loading error={rules.error} loading={rules.isLoading} />
        {rules.data && (
          <div className="adm-scroll">
            <table className="simple">
              <thead>
                <tr><th>Sıra</th><th>Öncelik</th><th>Ad</th><th>Desen (regex)</th><th>Tür</th><th>Standart</th><th>Ölçü</th><th>Aktif</th><th></th></tr>
              </thead>
              <tbody>
                {filtered.map(({ r, i }) => (
                  <tr key={r.id} style={r.active ? undefined : { opacity: 0.55 }}>
                    <td>
                      <div className="row" style={{ gap: 2, flexWrap: "nowrap" }}>
                        <button className="btn small" title="Yukarı taşı" disabled={i === 0 || reorder.isPending || !!q} onClick={() => move(i, -1)}>▲</button>
                        <button className="btn small" title="Aşağı taşı" disabled={i === all.length - 1 || reorder.isPending || !!q} onClick={() => move(i, 1)}>▼</button>
                      </div>
                    </td>
                    <td>{fmtNum(r.priority)}</td>
                    <td><b>{r.name}</b>{r.desc && <div className="muted adm-small">{r.desc}</div>}</td>
                    <td style={{ ...mono, wordBreak: "break-all", maxWidth: 360 }}>{r.pattern}</td>
                    <td>{r.type}</td>
                    <td style={mono}>{r.std}</td>
                    <td style={mono}>{r.size}</td>
                    <td>
                      <input type="checkbox" checked={r.active} disabled={update.isPending}
                        onChange={() => update.mutate({ ...toBody(r), active: !r.active, id: r.id })} />
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <button className="btn small" onClick={() => setEditing(r)}>Düzenle</button>
                        <button className="btn small danger" disabled={del.isPending}
                          onClick={() => confirm(`"${r.name}" kuralı silinsin mi?`) && del.mutate(r)}>Sil</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!filtered.length && <tr><td colSpan={9} className="muted">Kural yok.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          Şablonlarda <code>{"{1}"}</code> desendeki 1. grubu, <code>{"{1|TABLO}"}</code> ise 1. grubun "TABLO" eşleme tablosundaki karşılığını verir.
          Kural değişiklikleri sonraki BOM yüklemelerinde ve bağlantı elemanı özetinde kullanılır.
        </p>
      </div>
      {editing && (
        <RuleForm rule={editing === "new" ? undefined : editing}
          nextPriority={(all.at(-1)?.priority ?? 0) + 10}
          onClose={() => setEditing(null)} onSaved={invalidate} />
      )}
    </div>
  );
}

function MatchView({ m }: { m: Match | null }) {
  if (!m) return <span className="badge warn">Tanınmadı (standart dışı isim)</span>;
  return (
    <span className="row" style={{ gap: 6 }}>
      <span className="badge new">{m.type}</span>
      <b style={mono}>{m.std}</b>
      <span style={mono}>{m.size}</span>
      {m.desc && <span className="muted">{m.desc}</span>}
      {(m.d != null || m.l != null) && (
        <span className="muted adm-small">
          {m.d != null && `Ø ${m.d.toLocaleString("tr-TR")}`}{m.d != null && m.l != null && " · "}{m.l != null && `L ${m.l.toLocaleString("tr-TR")}`}
        </span>
      )}
      {m.rule && <span className="muted adm-small">kural: {m.rule}</span>}
    </span>
  );
}

function Results({ data }: { data: TestResult }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div className="muted">{fmtNum(data.matched)} / {fmtNum(data.total)} satır tanındı</div>
      <table className="simple" style={{ marginTop: 4 }}>
        <thead><tr><th>Metin</th><th>Sonuç</th></tr></thead>
        <tbody>
          {data.results.map((r, i) => (
            <tr key={i}><td style={mono}>{r.text}</td><td><MatchView m={r.match} /></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Runs the saved rule set on free text (one description per line). */
function TestBox() {
  const toast = useToast();
  const [text, setText] = useState("DIN 912 M10 x 65 --- 32N\nWasher DIN 125 - A 10.5\ngps anteni");
  const test = useMutation({
    mutationFn: () => api.post<TestResult>("/fastener-rules/test", { text }),
    onError: (e) => toast(errText(e), true),
  });
  return (
    <div className="card">
      <h3>Metni test et</h3>
      <p className="muted">Her satıra bir dosya adı / açıklama yazın; kayıtlı aktif kurallarla nasıl tanındığını görün.</p>
      <textarea rows={4} style={{ width: "100%", ...mono }} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row" style={{ marginTop: 6 }}>
        <button className="btn primary" disabled={!text.trim() || test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Test ediliyor…" : "Metni test et"}
        </button>
      </div>
      {test.data && <Results data={test.data} />}
    </div>
  );
}

function RuleForm({ rule, nextPriority, onClose, onSaved }: {
  rule?: Rule; nextPriority: number; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [f, setF] = useState<RuleBody>(() =>
    rule ? toBody(rule) : { name: "", pattern: "", type: "Cıvata", desc: "", std: "", size: "", d: "", l: "", maps: {}, priority: nextPriority, active: true },
  );
  const [mapsText, setMapsText] = useState(() => (rule && Object.keys(rule.maps ?? {}).length ? JSON.stringify(rule.maps, null, 2) : ""));
  const [sample, setSample] = useState("");
  const set = <K extends keyof RuleBody>(k: K, v: RuleBody[K]) => setF((x) => ({ ...x, [k]: v }));

  const parsedMaps = useMemo((): { maps?: Maps; err?: string } => {
    if (!mapsText.trim()) return { maps: {} };
    try {
      const v = JSON.parse(mapsText);
      if (!v || typeof v !== "object" || Array.isArray(v)) return { err: "Eşleme tabloları bir nesne olmalı" };
      for (const [k, t] of Object.entries(v)) {
        if (!/^[A-Za-z0-9_]+$/.test(k)) return { err: `Tablo adı yalnızca harf, rakam ve _ içerebilir: ${k}` };
        if (!t || typeof t !== "object" || Array.isArray(t)) return { err: `"${k}" tablosu {"anahtar": "değer"} biçiminde olmalı` };
        for (const x of Object.values(t as object)) if (typeof x !== "string") return { err: `"${k}" tablosundaki değerler metin olmalı` };
      }
      return { maps: v as Maps };
    } catch (e) {
      return { err: `JSON hatası: ${e instanceof Error ? e.message : e}` };
    }
  }, [mapsText]);

  const body = (): RuleBody => ({ ...f, name: f.name.trim(), maps: parsedMaps.maps ?? {} });
  const save = useMutation({
    mutationFn: () => (rule ? api.put<Rule>(`/fastener-rules/${rule.id}`, body()) : api.post<Rule>("/fastener-rules", body())),
    onSuccess: () => {
      toast(rule ? "Kural güncellendi" : "Kural eklendi");
      onSaved();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  const test = useMutation({
    mutationFn: () => api.post<TestResult>("/fastener-rules/test", { text: sample, rule: body() }),
    onError: (e) => toast(errText(e), true),
  });

  const invalid = !f.name.trim() || !f.pattern.trim() || !f.type.trim() || !!parsedMaps.err;
  return (
    <Modal wide title={rule ? `Kuralı düzenle: ${rule.name}` : "Yeni bağlantı elemanı kuralı"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={invalid || save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form two">
        <Field label="Ad"><input autoFocus value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Tür">
          <input list="adm-fastener-types" value={f.type} onChange={(e) => set("type", e.target.value)} />
          <datalist id="adm-fastener-types">{TYPES.map((t) => <option key={t} value={t} />)}</datalist>
        </Field>
        <div style={{ gridColumn: "1 / -1" }}>
          <Field label="Desen (regex, Python sözdizimi)" hint="Gruplar () ile yakalanır; şablonlarda {1}, {2}… ile kullanılır.">
            <input style={mono} value={f.pattern} onChange={(e) => set("pattern", e.target.value)} placeholder="(DIN 912|ISO 4762) M(\d+) x (\d+)" />
          </Field>
        </div>
        <Field label="Açıklama şablonu"><input value={f.desc} onChange={(e) => set("desc", e.target.value)} placeholder="İmbus cıvata" /></Field>
        <Field label="Standart şablonu"><input style={mono} value={f.std} onChange={(e) => set("std", e.target.value)} placeholder="DIN 912 / ISO 4762" /></Field>
        <Field label="Ölçü şablonu"><input style={mono} value={f.size} onChange={(e) => set("size", e.target.value)} placeholder="M{2}x{3}" /></Field>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <Field label="Çap (d)"><input style={{ ...mono, width: 110 }} value={f.d} onChange={(e) => set("d", e.target.value)} placeholder="{2}" /></Field>
          <Field label="Boy (l)"><input style={{ ...mono, width: 110 }} value={f.l} onChange={(e) => set("l", e.target.value)} placeholder="{3}" /></Field>
        </div>
        <Field label="Öncelik" hint="Küçük değer önce denenir.">
          <input type="number" value={f.priority} onChange={(e) => set("priority", Number(e.target.value) || 0)} style={{ width: 120 }} />
        </Field>
        <label className="row" style={{ gap: 6, alignSelf: "end" }}>
          <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> Aktif
        </label>
        <div style={{ gridColumn: "1 / -1" }}>
          <Field label="Eşleme tabloları (JSON, isteğe bağlı)" hint={<>Örnek: {'{"NUT_DESC": {"ISO 4032": "Altıgen somun"}}'} → şablonda {"{1|NUT_DESC}"}</>}>
            <textarea rows={5} style={mono} value={mapsText} onChange={(e) => setMapsText(e.target.value)} placeholder="{}" />
          </Field>
          {parsedMaps.err && <div className="error">{parsedMaps.err}</div>}
        </div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <b>Taslağı test et</b>
        <span className="muted"> (kaydetmeden, yalnızca bu kuralla)</span>
        <textarea rows={3} style={{ width: "100%", marginTop: 6, ...mono }} value={sample} onChange={(e) => setSample(e.target.value)}
          placeholder="Her satıra bir örnek dosya adı" />
        <button className="btn small" style={{ marginTop: 6 }} disabled={invalid || !sample.trim() || test.isPending} onClick={() => test.mutate()}>Test et</button>
        {test.data && <Results data={test.data} />}
      </div>
    </Modal>
  );
}
