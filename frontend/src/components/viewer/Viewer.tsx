import { useCallback, useEffect, useState, type ReactNode } from "react";
import { download } from "../../api/client";
import PdfViewer from "../PdfViewer";
import { errText, useToast } from "../Toast";
import ImageLightbox from "./ImageLightbox";
import Thumb from "./Thumb";

export type ViewItem = {
  key: string | number;
  name: string;
  /** API path of the full file */
  path: string;
  /** API path of a small preview for the strip; omit to show the extension */
  thumb?: string;
  kind: "pdf" | "image";
  caption?: string;
};

/** Opens a list of PDFs and images in the in-app viewers with previous/next and a thumbnail strip. */
export default function Viewer({ items, start = 0, onClose, actions }: {
  items: ViewItem[]; start?: number; onClose: () => void; actions?: (item: ViewItem) => ReactNode;
}) {
  const toast = useToast();
  const [i, setI] = useState(start);
  const n = items.length;
  useEffect(() => { if (i >= n && n) setI(n - 1); if (!n) onClose(); }, [i, n, onClose]);
  const prev = useCallback(() => setI((x) => (x - 1 + n) % n), [n]);
  const next = useCallback(() => setI((x) => (x + 1) % n), [n]);
  const it = items[Math.min(i, n - 1)];
  if (!it) return null;
  const nav = { index: i, count: n, prev, next };
  const dl = () => void download(it.path, it.name).catch((e) => toast(errText(e), true));
  const footer = n > 1 ? (
    <div className="viewer-strip">
      {items.map((x, j) => (
        <button key={x.key} className={j === i ? "on" : ""} onClick={() => setI(j)} title={x.name}>
          <Thumb path={x.thumb} label={x.name} />
        </button>
      ))}
    </div>
  ) : undefined;
  const extra = actions?.(it);
  return it.kind === "pdf"
    ? <PdfViewer key={it.key} src={it.path} title={it.name} onClose={onClose} onDownload={dl} nav={nav} footer={footer} actions={extra} />
    : <ImageLightbox key={it.key} src={it.path} title={it.name} caption={it.caption} onClose={onClose} onDownload={dl}
        nav={nav} footer={footer} actions={extra} />;
}
