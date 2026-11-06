import { useEffect, useRef, useState } from "react";
import { blobUrl } from "../../api/client";

// Object URLs for thumbnails, shared by every component and kept for the session (they are small).
const cache = new Map<string, Promise<string | null>>();
let active = 0;
const queue: (() => void)[] = [];

function load(path: string): Promise<string | null> {
  let p = cache.get(path);
  if (!p) {
    p = new Promise<string | null>((resolve) => {
      const run = () => {
        active++;
        blobUrl(path).then(resolve, () => { cache.delete(path); resolve(null); })   // a failure is not kept: the next view asks again
          .finally(() => { active--; queue.shift()?.(); });
      };
      if (active < 6) run(); else queue.push(run);
    });
    cache.set(path, p);
  }
  return p;
}

/** Drop a cached thumbnail (after the file was replaced or deleted). */
export function forgetThumb(path: string) {
  void cache.get(path)?.then((u) => u && URL.revokeObjectURL(u));
  cache.delete(path);
}

/** Lazy, cached preview image of a protected API file; shows `label`'s extension when there is none. */
export default function Thumb({ path, label, className }: { path?: string | null; label: string; className?: string }) {
  const [url, setUrl] = useState<string | null | undefined>(undefined);
  const [seen, setSeen] = useState(() => !!path && cache.has(path));
  const ph = useRef<HTMLSpanElement>(null);
  // Big galleries: fetch only the thumbnails that scroll into view
  useEffect(() => {
    const el = ph.current;
    if (seen || !el || typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); }, { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  useEffect(() => {
    if (!path) { setUrl(null); return; }
    if (!seen) return;
    let alive = true;
    void load(path).then((u) => alive && setUrl(u));
    return () => { alive = false; };
  }, [path, seen]);
  if (url) return <img className={className ?? "thumb-img"} src={url} alt={label} draggable={false} />;
  const ext = label.includes(".") ? label.split(".").pop()!.toUpperCase().slice(0, 5) : "DOSYA";
  return <span ref={ph} className={`thumb-ph${className ? ` ${className}` : ""}`}>{url === undefined && path ? "…" : ext}</span>;
}
