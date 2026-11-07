import { useEffect, useRef, useState, type ReactNode } from "react";

export type PrintChoice = { label: string; hint: string; run: () => void };

/** One print button with its ways of printing, so a toolbar stays one button wide. */
export default function PrintMenu({ label, choices, disabled }: { label: ReactNode; choices: PrintChoice[]; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="dg-menu-wrap" ref={wrap}>
      <button className="btn small" disabled={disabled} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>{label}</button>
      {open && (
        <div className="dg-menu card print-menu" role="menu">
          {choices.map((c) => (
            <button key={c.label} role="menuitem" className="btn small" onClick={() => { setOpen(false); c.run(); }}>
              <span><b>{c.label}</b><small className="muted">{c.hint}</small></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
