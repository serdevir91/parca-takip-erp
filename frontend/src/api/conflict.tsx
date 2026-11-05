import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal } from "../pages/admin/shared";
import { ApiError } from "./client";

type Pending = { message: string; answer: (overwrite: boolean) => void };
let ask: ((p: Pending) => void) | null = null;

const conflictOf = (e: unknown): string | null => {
  const detail = e instanceof ApiError ? (e.body as { detail?: { conflict?: boolean; message?: string } } | undefined)?.detail : undefined;
  return detail?.conflict ? detail.message ?? "Bu kaydı siz düzenlerken başka biri değiştirdi." : null;
};

/**
 * Save a form against the revision it was opened with (backend/app/services/conflict.py).
 * When someone else saved first the user decides; sending no revision is the deliberate overwrite.
 */
export async function saveRev<T>(rev: number | undefined, send: (rev: number | undefined) => Promise<T>): Promise<T> {
  try {
    return await send(rev);
  } catch (e) {
    const message = conflictOf(e);
    if (!message || !ask) throw e;
    const show = ask;
    const overwrite = await new Promise<boolean>((answer) => show({ message, answer }));
    if (!overwrite) throw new ApiError(409, "Değişikliğiniz kaydedilmedi. Güncel hali görmek için formu kapatıp yeniden açın.");
    return send(undefined);
  }
}

/** Mounted once; any form using saveRev opens this dialog. */
export function ConflictHost() {
  const qc = useQueryClient();
  const [pending, setPending] = useState<Pending | null>(null);
  useEffect(() => {
    ask = setPending;
    return () => { ask = null; };
  }, []);
  if (!pending) return null;
  const answer = (overwrite: boolean) => {
    pending.answer(overwrite);
    setPending(null);
    if (!overwrite) void qc.invalidateQueries();
  };
  return (
    <Modal title="Başkası değiştirdi" onClose={() => answer(false)}
      footer={<>
        <button className="btn" onClick={() => answer(false)}>Onlarınki kalsın</button>
        <button className="btn danger" onClick={() => answer(true)}>Yine de kaydet</button>
      </>}>
      <p>{pending.message}</p>
      <p className="muted">“Yine de kaydet” sizin formunuzdaki değerleri onların değişikliğinin üzerine yazar.</p>
    </Modal>
  );
}
