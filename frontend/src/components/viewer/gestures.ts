import { useEffect, useRef, type RefObject } from "react";

export type GestureHandlers = {
  /** Drag with mouse or one finger, in screen pixels. */
  pan: (dx: number, dy: number) => void;
  /** Wheel or pinch: multiply the zoom by `factor` around (cx, cy) relative to the element. */
  zoom: (factor: number, cx: number, cy: number) => void;
  dbl?: (cx: number, cy: number) => void;
};

/** Mouse wheel zoom, drag to pan, two-finger pinch and double click on one element. */
export function useGestures(ref: RefObject<HTMLElement | null>, handlers: GestureHandlers, enabled = true) {
  const h = useRef(handlers);
  h.current = handlers;

  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    const pts = new Map<number, { x: number; y: number }>();
    let lastDist = 0;
    const rel = (x: number, y: number): [number, number] => {
      const r = el.getBoundingClientRect();
      return [x - r.left, y - r.top];
    };
    const spread = () => {
      const [a, b] = [...pts.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };

    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const [cx, cy] = rel(e.clientX, e.clientY);
      const step = e.deltaMode === 1 ? 0.05 : e.ctrlKey ? 0.01 : 0.0015; // lines, trackpad pinch, pixels
      h.current.zoom(Math.exp(-e.deltaY * step), cx, cy);
    };
    const down = (e: PointerEvent) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if ((e.target as HTMLElement).closest("button, input, a")) return;
      el.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 2) lastDist = spread();
      el.classList.add("grabbing");
    };
    const move = (e: PointerEvent) => {
      const p = pts.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x;
      const dy = e.clientY - p.y;
      p.x = e.clientX;
      p.y = e.clientY;
      if (pts.size === 1) { if (dx || dy) h.current.pan(dx, dy); }
      else if (pts.size === 2) {
        const d = spread();
        const [a, b] = [...pts.values()];
        const [cx, cy] = rel((a.x + b.x) / 2, (a.y + b.y) / 2);
        if (lastDist > 0) h.current.zoom(d / lastDist, cx, cy);
        lastDist = d;
      }
    };
    const up = (e: PointerEvent) => {
      pts.delete(e.pointerId);
      lastDist = pts.size === 2 ? spread() : 0;
      if (!pts.size) el.classList.remove("grabbing");
    };
    const dbl = (e: MouseEvent) => {
      const [cx, cy] = rel(e.clientX, e.clientY);
      h.current.dbl?.(cx, cy);
    };

    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("dblclick", dbl);
    return () => {
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("dblclick", dbl);
    };
  }, [ref, enabled]);
}
