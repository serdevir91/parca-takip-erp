import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { FIELD_LABELS, type PartChoices } from "./PartDetail";
import { errText, useToast } from "./Toast";
import { LOCALE, tx } from "../api/i18n";

type BulkResult = { matched: number; updated: number; fields_changed: number; not_found: string[] };

const FIELDS = ["progress", "procurement_override", "manufacturer", "material_status", "note", "t35_note", "is_new"] as const;
type Field = (typeof FIELDS)[number];
const CLEAR = "__clear__";

/** Modal: apply one field value to every selected part (POST /projects/{pid}/parts/bulk). */
export default function BulkEdit({ pid, partNos, choices, onClose, onDone }: {
  pid: number; partNos: string[]; choices?: PartChoices; onClose: () => void; onDone?: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const [field, setField] = useState<Field>("progress");
  const [value, setValue] = useState<string>("");

  const options = useMemo<string[] | null>(() => {
    switch (field) {
      case "progress": return choices?.progress_choices ?? [];
      case "procurement_override": return choices?.temin_choices ?? [];
      case "material_status": return choices?.material_status_choices ?? [];
      case "manufacturer": return choices?.manufacturers?.length ? choices.manufacturers : null;
      case "is_new": return ["true", "false"];
      default: return null;
    }
  }, [field, choices]);

  const m = useMutation({
    mutationFn: () => {
      let v: unknown = value;
      if (field === "is_new") v = value === "true";
      else if (value === CLEAR) v = field === "procurement_override" ? null : "";
      return api.post<BulkResult>(`/projects/${pid}/parts/bulk`, { part_nos: partNos, changes: { [field]: v } });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["parts", pid] });
      qc.invalidateQueries({ queryKey: ["dashboard", pid] });
      const nf = r.not_found.length ? tx(" · bulunamayan: {0}", r.not_found.length.toLocaleString(LOCALE)) : "";
      toast(tx("{0} parça güncellendi ({1} alan){2}", r.updated.toLocaleString(LOCALE), r.fields_changed.toLocaleString(LOCALE), nf));
      onDone?.();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });

  const needsValue = options !== null && field !== "note" && field !== "t35_note";
  const valid = !needsValue || value !== "";

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={tx("Toplu düzenle")}>
        <h3 style={{ marginTop: 0 }}>{tx("Toplu düzenle")}</h3>
        <p className="muted">{tx("{0} parça seçili. Seçilen alan hepsinde aynı değere ayarlanır.", partNos.length.toLocaleString(LOCALE))}</p>
        <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 10, alignItems: "center" }}>
          <label htmlFor="bulk-field">{tx("Alan")}</label>
          <select id="bulk-field" value={field} onChange={(e) => { setField(e.target.value as Field); setValue(""); }}>
            {FIELDS.map((f) => <option key={f} value={f}>{FIELD_LABELS[f]}</option>)}
          </select>
          <label htmlFor="bulk-value">{tx("Değer")}</label>
          {options ? (
            <select id="bulk-value" value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="" disabled>{tx("Seçin…")}</option>
              {field === "is_new"
                ? <><option value="true">{tx("Yeni olarak işaretle")}</option><option value="false">{tx("Yeni etiketini kaldır")}</option></>
                : options.map((o) => <option key={o} value={o}>{tx(o)}</option>)}
              {(field === "procurement_override" || field === "manufacturer" || field === "material_status") && (
                <option value={CLEAR}>{field === "procurement_override" ? tx("(BOM değerine dön)") : tx("(Boşalt)")}</option>
              )}
            </select>
          ) : field === "note" || field === "t35_note" ? (
            <textarea id="bulk-value" rows={3} value={value} onChange={(e) => setValue(e.target.value)} placeholder={tx("Boş bırakılırsa alan temizlenir")} />
          ) : (
            <input id="bulk-value" value={value} onChange={(e) => setValue(e.target.value)} />
          )}
        </div>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button className="btn" onClick={onClose} disabled={m.isPending}>{tx("Vazgeç")}</button>
          <button className="btn primary" disabled={!valid || m.isPending || partNos.length === 0} onClick={() => m.mutate()}>
            {m.isPending ? tx("Uygulanıyor…") : tx("Uygula")}
          </button>
        </div>
      </div>
    </div>
  );
}
