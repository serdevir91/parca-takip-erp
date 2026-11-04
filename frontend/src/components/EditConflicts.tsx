import { Modal, fmtDate } from "../pages/admin/shared";

export type EditConflict = { part_no: string; field: string; mine: unknown; theirs: string | null; by: string; at: string };

const FIELD: Record<string, string> = {
  procurement_override: "Temin şekli", progress: "İlerleme", note: "Not", t35_note: "Liste notu", manufacturer: "Üretici",
  material_status: "Malzeme durumu", is_new: "Yeni", hidden: "Gizli", part_name: "Parça adı",
};
const shown = (v: unknown) => (v === null || v === undefined || v === "" ? "(boş)" : v === true ? "Evet" : v === false ? "Hayır" : String(v));

/** Someone else saved these cells while this user was looking at older values; nothing was overwritten yet. */
export default function EditConflicts({ items, onOverwrite, onKeep }: { items: EditConflict[]; onOverwrite: () => void; onKeep: () => void }) {
  return (
    <Modal
      title="Başkası değiştirdi"
      onClose={onKeep}
      footer={
        <>
          <button className="btn" onClick={onKeep}>Onlarınki kalsın</button>
          <button className="btn danger" onClick={onOverwrite}>Benimkini yaz</button>
        </>
      }
    >
      <p>Siz düzenlerken bu alanlar değişti. Değişikliğiniz kaydedilmedi.</p>
      <div className="adm-scroll" style={{ maxHeight: "50vh" }}>
        <table className="simple">
          <thead><tr><th>Parça</th><th>Alan</th><th>Sizin değeriniz</th><th>Kayıtlı değer</th><th>Kim</th></tr></thead>
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
