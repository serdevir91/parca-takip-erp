import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal } from "./shared";

type Firm = { id: number; name: string; kind: string; kind_label: string; contact: string; note: string; active: boolean };

export const FIRM_KINDS: { value: string; label: string }[] = [
  { value: "manufacturer", label: "Üretici" },
  { value: "supplier", label: "Tedarikçi" },
  { value: "both", label: "Her ikisi" },
];
const kindLabel = (k: string) => FIRM_KINDS.find((x) => x.value === k)?.label ?? k;

export default function FirmsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const firms = useQuery({ queryKey: ["admin", "firms"], queryFn: () => api.get<Firm[]>("/admin/firms") });
  const [editing, setEditing] = useState<Firm | "new" | null>(null);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "firms"] });
    void qc.invalidateQueries({ queryKey: ["t35config"] });
  };
  const del = useMutation({
    mutationFn: (f: Firm) => api.del(`/admin/firms/${f.id}`),
    onSuccess: () => {
      toast("Firma silindi");
      refresh();
    },
    onError: (e) => toast(errText(e), true),
  });
  const toggle = useMutation({
    mutationFn: (f: Firm) => api.put(`/admin/firms/${f.id}`, { active: !f.active }),
    onSuccess: refresh,
    onError: (e) => toast(errText(e), true),
  });

  const list = useMemo(() => {
    const s = q.trim().toLocaleLowerCase("tr-TR");
    return (firms.data ?? []).filter(
      (f) => (!kind || f.kind === kind) && (!s || `${f.name} ${f.contact} ${f.note}`.toLocaleLowerCase("tr-TR").includes(s)),
    );
  }, [firms.data, kind, q]);

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <button className="btn primary" onClick={() => setEditing("new")}>+ Yeni firma</button>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Tüm türler</option>
          {FIRM_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <input placeholder="Ara…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{list.length.toLocaleString("tr-TR")} / {(firms.data?.length ?? 0).toLocaleString("tr-TR")} firma</span>
      </div>
      <Loading error={firms.error} loading={firms.isLoading} />
      {firms.data && (
        <div className="adm-scroll">
          <table className="simple">
            <thead><tr><th>Firma adı</th><th>Tür</th><th>İletişim</th><th>Not</th><th>Durum</th><th></th></tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.id} style={f.active ? undefined : { opacity: 0.6 }}>
                  <td><b>{f.name}</b></td>
                  <td>{kindLabel(f.kind)}</td>
                  <td>{f.contact}</td>
                  <td className="muted" style={{ whiteSpace: "pre-wrap" }}>{f.note}</td>
                  <td>
                    <label className="row" style={{ gap: 4 }}>
                      <input type="checkbox" checked={f.active} disabled={toggle.isPending} onChange={() => toggle.mutate(f)} />
                      {f.active ? "Aktif" : "Pasif"}
                    </label>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                      <button className="btn small" onClick={() => setEditing(f)}>Düzenle</button>
                      <button className="btn small danger" disabled={del.isPending}
                        onClick={() => confirm(`"${f.name}" firması silinsin mi? Parça kayıtlarındaki firma adı metin olarak korunur.`) && del.mutate(f)}>Sil</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!list.length && <tr><td colSpan={6} className="muted">Kayıt yok.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ marginTop: 10 }}>
        Üretici firmalar T-35 listesindeki metinden üretici tespiti için de kullanılır.
      </p>
      {editing && <FirmForm firm={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </div>
  );
}

function FirmForm({ firm, onClose, onSaved }: { firm?: Firm; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(firm?.name ?? "");
  const [kind, setKind] = useState(firm?.kind ?? "manufacturer");
  const [contact, setContact] = useState(firm?.contact ?? "");
  const [note, setNote] = useState(firm?.note ?? "");
  const [active, setActive] = useState(firm?.active ?? true);
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), kind, contact, note, active };
      return firm ? api.put<Firm>(`/admin/firms/${firm.id}`, body) : api.post<Firm>("/admin/firms", body);
    },
    onSuccess: () => {
      toast(firm ? "Firma güncellendi" : "Firma eklendi");
      onSaved();
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={firm ? `Firmayı düzenle: ${firm.name}` : "Yeni firma"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form">
        <Field label="Firma adı"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Tür">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {FIRM_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </Field>
        <Field label="İletişim"><input value={contact} onChange={(e) => setContact(e.target.value)} /></Field>
        <Field label="Not"><textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Aktif</label>
      </div>
    </Modal>
  );
}
