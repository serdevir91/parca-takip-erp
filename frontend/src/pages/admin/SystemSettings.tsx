import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../api/auth";
import { OPTIONS_KEY } from "../../api/system";
import BrandMark from "../../components/BrandMark";
import { errText, useToast } from "../../components/Toast";
import { Field, ListEditor, Loading } from "./shared";

type Values = Record<string, string | number | string[]>;
type Sections = "company" | "commerce" | "production" | "security" | "files" | "modules";
type System = Record<Sections, Values>;
type Module = { key: string; label: string; locked: boolean };
type Data = { system: System; modules: Module[] };

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
      reject(new Error("Resim okunamadı"));
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
      toast("Ayar kaydedildi");
    },
    onError: (e) => toast(errText(e), true),
  });
  const card = { data: data.system, pending: save.isPending, onSave: (s: System) => save.mutate(s) };

  return (
    <div className="grid adm-settings">
      <Card {...card} section="company" title="Şirket ve görünüm"
        note="Şirket bilgileri sipariş, teklif ve fatura formlarının üstüne yazılır. Uygulama adı menüde, giriş ekranında ve e-postalarda görünür.">
        {(f, set) => (
          <>
            <Text f={f} set={set} k="app_name" label="Uygulama adı" />
            <Logo value={String(f.logo)} onChange={(v) => set("logo", v)} />
            <Text f={f} set={set} k="name" label="Şirket adı" />
            <Text f={f} set={set} k="address" label="Adres" />
            <div className="adm-two">
              <Text f={f} set={set} k="phone" label="Telefon" />
              <Text f={f} set={set} k="email" label="E-posta" />
            </div>
            <Text f={f} set={set} k="web" label="Web adresi" />
            <div className="adm-two">
              <Text f={f} set={set} k="tax_office" label="Vergi dairesi" />
              <Text f={f} set={set} k="tax_no" label="Vergi numarası" />
            </div>
          </>
        )}
      </Card>

      <Card {...card} section="commerce" title="Finans ve belgeler"
        note="Yeni belgelerin varsayılanları. Mevcut belgeler değişmez; kur çevrimi yapılmaz, toplamlar yalnızca varsayılan para birimindeki kayıtları sayar.">
        {(f, set) => (
          <>
            <div className="adm-two">
              <Text f={f} set={set} k="currency" label="Para birimi" hint="TRY, EUR, USD gibi" />
              <Num f={f} set={set} k="vat" label="KDV oranı (%)" />
            </div>
            <div className="adm-two">
              <Num f={f} set={set} k="payment_days" label="Fatura vadesi (gün)" />
              <Num f={f} set={set} k="quote_days" label="Teklif geçerliliği (gün)" />
            </div>
            <Field label="Ödeme yöntemleri">
              <ListEditor value={f.pay_methods as string[]} onChange={(v) => set("pay_methods", v)} placeholder="Ödeme yöntemi" />
            </Field>
            <div className="adm-two">
              <Text f={f} set={set} k="no_po" label="Satın alma no öneki" />
              <Text f={f} set={set} k="no_so" label="Satış no öneki" />
            </div>
            <div className="adm-two">
              <Text f={f} set={set} k="no_invoice" label="Fatura no öneki" />
              <Text f={f} set={set} k="no_wo" label="İş emri no öneki" />
            </div>
            <p className="muted" style={{ margin: 0 }}>Örnek numara: {String(f.no_po)}-{new Date().getFullYear()}-0001. Yeni önek 0001'den başlar.</p>
          </>
        )}
      </Card>

      <Card {...card} section="production" title="Üretim ve stok" note="Yeni kayıtlarda önerilen değerler; her kayıtta değiştirilebilir.">
        {(f, set) => (
          <>
            <Text f={f} set={set} k="unit" label="Varsayılan birim" />
            <Num f={f} set={set} k="spare_pct" label="Bağlantı elemanı yedek oranı (%)" />
            <Num f={f} set={set} k="work_hours" label="Günlük çalışma saati" />
          </>
        )}
      </Card>

      <Card {...card} section="security" title="Güvenlik" note="Şifre kuralı yalnızca yeni şifrelerde, oturum süresi sonraki girişlerde geçerli olur.">
        {(f, set) => (
          <>
            <Num f={f} set={set} k="session_hours" label="Oturum süresi (saat)" />
            <Num f={f} set={set} k="password_min" label="En kısa şifre (karakter)" />
            <div className="adm-two">
              <Num f={f} set={set} k="login_attempts" label="Hatalı giriş sınırı" />
              <Num f={f} set={set} k="lock_minutes" label="Kilit süresi (dakika)" />
            </div>
          </>
        )}
      </Card>

      <Card {...card} section="files" title="Dosya ve yedek">
        {(f, set) => (
          <>
            <Num f={f} set={set} k="upload_mb" label="En büyük dosya (MB)" hint="Docker kurulumunda web sunucusu 2048 MB üstünü geçirmez." />
            <Num f={f} set={set} k="keep_days" label="Yedek saklama (gün)" />
            <Field label="Günlük yedek saati">
              <input type="time" value={String(f.backup_time)} onChange={(e) => set("backup_time", e.target.value)} style={{ width: 140 }} />
            </Field>
          </>
        )}
      </Card>

      <Card {...card} section="modules" title="Modüller"
        note="Kapatılan modül herkesten, yöneticiler dahil, gizlenir ve kullanılamaz. Veriler silinmez; açınca geri gelir.">
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
    </div>
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
        <button className="btn primary" disabled={!dirty || pending} onClick={() => onSave({ ...data, [section]: f })}>Kaydet</button>
        <button className="btn" disabled={!dirty || pending} onClick={() => setF(saved)}>Geri al</button>
        {dirty && <span className="warn">Kaydedilmemiş değişiklik var</span>}
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
    <Field label="Logo" hint="Kare bir resim seçin. Masaüstü ve Android simgeleri değişmez.">
      <div className="row">
        <span className="brand-logo"><BrandMark logo={value} /></span>
        <input type="file" accept="image/*" onChange={pick} />
        {value && <button className="btn small" type="button" onClick={() => onChange("")}>Kaldır</button>}
      </div>
    </Field>
  );
}
