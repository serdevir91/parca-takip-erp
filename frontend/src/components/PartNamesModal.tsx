import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { parseTsv } from "./dgSheet";
import { errText, useToast } from "./Toast";
import { LOCALE, tx } from "../api/i18n";

type Result = { updated: number; matched: number; not_found: string[] };

/** Lines of "part number, name" copied from Excel; a tab or a semicolon separates the two. */
export function parseNames(text: string): { part_no: string; name: string }[] {
  const tabbed = text.includes("\t");
  const rows = tabbed ? parseTsv(text) : text.split(/\r?\n/).map((l) => l.split(";"));
  return rows.filter((r) => r[0]?.trim()).map((r) => ({ part_no: r[0].trim(), name: r.slice(1).join(" ").trim() }));
}

export default function PartNamesModal({ pid, onClose }: { pid: number; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const items = useMemo(() => parseNames(text), [text]);
  const m = useMutation({
    mutationFn: () => api.post<Result>(`/projects/${pid}/parts/names`, { items }),
    onSuccess: (r) => {
      setResult(r);
      toast(tx("{0} parça adı kaydedildi", r.updated.toLocaleString(LOCALE)));
      qc.invalidateQueries({ queryKey: ["parts", pid] });
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-label={tx("Parça adlarını yapıştır")} onClick={(e) => e.stopPropagation()} style={{ width: 560 }}>
        <h3>{tx("Parça adlarını yapıştır")}</h3>
        <p className="muted">{tx("Excel'den iki sütun kopyalayın: parça no ve parça adı. Ad, parça numarası aynı olan tüm projelerde görünür. Adı boş bırakılan satırın adı silinir.")}</p>
        <textarea rows={10} style={{ width: "100%" }} autoFocus aria-label={tx("Parça no ve adları")} placeholder={tx("T01-0004-0001\tSol yan sac\nT01-0004-0002\tMotor flanşı")}
          value={text} onChange={(e) => { setText(e.target.value); setResult(null); }} />
        <p className="muted">{tx("{0} satır okundu.", items.length.toLocaleString(LOCALE))}</p>
        {result && (
          <p>
            {tx("{0} parça eşleşti, {1} ad değişti.", result.matched.toLocaleString(LOCALE), result.updated.toLocaleString(LOCALE))}
            {result.not_found.length > 0 && <span className="error">{" "}{tx("Bu projede bulunmayan {0} numara: {1}", result.not_found.length.toLocaleString(LOCALE), result.not_found.slice(0, 8).join(", "))}{result.not_found.length > 8 ? "…" : ""}</span>}
          </p>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>{tx("Kapat")}</button>
          <button className="btn primary" disabled={!items.length || m.isPending} onClick={() => m.mutate()}>{tx("Kaydet")}</button>
        </div>
      </div>
    </div>
  );
}
