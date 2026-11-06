import { useEffect, useState } from "react";
import { FileDown } from "lucide-react";
import { useLocation } from "react-router-dom";
import { exportBook, tableSheet, type Sheet } from "../api/exportFile";
import { errText, useToast } from "./Toast";
import { tx } from "../api/i18n";

/** Plain tables on screen. Grids are left out: they have their own export, which also covers rows off screen. */
const plainTables = () => [...document.querySelectorAll<HTMLTableElement>(".main table")]
  .filter((t) => !t.closest(".dg") && t.offsetParent !== null && t.tBodies[0]?.rows.length);

const text = (e: Element | null | undefined) => (e?.textContent ?? "").replace(/\s+/g, " ").trim();

/** Puts every plain table of the page into one Excel file, so a new table needs no export code of its own. */
export default function TableExport() {
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const { pathname } = useLocation();
  const toast = useToast();

  useEffect(() => {
    const main = document.querySelector(".main");
    if (!main) return;
    let timer = 0;
    const look = () => { window.clearTimeout(timer); timer = window.setTimeout(() => setCount(plainTables().length), 250); };
    look();
    const seen = new MutationObserver(look);
    seen.observe(main, { childList: true, subtree: true });
    return () => { window.clearTimeout(timer); seen.disconnect(); };
  }, [pathname]);

  if (!count) return null;
  const run = async () => {
    const title = text(document.querySelector(".main h1")) || tx("Tablo");
    const sheets = plainTables()
      .map((t) => tableSheet(t, text(t.closest(".card")?.querySelector("h2, h3, h4")) || title))
      .filter((s): s is Sheet => s !== null);
    setBusy(true);
    try {
      await exportBook(title, sheets);
    } catch (e) {
      toast(errText(e), true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="icon-btn" disabled={busy} title={tx("Bu sayfadaki tabloları Excel'e aktar")} aria-label={tx("Bu sayfadaki tabloları Excel'e aktar")} onClick={() => void run()}>
      <FileDown size={17} />
      <span className="icon-btn-text">{tx("Excel'e aktar")}</span>
    </button>
  );
}
