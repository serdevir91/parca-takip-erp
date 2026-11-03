import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, ImagePlus, Pencil, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { api, upload } from "../api/client";
import { fmtBytes, isImageFile, makeThumb } from "../api/images";
import { errText, useToast } from "./Toast";
import Thumb, { forgetThumb } from "./viewer/Thumb";
import Viewer, { type ViewItem } from "./viewer/Viewer";

export type Photo = {
  id: number; entity: string; key: string; filename: string; content_type: string; size: number; caption: string;
  preview: boolean; uploaded_by: string; uploaded_at: string | null;
};
type Entity = "part" | "stock";

const photoItem = (p: Photo): ViewItem => ({
  key: p.id, name: p.filename, path: `/photos/${p.id}/file`, thumb: `/photos/${p.id}/thumb`, kind: "image",
  caption: [p.caption, `${p.uploaded_by} · ${p.uploaded_at ? new Date(p.uploaded_at).toLocaleDateString("tr-TR") : ""}`]
    .filter(Boolean).join(" · "),
});

/** Photos of one part number or stock item: thumbnail grid, multi-upload (drag & drop, phone camera)
 *  and the zoomable viewer. */
export default function Photos({ entity, entityKey, canEdit }: { entity: Entity; entityKey: string; canEdit: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const qk = ["photos", entity, entityKey];
  const q = useQuery({
    queryKey: qk,
    queryFn: () => api.get<Photo[]>(`/photos?entity=${entity}&key=${encodeURIComponent(entityKey)}`),
  });
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const pick = useRef<HTMLInputElement>(null);
  const cam = useRef<HTMLInputElement>(null);
  const photos = q.data ?? [];
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk });
    void qc.invalidateQueries({ queryKey: ["photos", "counts", entity] });
  };

  const send = async (list: File[]) => {
    const files = list.filter(isImageFile);
    if (files.length < list.length) toast(`${list.length - files.length} dosya resim olmadığı için atlandı`, true);
    let ok = 0;
    for (const [i, f] of files.entries()) {
      setBusy(`${i + 1} / ${files.length} yükleniyor…`);
      const form = new FormData();
      form.append("entity", entity);
      form.append("key", entityKey);
      form.append("file", f, f.name);
      const t = await makeThumb(f);
      if (t) form.append("thumb", t, "t.jpg");
      try {
        await upload(`/photos`, form, (pct) => setBusy(`${i + 1} / ${files.length} yükleniyor… %${pct}`));
        ok++;
      } catch (e) {
        toast(`${f.name}: ${errText(e)}`, true);
      }
    }
    setBusy(null);
    if (ok) toast(`${ok} fotoğraf eklendi`);
    refresh();
  };

  const remove = async (p: Photo) => {
    if (!confirm(`${p.filename} silinsin mi?`)) return;
    try {
      await api.del(`/photos/${p.id}`);
      forgetThumb(`/photos/${p.id}/thumb`);
      refresh();
    } catch (e) { toast(errText(e), true); }
  };
  const caption = async (p: Photo) => {
    const c = prompt("Fotoğraf açıklaması:", p.caption);
    if (c === null) return;
    try { await api.patch(`/photos/${p.id}`, { caption: c }); refresh(); } catch (e) { toast(errText(e), true); }
  };

  return (
    <div className={`photos${over ? " drop" : ""}`}
      onDragOver={(e) => { if (canEdit && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (canEdit) void send([...e.dataTransfer.files]); }}>
      {canEdit && (
        <div className="row" style={{ marginBottom: 8 }}>
          <button className="btn small" disabled={!!busy} onClick={() => pick.current?.click()}><ImagePlus size={15} /> Fotoğraf ekle</button>
          <button className="btn small only-touch" disabled={!!busy} onClick={() => cam.current?.click()}><Camera size={15} /> Çek</button>
          <span className="muted" style={{ fontSize: 12 }}>{busy ?? "Birden fazla seçebilir veya buraya sürükleyebilirsiniz."}</span>
          <input ref={pick} type="file" accept="image/*,.heic,.heif" multiple hidden
            onChange={(e) => { void send([...(e.target.files ?? [])]); e.target.value = ""; }} />
          <input ref={cam} type="file" accept="image/*" capture="environment" hidden
            onChange={(e) => { void send([...(e.target.files ?? [])]); e.target.value = ""; }} />
        </div>
      )}
      {q.isError && <div className="error">{errText(q.error)}</div>}
      {q.isSuccess && !photos.length && <div className="muted">Fotoğraf yok.</div>}
      {!!photos.length && (
        <div className="photo-grid">
          {photos.map((p, i) => (
            <figure key={p.id} className="photo" onClick={() => setOpen(i)} title={`${p.filename} · ${fmtBytes(p.size)}`}>
              <Thumb path={p.preview ? `/photos/${p.id}/thumb` : null} label={p.filename} />
              {p.caption && <figcaption>{p.caption}</figcaption>}
              {canEdit && (
                <button className="photo-del" aria-label="Sil" onClick={(e) => { e.stopPropagation(); void remove(p); }}><Trash2 size={14} /></button>
              )}
            </figure>
          ))}
        </div>
      )}
      {open !== null && photos.length > 0 && (
        <Viewer items={photos.map(photoItem)} start={open} onClose={() => setOpen(null)}
          actions={canEdit ? (it) => {
            const p = photos.find((x) => x.id === it.key);
            return p && <>
              <button className="btn small" onClick={() => void caption(p)} title="Açıklama"><Pencil size={16} /></button>
              <button className="btn small danger" onClick={() => void remove(p)} title="Sil"><Trash2 size={16} /></button>
            </>;
          } : undefined} />
      )}
    </div>
  );
}
