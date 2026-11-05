import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../api/auth";
import { OPTIONS_KEY } from "../../api/system";
import BrandMark from "../../components/BrandMark";
import { errText, useToast } from "../../components/Toast";
import { Field, ListEditor, Loading } from "./shared";
import { tx } from "../../api/i18n";

type Values = Record<string, string | number | string[]>;
type Sections = "company" | "commerce" | "production" | "security" | "files" | "modules";
type System = Record<Sections, Values>;
type Module = { key: string; label: string; locked: boolean };
type TeminType = { name: string; kind: string; drawing: boolean; order: boolean };
type Data = { system: System; modules: Module[]; temin_types: TeminType[] };

const QK = ["admin", "settings"];
const LOGO_SIZE = 128;

/** Any picture becomes a small PNG, so the stored logo stays a few KB. */
function toLogo(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(LOGO_SIZE / img.width, LOGO_SIZE / img.height, 1);
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(img.width * k));
      c.height = Math.max(1, Math.round(img.height * k));
      c.getContext("2d")?.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/png"));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error(tx("Resim okunamadı")));
    };
    img.src = url;
  });
}

export default function SystemSettingsTab() {
  const q = useQuery({ queryKey: QK, queryFn: () => api.get<Data>("/admin/settings") });
  return (
    <>
      <Loading error={q.error} loading={q.isLoading} />
      {q.data && <Forms data={q.data} />}
    </>
  );
}

function Forms({ data }: { data: Data }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { reloadUser } = useAuth();
  const save = useMutation({
    mutationFn: (s: System) => api.put<Data>("/admin/settings/system", { value: s }),
    onSuccess: (d) => {
      qc.setQueryData(QK, d);
      void qc.invalidateQueries({ queryKey: OPTIONS_KEY });
      reloadUser();
      toast(tx("Ayar kaydedildi"));
    },
    onError: (e) => toast(errText(e), true),
  });
  const card = { data: data.system, pending: save.isPending, onSave: (s: System) => save.mutate(s) };

  return (
    <div className="grid adm-settings">
      <Card {...card} section="company" title={tx("Şirket ve görünüm")}
        note={tx("Şirket bilgileri sipariş, teklif ve fatura formlarının üstüne yazılır. Uygulama adı menüde, giriş ekranında ve e-postalarda görünür.")}>
        {(f, set) => (
          <>
            <Text f={f} set={set} k="app_name" label={tx("Uygulama adı")} />
            <Logo value={String(f.logo)} onChange={(v) => set("logo", v)} />
            <Text f={f} set={set} k="name" label={tx("Şirket adı")} />
            <Text f={f} set={set} k="address" label={tx("Adres")} />
            <div className="adm-two">
              <Text f={f} set={set} k="phone" label={tx("Telefon")} />
              <Text f={f} set={set} k="email" label={tx("E-posta")} />
            </div>
            <Text f={f} set={set} k="web" label={tx("Web adresi")} />
            <div className="adm-two">
              <Text f={f} set={set} k="tax_office" label={tx("Vergi dairesi")} />
              <Text f={f} set={set} k="tax_no" label={tx("Vergi numarası")} />
            </div>
          </>
        )}
      </Card>

      <Card {...card} section="commerce" title={tx("Finans ve belgeler")}
        note={tx("Yeni belgelerin varsayılanları. Toplamlar bu para birimine çevrilir: her belge kendi kurunu saklar, kurlar Fatura ve ödeme > Kurlar sekmesindedir. Para birimini değiştirirseniz eski kurlar ve belge kurları eski birime göre kalır.")}>
        {(f, set) => (
          <>
            <div className="adm-two">
              <Text f={f} set={set} k="currency" label={tx("Para birimi")} hint={tx("TRY, EUR, USD gibi")} />
              <Num f={f} set={set} k="vat" label={tx("KDV oranı (%)")} />
            </div>
            <div className="adm-two">
              <Num f={f} set={set} k="payment_days" label={tx("Fatura vadesi (gün)")} />
              <Num f={f} set={set} k="quote_days" label={tx("Teklif geçerliliği (gün)")} />
            </div>
            <div className="adm-two">
              <Num f={f} set={set} k="over_receipt_pct" label={tx("Fazla teslim payı (%)")} hint={tx("Mal kabulde sipariş miktarının en çok bu kadar üstü kabul edilir.")} />
            </div>
            <Field label={tx("Cari bakiye değerleme kuru")}
              hint={tx("Bugünkü kur: açık bakiye günün kuruyla değerlenir. Belge kuru: her fatura ve ödeme kendi tarihindeki kurla kalır, kapanmış hesapta kur farkı görünür.")}>
              <select value={String(f.balance_basis ?? "today")} onChange={(e) => set("balance_basis", e.target.value)}>
                <option value="today">{tx("Bugünkü kur")}</option>
                <option value="doc">{tx("Belge tarihindeki kur")}</option>
              </select>
            </Field>
            <Field label={tx("Ödeme yöntemleri")}>
              <ListEditor value={f.pay_methods as string[]} onChange={(v) => set("pay_methods", v)} placeholder={tx("Ödeme yöntemi")} />
            </Field>
            <div className="adm-two">
              <Text f={f} set={set} k="no_po" label={tx("Satın alma no öneki")} />
              <Text f={f} set={set} k="no_so" label={tx("Satış no öneki")} />
            </div>
            <div className="adm-two">
              <Text f={f} set={set} k="no_invoice" label={tx("Fatura no öneki")} />
              <Text f={f} set={set} k="no_wo" label={tx("İş emri no öneki")} />
            </div>
            <p className="muted" style={{ margin: 0 }}>{tx("Örnek numara: {0}-{1}-0001. Yeni önek 0001'den başlar.", String(f.no_po), new Date().getFullYear())}</p>
          </>
        )}
      </Card>

      <Card {...card} section="production" title={tx("Üretim ve stok")} note={tx("Yeni kayıtlarda önerilen değerler; her kayıtta değiştirilebilir.")}>
        {(f, set) => (
          <>
            <Text f={f} set={set} k="unit" label={tx("Varsayılan birim")} />
            <Num f={f} set={set} k="spare_pct" label={tx("Bağlantı elemanı yedek oranı (%)")} />
            <Num f={f} set={set} k="work_hours" label={tx("Günlük çalışma saati")} />
            <Num f={f} set={set} k="week_hours" label={tx("Haftalık çalışma saati (üstü fazla mesai)")} />
            <Num f={f} set={set} k="break_minutes" label={tx("Mola süresi (dk, 4 saatten uzun mesaide düşülür)")} />
            <Num f={f} set={set} k="annual_leave_days" label={tx("Yıllık izin hakkı (gün, personel kartında değiştirilebilir)")} />
          </>
        )}
      </Card>

      <Card {...card} section="security" title={tx("Güvenlik")} note={tx("Şifre kuralı yalnızca yeni şifrelerde, oturum süresi sonraki girişlerde geçerli olur.")}>
        {(f, set) => (
          <>
            <Num f={f} set={set} k="session_hours" label={tx("Oturum süresi (saat)")} />
            <Num f={f} set={set} k="password_min" label={tx("En kısa şifre (karakter)")} />
            <div className="adm-two">
              <Num f={f} set={set} k="login_attempts" label={tx("Hatalı giriş sınırı")} />
              <Num f={f} set={set} k="lock_minutes" label={tx("Kilit süresi (dakika)")} />
            </div>
          </>
        )}
      </Card>

      <Card {...card} section="files" title={tx("Dosya ve yedek")}>
        {(f, set) => (
          <>
            <Num f={f} set={set} k="upload_mb" label={tx("En büyük dosya (MB)")} hint={tx("Docker kurulumunda web sunucusu 2048 MB üstünü geçirmez.")} />
            <Num f={f} set={set} k="keep_days" label={tx("Yedek saklama (gün)")} />
            <Field label={tx("Günlük yedek saati")}>
              <input type="time" value={String(f.backup_time)} onChange={(e) => set("backup_time", e.target.value)} style={{ width: 140 }} />
            </Field>
          </>
        )}
      </Card>

      <Card {...card} section="modules" title={tx("Modüller")}
        note={tx("Kapatılan modül herkesten, yöneticiler dahil, gizlenir ve kullanılamaz. Veriler silinmez; açınca geri gelir.")}>
        {(f, set) => {
          const off = f.off as string[];
          return (
            <div className="grid" style={{ gap: 6 }}>
              {data.modules.map((m) => (
                <label key={m.key} className="row" style={{ gap: 8 }}>
                  <input type="checkbox" disabled={m.locked} checked={!off.includes(m.key)}
                    onChange={(e) => set("off", e.target.checked ? off.filter((k) => k !== m.key) : [...off, m.key])} />
                  {m.label}
                </label>
              ))}
            </div>
          );
        }}
      </Card>
      <TeminCard types={data.temin_types} />
    </div>
  );
}

const FIXED_TEMINS = ["İmalat", "Hazır Alım", "Belirtilmemiş"];

/** Temin types: the name people pick, which status set it follows, and what it asks for. */
function TeminCard({ types }: { types: TeminType[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [list, setList] = useState(types);
  const set = (i: number, ch: Partial<TeminType>) => setList((s) => s.map((t, j) => (j === i ? { ...t, ...ch } : t)));
  const save = useMutation({
    mutationFn: () => api.put<Data>("/admin/settings/temin_types", { value: list }),
    onSuccess: (d) => {
      qc.setQueryData(QK, d);
      setList(d.temin_types);
      void qc.invalidateQueries({ queryKey: ["partChoices"] });
      void qc.invalidateQueries({ queryKey: ["parts"] });
      toast(tx("Temin şekilleri kaydedildi"));
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <section className="card adm-temin">
      <h3>{tx("Temin şekilleri")}</h3>
      <p className="muted">{tx("Davranış, parçanın hangi durumlardan geçeceğini belirler. Teknik resim işaretliyse resmi olmayan parça uyarı verir. Sipariş önerisi kapalıysa ihtiyaç listesi bu parça için iş emri ya da satın alma önermez.")}</p>
      <table className="simple">
        <thead><tr><th>{tx("Ad")}</th><th>{tx("Davranış")}</th><th>{tx("Teknik resim")}</th><th>{tx("Sipariş önerisi")}</th><th /></tr></thead>
        <tbody>
          {list.map((t, i) => {
            const fixed = FIXED_TEMINS.includes(t.name);
            return (
              <tr key={i}>
                <td><input value={t.name} disabled={fixed} maxLength={64} aria-label={tx("Temin şekli adı")} onChange={(e) => set(i, { name: e.target.value })} /></td>
                <td>
                  <select value={t.kind} disabled={fixed} aria-label={tx("Davranış")} onChange={(e) => set(i, { kind: e.target.value })}>
                    {t.kind === "" && <option value="">{tx("Yok")}</option>}
                    <option value="İmalat">{tx("İmalat: Üretilmedi, Üretildi")}</option>
                    <option value="Hazır Alım">{tx("Hazır Alım: Sipariş Verilmedi, Verildi, Teslim Edildi")}</option>
                  </select>
                </td>
                <td><input type="checkbox" checked={t.drawing} aria-label={tx("Teknik resim gerekir")} onChange={(e) => set(i, { drawing: e.target.checked })} /></td>
                <td><input type="checkbox" checked={t.order} aria-label={tx("Sipariş önerisi")} onChange={(e) => set(i, { order: e.target.checked })} /></td>
                <td>{!fixed && <button className="btn small" onClick={() => setList((s) => s.filter((_, j) => j !== i))}>{tx("Sil")}</button>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn small" onClick={() => setList((s) => [...s, { name: "", kind: "Hazır Alım", drawing: false, order: true }])}>{tx("+ Temin şekli ekle")}</button>
        <button className="btn small primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </div>
      <p className="muted">{tx("Silinen bir türü kullanan parçalar eski adını korur, durumu \"Temin seçilmedi\" olur.")}</p>
    </section>
  );
}

type Setter = (k: string, v: Values[string]) => void;

function Card({ section, title, note, data, pending, onSave, children }: {
  section: Sections; title: string; note?: string; data: System; pending: boolean;
  onSave: (s: System) => void; children: (f: Values, set: Setter) => ReactNode;
}) {
  const saved = data[section];
  const [f, setF] = useState(saved);
  useEffect(() => setF(saved), [saved]);
  const dirty = JSON.stringify(f) !== JSON.stringify(saved);
  return (
    <div className="card">
      <h3>{title}</h3>
      {note && <p className="muted">{note}</p>}
      <div className="grid" style={{ gap: 10 }}>{children(f, (k, v) => setF((p) => ({ ...p, [k]: v })))}</div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={!dirty || pending} onClick={() => onSave({ ...data, [section]: f })}>{tx("Kaydet")}</button>
        <button className="btn" disabled={!dirty || pending} onClick={() => setF(saved)}>{tx("Geri al")}</button>
        {dirty && <span className="warn">{tx("Kaydedilmemiş değişiklik var")}</span>}
      </div>
    </div>
  );
}

function Text({ f, set, k, label, hint }: { f: Values; set: Setter; k: string; label: string; hint?: string }) {
  return <Field label={label} hint={hint}><input value={String(f[k] ?? "")} onChange={(e) => set(k, e.target.value)} /></Field>;
}

function Num({ f, set, k, label, hint }: { f: Values; set: Setter; k: string; label: string; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <input inputMode="decimal" value={String(f[k] ?? "")} onChange={(e) => set(k, e.target.value.replace(",", "."))} />
    </Field>
  );
}

function Logo({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const toast = useToast();
  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      onChange(await toLogo(file));
    } catch (err) {
      toast(errText(err), true);
    }
  };
  return (
    <Field label={tx("Logo")} hint={tx("Kare bir resim seçin. Masaüstü ve Android simgeleri değişmez.")}>
      <div className="row">
        <span className="brand-logo"><BrandMark logo={value} /></span>
        <input type="file" accept="image/*" onChange={pick} />
        {value && <button className="btn small" type="button" onClick={() => onChange("")}>{tx("Kaldır")}</button>}
      </div>
    </Field>
  );
}
