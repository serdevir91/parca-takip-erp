import { api, download } from "./client";

export type Sheet = { name: string; columns: string[]; rows: unknown[][] };

/** Tables as one Excel file, one sheet each. The server builds it, so every client can save it. */
export async function exportBook(name: string, sheets: Sheet[]): Promise<void> {
  const { id } = await api.post<{ id: string }>("/export/book", { sheets });
  await download(`/export/grid/${id}?name=${encodeURIComponent(name)}`, `${name}.xlsx`);
}

export const exportSheet = (name: string, columns: string[], rows: unknown[][]) => exportBook(name, [{ name, columns, rows }]);

/** A cell as Excel should hold it: what the user sees, a number only when nothing can be lost. Part numbers like 00123 stay text. */
function cellValue(td: HTMLTableCellElement): string | number | null {
  const fields = [...td.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea")]
    .filter((f) => !(f instanceof HTMLInputElement && ["checkbox", "radio", "file", "hidden"].includes(f.type)));
  const text = fields.length
    ? fields.map((f) => (f instanceof HTMLSelectElement ? f.selectedOptions[0]?.text ?? "" : f.value)).join(" ")
    : (() => {
      const copy = td.cloneNode(true) as HTMLElement;
      copy.querySelectorAll("button, svg, .no-export").forEach((e) => e.remove());
      return copy.textContent ?? "";
    })();
  const t = text.replace(/\s+/g, " ").trim();
  if (!t) return null;
  return /^-?(0|[1-9]\d{0,14})$/.test(t) ? Number(t) : t;
}

/** A table on screen as a sheet: columns without a title are buttons and stay out. */
export function tableSheet(table: HTMLTableElement, name: string): Sheet | null {
  const lines = [...table.rows];
  const head = lines.find((r) => r.parentElement?.tagName === "THEAD") ?? (lines[0]?.cells[0]?.tagName === "TH" ? lines[0] : null);
  const body = lines.filter((r) => r !== head && r.parentElement?.tagName !== "THEAD");
  if (!body.length) return null;
  const spread = (r: HTMLTableRowElement) => [...r.cells].flatMap((c) => [c, ...Array<null>(Math.max(0, c.colSpan - 1)).fill(null)]);
  const titles = head ? spread(head).map((c) => (c ? (c.textContent ?? "").replace(/\s+/g, " ").trim() : "")) : [];
  const width = Math.max(titles.length, ...body.map((r) => spread(r).length));
  const keep = Array.from({ length: width }, (_, i) => i).filter((i) => !head || titles[i]);
  return {
    name,
    columns: keep.map((i) => titles[i] || String(i + 1)),
    rows: body.map((r) => { const cells = spread(r); return keep.map((i) => (cells[i] ? cellValue(cells[i]!) : null)); }),
  };
}
