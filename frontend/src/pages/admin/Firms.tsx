import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { saveRev } from "../../api/conflict";
import { useAuth } from "../../api/auth";
import { fmtMoney } from "../erp/common";
import { LedgerModal, useBalances } from "../erp/commerce";
import { errText, useToast } from "../../components/Toast";
import { Field, Loading, Modal } from "./shared";

type Firm = {
  rev?: number;
  id: number; name: string; kind: string; kind_label: string; contact: string; note: string; active: boolean;
  phone: string; email: string; address: string; tax_office: string; tax_no: string; lead_days: number;
};

export const FIRM_KINDS: { value: string; label: string }[] = [
  { value: "manufacturer", label: "Üretici" },
  { value: "supplier", label: "Tedarikçi" },
  { value: "both", label: "Üretici + tedarikçi" },
  { value: "customer", label: "Müşteri" },
];
const kindLabel = (k: string) => FIRM_KINDS.find((x) => x.value === k)?.label ?? k;

/** Cari kartlar: customers, suppliers and manufacturers, with the current balance when finance may be seen. */
export default function FirmsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const canEdit = can("contacts", "edit");
  const fin = can("finance");
  const bal = useBalances(fin);
  const balance = useMemo(() => {
    const m = new Map<number, { v: number; cur: string; overdue: number }[]>();
    for (const b of bal.data ?? []) if (b.firm_id) m.set(b.firm_id, [...(m.get(b.firm_id) ?? []), { v: b.balance, cur: b.currency, overdue: b.overdue_receivable + b.overdue_payable }]);
    return m;
  }, [bal.data]);
  const [ledger, setLedger] = useState<Firm | null>(null);
  const firms = useQuery({ queryKey: ["admin", "firms"], queryFn: () => api.get<Firm[]>("/admin/firms") });
  const [editing, setEditing] = useState<Firm | "new" | null>(null);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "firms"] });
    void qc.invalidateQueries({ queryKey: ["t35config"] });
    void qc.invalidateQueries({ queryKey: ["firms"] });
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
      (f) => (!kind || f.kind === kind) && (!s || `${f.name} ${f.contact} ${f.phone} ${f.email} ${f.note}`.toLocaleLowerCase("tr-TR").includes(s)),
    );
  }, [firms.data, kind, q]);

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        {canEdit && <button className="btn primary" onClick={() => setEditing("new")}>+ Yeni cari kart</button>}
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
            <thead><tr><th>Firma adı</th><th>Tür</th><th>İletişim</th>{fin && <th className="num">Bakiye</th>}<th>Not</th><th>Durum</th><th></th></tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.id} style={f.active ? undefined : { opacity: 0.6 }}>
                  <td><b>{f.name}</b></td>
                  <td>{kindLabel(f.kind)}</td>
                  <td>
                    {f.contact}
                    {(f.phone || f.email) && <div className="muted">{[f.phone, f.email].filter(Boolean).join(" · ")}</div>}
                    {f.lead_days > 0 && <div className="muted">Termin {f.lead_days} gün</div>}
                  </td>
                  {fin && (
                    <td className="num">
                      {(balance.get(f.id) ?? []).map((b) => (
                        <div key={b.cur} className={b.v > 0 ? "ok" : b.v < 0 ? "warn" : "muted"} title={b.v > 0 ? "Firma bize borçlu" : b.v < 0 ? "Biz firmaya borçluyuz" : undefined}>
                          {fmtMoney(b.v, b.cur)}{b.overdue > 0 && <span className="badge err" style={{ marginLeft: 4 }} title="Vadesi geçen">!</span>}
                        </div>
                      ))}
                    </td>
                  )}
                  <td className="muted" style={{ whiteSpace: "pre-wrap" }}>{f.note}</td>
                  <td>
                    <label className="row" style={{ gap: 4 }}>
                      <input type="checkbox" checked={f.active} disabled={!canEdit || toggle.isPending} onChange={() => toggle.mutate(f)} />
                      {f.active ? "Aktif" : "Pasif"}
                    </label>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                      {fin && <button className="btn small" onClick={() => setLedger(f)}>Ekstre</button>}
                      {canEdit && <button className="btn small" onClick={() => setEditing(f)}>Düzenle</button>}
                      {canEdit && <button className="btn small danger" disabled={del.isPending}
                        onClick={() => confirm(`"${f.name}" firması silinsin mi? Parça kayıtlarındaki firma adı metin olarak korunur.`) && del.mutate(f)}>Sil</button>}
                    </div>
                  </td>
                </tr>
              ))}
              {!list.length && <tr><td colSpan={fin ? 7 : 6} className="muted empty">Kayıt yok.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ marginTop: 10 }}>
        Üretici firmalar durum listesindeki metinden üretici tespiti için de kullanılır. Müşteriler satış ve faturada seçilir.
      </p>
      {ledger && <LedgerModal firmId={ledger.id} firmName={ledger.name} onClose={() => setLedger(null)} />}
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
  const [phone, setPhone] = useState(firm?.phone ?? "");
  const [email, setEmail] = useState(firm?.email ?? "");
  const [address, setAddress] = useState(firm?.address ?? "");
  const [taxOffice, setTaxOffice] = useState(firm?.tax_office ?? "");
  const [taxNo, setTaxNo] = useState(firm?.tax_no ?? "");
  const [leadDays, setLeadDays] = useState(String(firm?.lead_days ?? 0));
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), kind, contact, note, active, phone, email, address, tax_office: taxOffice, tax_no: taxNo,
        lead_days: Math.max(0, Math.round(Number(leadDays) || 0)) };
      return firm ? saveRev(firm.rev, (rev) => api.put<Firm>(`/admin/firms/${firm.id}`, { ...body, rev })) : api.post<Firm>("/admin/firms", body);
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
        <Field label="İletişim (yetkili kişi)"><input value={contact} onChange={(e) => setContact(e.target.value)} /></Field>
        <div className="adm-form two">
          <Field label="Telefon"><input value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
          <Field label="E-posta"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Vergi dairesi"><input value={taxOffice} onChange={(e) => setTaxOffice(e.target.value)} /></Field>
          <Field label="Vergi no"><input value={taxNo} onChange={(e) => setTaxNo(e.target.value)} /></Field>
        </div>
        <Field label="Adres"><textarea rows={2} value={address} onChange={(e) => setAddress(e.target.value)} /></Field>
        <Field label="Termin süresi (gün)" hint="Satın alma siparişinde varsayılan teslim süresi."><input type="number" min={0} value={leadDays} onChange={(e) => setLeadDays(e.target.value)} /></Field>
        <Field label="Not"><textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Aktif</label>
      </div>
    </Modal>
  );
}
