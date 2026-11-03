import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Project } from "../../types";

// ---------- types (backend/app/services/erp.py) ----------
export type ItemKind = "part" | "fastener" | "other";
export type PoLine = {
  id?: number; seq?: number; code: string; kind: ItemKind | string; kind_label?: string; description: string; unit: string;
  qty: number; received_qty?: number; remaining?: number; unit_price: number | null; amount?: number | null;
};
export type PurchaseOrder = {
  id: number; no: string; firm_id: number | null; firm_name: string; project_id: number | null; project_name: string | null;
  status: string; status_label: string; order_date: string | null; due_date: string | null; overdue: boolean;
  currency: string; note: string; created_at: string | null; created_by: string; line_count: number; total: number;
  received_value: number; received_pct: number; missing_price: number; lines?: PoLine[];
};
export type WorkOrder = {
  id: number; no: string; project_id: number | null; project_name: string | null; part_no: string; description: string;
  qty: number; done_qty: number; remaining: number; firm_name: string; subcontract: boolean; status: string;
  status_label: string; start_date: string | null; due_date: string | null; overdue: boolean; unit_cost: number | null;
  total_cost: number | null; note: string; created_at: string | null; created_by: string;
};
export type StockItem = {
  id: number; code: string; name: string; kind: ItemKind | string; kind_label: string; unit: string; qty: number;
  min_qty: number; unit_cost: number | null; value: number | null; low: boolean; location: string; note: string;
  updated_at: string | null;
};
export type StockMove = {
  id: number; ts: string | null; kind: string; kind_label: string; qty: number; balance: number; unit_cost: number | null;
  project_id: number | null; project_name: string | null; ref: string; note: string; username: string;
  code: string | null; name: string | null;
};
export type FirmBrief = { id: number; name: string; kind: string; contact: string; phone: string; email: string; lead_days: number };

export const ITEM_KINDS: { value: ItemKind; label: string }[] = [
  { value: "part", label: "Parça" },
  { value: "fastener", label: "Bağlantı elemanı" },
  { value: "other", label: "Diğer" },
];

// Status colours: hex without '#', rendered through statusStyle like part statuses
export const PO_COLORS: Record<string, string> = {
  draft: "E7E6E6", sent: "FFEB9C", partial: "F8CBAD", received: "C6EFCE", cancelled: "D9D9D9",
};
export const WO_COLORS: Record<string, string> = {
  planned: "E7E6E6", in_progress: "FFEB9C", done: "C6EFCE", cancelled: "D9D9D9",
};

export const fmtQty = (n: number | null | undefined) =>
  n == null ? "" : n.toLocaleString("tr-TR", { maximumFractionDigits: 3 });
export const fmtMoney = (n: number | null | undefined, cur = "TRY") =>
  n == null ? "" : `${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur === "TRY" ? "₺" : cur}`;
export const fmtDay = (s: string | null | undefined) => {
  if (!s) return "";
  const d = new Date(`${s.slice(0, 10)}T00:00:00`);
  return isNaN(d.getTime()) ? s : d.toLocaleDateString("tr-TR");
};
export const today = () => new Date().toISOString().slice(0, 10);
export const addDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
export const trIncludes = (hay: string, needle: string) =>
  hay.toLocaleLowerCase("tr-TR").includes(needle.trim().toLocaleLowerCase("tr-TR"));
/** Number input value -> number | null (empty = null). */
export const numOrNull = (v: string): number | null => {
  const t = v.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};

export function useFirms(kind?: "supplier" | "manufacturer" | "customer") {
  return useQuery({
    queryKey: ["firms", kind ?? ""],
    queryFn: () => api.get<FirmBrief[]>(`/firms${kind ? `?kind=${kind}` : ""}`),
    staleTime: 60_000,
  });
}

export function useProjects() {
  return useQuery({ queryKey: ["projects", "picker"], queryFn: () => api.get<Project[]>("/projects"), staleTime: 60_000 });
}

export function FirmSelect({ value, onChange, kind, emptyLabel = "(Firma seçilmedi)" }: {
  value: number | null; onChange: (id: number | null) => void; kind?: "supplier" | "manufacturer" | "customer"; emptyLabel?: string;
}) {
  const firms = useFirms(kind);
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{emptyLabel}</option>
      {(firms.data ?? []).map((f) => (
        <option key={f.id} value={f.id}>{f.name}{f.lead_days ? ` (termin ${f.lead_days} gün)` : ""}</option>
      ))}
    </select>
  );
}

export function ProjectSelect({ value, onChange, emptyLabel = "(Proje yok)" }: {
  value: number | null; onChange: (id: number | null) => void; emptyLabel?: string;
}) {
  const projects = useProjects();
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{emptyLabel}</option>
      {(projects.data ?? []).filter((p) => !p.archived || p.id === value).map((p) => (
        <option key={p.id} value={p.id}>{p.name}</option>
      ))}
    </select>
  );
}

/** Firm name picker for work orders: "" = iç üretim, otherwise a manufacturer (free text allowed). */
export function MakerInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const firms = useFirms("manufacturer");
  const sub = value !== "";
  return (
    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      <select value={sub ? "sub" : "in"} onChange={(e) => onChange(e.target.value === "sub" ? (firms.data?.[0]?.name ?? " ") : "")}>
        <option value="in">İç üretim</option>
        <option value="sub">Fason</option>
      </select>
      {sub && (
        <>
          <input list="erp-makers" value={value.trim() ? value : ""} placeholder="Fason firma" onChange={(e) => onChange(e.target.value || " ")} />
          <datalist id="erp-makers">{(firms.data ?? []).map((f) => <option key={f.id} value={f.name} />)}</datalist>
        </>
      )}
    </div>
  );
}
