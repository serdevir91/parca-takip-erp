import { Modal, fmtDate } from "../pages/admin/shared";
import { tx } from "../api/i18n";

export type EditConflict = { part_no: string; field: string; mine: unknown; theirs: string | null; by: string; at: string };

const FIELD: Record<string, string> = {
  procurement_override: tx("Temin şekli"), progress: tx("İlerleme"), note: tx("Not"), t35_note: tx("Durum Notu"), manufacturer: tx("Üretici"),
  material_status: tx("Malzeme durumu"), is_new: tx("Yeni"), hidden: tx("Gizli"), part_name: tx("Parça adı"),
};
const shown = (v: unknown) => (v === null || v === undefined || v === "" ? tx("(boş)") : v === true ? tx("Evet") : v === false ? tx("Hayır") : String(v));

/** Someone else saved these cells while this user was looking at older values; nothing was overwritten yet. */
export default function EditConflicts({ items, onOverwrite, onKeep }: { items: EditConflict[]; onOverwrite: () => void; onKeep: () => void }) {
  return (
    <Modal
      title={tx("Başkası değiştirdi")}
      onClose={onKeep}
      footer={
        <>
          <button className="btn" onClick={onKeep}>{tx("Onlarınki kalsın")}</button>
          <button className="btn danger" onClick={onOverwrite}>{tx("Benimkini yaz")}</button>
        </>
      }
    >
      <p>{tx("Siz düzenlerken bu alanlar değişti. Değişikliğiniz kaydedilmedi.")}</p>
      <div className="adm-scroll" style={{ maxHeight: "50vh" }}>
        <table className="simple">
          <thead><tr><th>{tx("Parça")}</th><th>{tx("Alan")}</th><th>{tx("Sizin değeriniz")}</th><th>{tx("Kayıtlı değer")}</th><th>{tx("Kim")}</th></tr></thead>
          <tbody>
            {items.map((c) => (
              <tr key={`${c.part_no}|${c.field}`}>
                <td>{c.part_no}</td>
                <td>{FIELD[c.field] ?? c.field}</td>
                <td>{shown(c.mine)}</td>
                <td>{shown(c.theirs)}</td>
                <td>{c.by}<br /><span className="muted">{fmtDate(c.at)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
