import { useEffect, useState, type ReactNode } from "react";
import { errText } from "../../components/Toast";

/** Turkish role labels (backend labels are overridden for the admin screen). */
export const ROLE_TR: Record<string, string> = {
  admin: "Yönetici (Admin)",
  designer: "Tasarımcı",
  planner: "Planlama/Satın alma",
  viewer: "İzleyici",
};
export const roleLabel = (r: string) => ROLE_TR[r] ?? r;

export const fmtNum = (n: number | null | undefined, digits = 0) =>
  n == null ? "" : n.toLocaleString("tr-TR", { maximumFractionDigits: digits });

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString("tr-TR");
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString("tr-TR", { maximumFractionDigits: i ? 1 : 0 })} ${units[i]}`;
}

export function Modal({ title, onClose, children, footer, wide }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: wide ? "min(1000px, 95vw)" : "min(560px, 95vw)" }} role="dialog" aria-label={title}>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>{title}</h3>
          <button className="btn small" onClick={onClose} aria-label="Kapat">✕</button>
        </div>
        {children}
        {footer && <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>{footer}</div>}
      </div>
    </div>
  );
}

/** Label + control stacked; used by all admin forms. */
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="adm-field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

/**
 * Editable list of strings: one input per row, add/remove, plus a bulk textarea mode
 * (one value per line) for long lists such as purchased assemblies.
 */
export function ListEditor({ value, onChange, placeholder, validate, disabled, mono }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string;
  validate?: (s: string) => string | null; disabled?: boolean; mono?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [bulk, setBulk] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [filter, setFilter] = useState("");
  const style = mono ? { fontFamily: "ui-monospace, Consolas, monospace" } : undefined;

  const add = () => {
    const v = draft.trim();
    if (!v || value.includes(v)) return setDraft("");
    onChange([...value, v]);
    setDraft("");
  };
  const openBulk = () => {
    setBulkText(value.join("\n"));
    setBulk(true);
  };
  const applyBulk = () => {
    const out: string[] = [];
    for (const s of bulkText.split(/\r?\n/).map((x) => x.trim())) if (s && !out.includes(s)) out.push(s);
    onChange(out);
    setBulk(false);
  };

  if (bulk)
    return (
      <div>
        <textarea rows={12} style={{ width: "100%", ...style }} value={bulkText} onChange={(e) => setBulkText(e.target.value)}
          placeholder="Her satıra bir değer" />
        <div className="row" style={{ marginTop: 6 }}>
          <button className="btn small primary" onClick={applyBulk}>Listeye uygula</button>
          <button className="btn small" onClick={() => setBulk(false)}>Vazgeç</button>
          <span className="muted">{fmtNum(bulkText.split(/\r?\n/).filter((x) => x.trim()).length)} satır</span>
        </div>
      </div>
    );

  const f = filter.trim().toLocaleLowerCase("tr-TR");
  const shown = value.map((v, i) => ({ v, i })).filter((x) => !f || x.v.toLocaleLowerCase("tr-TR").includes(f));
  return (
    <div>
      {value.length > 15 && (
        <input placeholder="Listede ara…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ marginBottom: 6, width: "100%" }} />
      )}
      <div className="adm-list">
        {shown.map(({ v, i }) => {
          const err = validate?.(v);
          return (
            <div key={i} className="row adm-list-row">
              <input style={{ flex: 1, ...style }} value={v} disabled={disabled}
                onChange={(e) => onChange(value.map((x, j) => (j === i ? e.target.value : x)))} />
              {err && <span className="error" title={err}>⚠ {err}</span>}
              {!disabled && <button className="btn small" title="Kaldır" onClick={() => onChange(value.filter((_, j) => j !== i))}>✕</button>}
            </div>
          );
        })}
        {!value.length && <div className="muted">Liste boş.</div>}
      </div>
      {!disabled && (
        <div className="row" style={{ marginTop: 6 }}>
          <input style={{ flex: 1, ...style }} value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())} />
          <button className="btn small" onClick={add} disabled={!draft.trim()}>Ekle</button>
          <button className="btn small" onClick={openBulk}>Toplu düzenle</button>
        </div>
      )}
      <div className="muted" style={{ marginTop: 4 }}>{fmtNum(value.length)} kayıt</div>
    </div>
  );
}

export function Loading({ error, loading }: { error: unknown; loading: boolean }) {
  if (error) return <div className="error">{errText(error)}</div>;
  if (loading) return <div className="muted">Yükleniyor…</div>;
  return null;
}
