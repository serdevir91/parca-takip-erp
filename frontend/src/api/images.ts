import { LOCALE } from "./i18n";
/** Small JPEG preview made in the browser before upload (the server has no image library).
 *  null when the browser cannot decode the file (HEIC on most browsers, broken files). */
export async function makeThumb(file: Blob, max = 480): Promise<Blob | null> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return null;
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(bmp.width * k));
    c.height = Math.max(1, Math.round(bmp.height * k));
    const ctx = c.getContext("2d");
    if (!ctx) return null;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    return await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", 0.82));
  } catch {
    return null;
  }
}

export const isImageFile = (f: File) => f.type.startsWith("image/") || /\.(jpe?g|png|gif|webp|bmp|heic|heif)$/i.test(f.name);

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 0 })} KB`;
  return `${(n / 1024 / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 })} MB`;
}
