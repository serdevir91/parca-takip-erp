import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  ArrowDown, ArrowUp, Box, Boxes, ChevronDown, ChevronRight, Copy, FileSpreadsheet, IndentDecrease, IndentIncrease,
  Network, Plus, Trash2, Undo2,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../api/auth";
import { PageHeader, useProject } from "../components/Layout";
import TreeExcelModal, { type TreeExcelApply } from "../components/TreeExcelModal";
import { exportSheet } from "../api/exportFile";
import { errText, useToast } from "../components/Toast";
import { LOCALE, tx } from "../api/i18n";

type Item = {
  part_no: string; name?: string; assembly: boolean; qty: number; material: string; weight: number | null; rev: string;
  procurement: string; coating: string; children: Item[];
};
type TreeNode = Omit<Item, "children"> & { key: string; children: TreeNode[] };
type Draft = { tree: Item; rev: number; by: string; at: string };
type Version = { id: number; seq: number; filename: string; status: string };
type Flat = { node: TreeNode; depth: number; level: string; total: number };

const STATUS: Record<string, string> = { approved: tx("Onaylı"), pending: tx("Bekliyor"), rejected: tx("Reddedildi"), undone: tx("Geri alındı") };
const HISTORY = 50;

let lastKey = 0;
const newKey = () => `n${++lastKey}`;
const withKeys = (i: Item): TreeNode => ({ ...i, key: newKey(), children: (i.children ?? []).map(withKeys) });
const blank = (assembly: boolean, procurement: string): TreeNode => ({
  key: newKey(), part_no: "", name: "", assembly, qty: 1, material: "", weight: null, rev: "", procurement, coating: "", children: [],
});

function locate(n: TreeNode, key: string, parent: TreeNode | null = null): { node: TreeNode; parent: TreeNode | null } | null {
  if (n.key === key) return { node: n, parent };
  for (const c of n.children) {
    const hit = locate(c, key, n);
    if (hit) return hit;
  }
  return null;
}

function flatten(root: TreeNode, collapsed: Set<string>): Flat[] {
  const out: Flat[] = [];
  const walk = (node: TreeNode, depth: number, level: string, mult: number) => {
    const total = depth ? node.qty * mult : 1;
    out.push({ node, depth, level, total });
    if (!collapsed.has(node.key)) node.children.forEach((c, i) => walk(c, depth + 1, `${level}.${i + 1}`, total));
  };
  walk(root, 0, "1", 1);
  return out;
}

function counts(root: TreeNode): { rows: number; unique: number } {
  const seen = new Set<string>();
  let rows = 0;
  const walk = (n: TreeNode) => {
    rows += 1;
    if (n.part_no) seen.add(n.part_no);
    n.children.forEach(walk);
  };
  walk(root);
  return { rows, unique: seen.size };
}

export default function BomTree() {
  const { pid, project } = useProject();
  const toast = useToast();
  const navigate = useNavigate();
  const canEdit = useAuth().can("projects", "edit") && !project?.archived;

  const draftQ = useQuery({
    queryKey: ["bomDraft", pid],
    queryFn: () => api.get<{ draft: Draft | null; temin: string[] }>(`/projects/${pid}/bom/draft`),
    gcTime: 0, refetchOnWindowFocus: false,   // read once per visit; a cached draft may already be sent
  });
  const versionsQ = useQuery({
    queryKey: ["bomVersions", pid, "tree"],
    queryFn: () => api.get<Version[]>(`/projects/${pid}/bom/versions`),
  });
  const temin = useMemo(() => draftQ.data?.temin ?? [], [draftQ.data]);

  const [root, setRoot] = useState<TreeNode | null>(null);
  const [sel, setSel] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [past, setPast] = useState<TreeNode[]>([]);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState("");
  const [saveError, setSaveError] = useState("");
  const [conflict, setConflict] = useState("");
  const [retry, setRetry] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [askDelete, setAskDelete] = useState(false);
  const [excel, setExcel] = useState(false);

  const loaded = useRef(false);
  const rev = useRef<number>(0);
  const saving = useRef(false);
  const lastGroup = useRef<string | null>(null);
  const latest = useRef({ root, dirty, conflict });
  latest.current = { root, dirty, conflict };
  const partInput = useRef<HTMLInputElement>(null);

  const open = (tree: TreeNode) => {
    setRoot(tree);
    setSel(tree.key);
    setPast([]);
    setErrors([]);
    // A long tree opens with its first level only
    const big = counts(tree).rows > 200;
    setCollapsed(new Set(big ? tree.children.filter((c) => c.children.length).map((c) => c.key) : []));
  };

  useEffect(() => {
    const d = draftQ.data?.draft;
    if (loaded.current || !draftQ.data) return;
    loaded.current = true;
    if (d) {
      rev.current = d.rev;
      setSavedAt(d.at);
      open(withKeys(d.tree));
    }
  }, [draftQ.data]);

  // ---------- draft: saved a moment after the last edit, one request at a time ----------
  const flush = async (force = false) => {
    if (saving.current) return;
    const sent = latest.current.root;
    if (!sent) return;
    saving.current = true;
    try {
      const r = await api.put<{ rev: number; at: string }>(`/projects/${pid}/bom/draft`,
        { tree: sent, rev: force ? null : rev.current });
      rev.current = r.rev;
      setSavedAt(r.at);
      setSaveError("");
      setConflict("");
      if (latest.current.root === sent) setDirty(false);
      else setRetry((n) => n + 1);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(errText(e));
      else setSaveError(errText(e));
    } finally {
      saving.current = false;
    }
  };
  useEffect(() => {
    if (!dirty || !canEdit || conflict) return;
    const t = setTimeout(() => void flush(), 1500);
    return () => clearTimeout(t);
    // flush reads the latest tree from the ref
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, dirty, retry, conflict, canEdit]);
  useEffect(() => () => {
    const { root: r, dirty: d, conflict: c } = latest.current;
    if (r && d && !c) api.put(`/projects/${pid}/bom/draft`, { tree: r, rev: rev.current }).catch(() => {});
  }, [pid]);

  // ---------- editing ----------
  const change = (fn: (r: TreeNode) => void, group: string | null = null) => {
    if (!root) return;
    const next = structuredClone(root);
    fn(next);
    if (!group || group !== lastGroup.current) setPast((p) => [...p.slice(-(HISTORY - 1)), root]);
    lastGroup.current = group;
    setRoot(next);
    setDirty(true);
    setErrors([]);
  };
  const undo = () => {
    const prev = past[past.length - 1];
    if (!prev) return;
    setPast(past.slice(0, -1));
    setRoot(prev);
    if (!locate(prev, sel)) setSel(prev.key);
    lastGroup.current = null;
    setDirty(true);
  };

  const hit = root ? locate(root, sel) : null;

  /** What the user selected from a spreadsheet. One change, so one undo takes all of it back. */
  const applyExcel = (a: TreeExcelApply) => change((r) => {
    const nodes = (no: string): TreeNode[] => {
      const out: TreeNode[] = [];
      const walk = (n: TreeNode) => { if (n.part_no === no) out.push(n); n.children.forEach(walk); };
      walk(r);
      return out;
    };
    if (a.root) Object.assign(r, a.root);
    for (const c of a.changes) {
      const where = c.parent_no ? nodes(c.parent_no).flatMap((p) => p.children.filter((n) => n.part_no === c.part_no)) : nodes(c.part_no);
      for (const n of where) Object.assign(n, { [c.field]: c.new });
    }
    const picked = locate(r, sel)?.node;
    const fallback = picked?.assembly ? picked : r;
    for (const { id: _id, parent_no, ...item } of a.add) {
      const parents = nodes(parent_no);
      for (const p of parents) p.assembly = true;
      (parents[0] ?? fallback).children.push({ ...blank(item.assembly, temin[0] ?? ""), ...item, procurement: item.procurement || temin[0] || "" });
    }
  });
  const exportTree = async () => {
    if (!root) return;
    const rows = flatten(root, new Set()).map(({ node: n, level, total }) => [
      level, n.part_no, n.name ?? "", n.assembly ? tx("Montaj") : tx("Parça"), n.qty, total, n.material, n.weight, n.rev, n.procurement, n.coating]);
    try {
      await exportSheet(tx("Ürün ağacı"), [tx("Seviye"), tx("Parça No"), tx("Parça Adı"), tx("Tip"), tx("Adet"), tx("Toplam"), tx("Malzeme"),
        tx("Ağırlık (g)"), tx("Rev"), tx("Temin Şekli"), tx("Kaplama")], rows);
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const node = hit?.node ?? null;
  const parent = hit?.parent ?? null;
  const index = parent && node ? parent.children.findIndex((c) => c.key === node.key) : -1;
  const before = parent && index > 0 ? parent.children[index - 1] : null;

  const add = (assembly: boolean, sibling = false) => {
    if (!node) return;
    const n = blank(assembly, temin[0] ?? "");
    change((r) => {
      const at = locate(r, node.key);
      if (!at) return;
      if (at.node.assembly && !sibling) at.node.children.push(n);
      else if (at.parent) at.parent.children.splice(at.parent.children.indexOf(at.node) + 1, 0, n);
    });
    setCollapsed((s) => { const c = new Set(s); c.delete(node.key); return c; });
    setSel(n.key);
    setTimeout(() => partInput.current?.focus(), 0);
  };
  const move = (by: -1 | 1) => change((r) => {
    const at = locate(r, sel);
    if (!at?.parent) return;
    const list = at.parent.children;
    const i = list.indexOf(at.node);
    if (list[i + by]) [list[i], list[i + by]] = [list[i + by], list[i]];
  });
  const indent = () => change((r) => {
    const at = locate(r, sel);
    if (!at?.parent) return;
    const list = at.parent.children;
    const i = list.indexOf(at.node);
    if (i < 1 || !list[i - 1].assembly) return;
    list[i - 1].children.push(...list.splice(i, 1));
  });
  const outdent = () => change((r) => {
    const at = locate(r, sel);
    const up = at?.parent ? locate(r, at.parent.key) : null;
    if (!at || !up?.parent) return;
    const list = up.node.children;
    list.splice(list.indexOf(at.node), 1);
    up.parent.children.splice(up.parent.children.indexOf(up.node) + 1, 0, at.node);
  });
  const copy = () => change((r) => {
    const at = locate(r, sel);
    if (!at?.parent) return;
    at.parent.children.splice(at.parent.children.indexOf(at.node) + 1, 0, withKeys(at.node));
  });
  const remove = () => {
    if (!parent || !node) return;
    const next = parent.children[index + 1] ?? before ?? parent;
    change((r) => {
      const at = locate(r, sel);
      if (at?.parent) at.parent.children.splice(at.parent.children.indexOf(at.node), 1);
    });
    setSel(next.key);
  };
  const set = <K extends keyof Item>(field: K, value: TreeNode[K]) => change((r) => {
    const at = locate(r, sel);
    if (at) at.node[field] = value;
  }, `${sel}.${field}`);

  // ---------- item master ----------
  const [focused, setFocused] = useState(false);
  const [term, setTerm] = useState("");
  const typed = node?.part_no ?? "";
  useEffect(() => {
    const t = setTimeout(() => setTerm(typed.trim()), 250);
    return () => clearTimeout(t);
  }, [typed]);
  const itemsQ = useQuery({
    queryKey: ["bomItems", pid, term],
    queryFn: () => api.get<Item[]>(`/projects/${pid}/bom/items?q=${encodeURIComponent(term)}`),
    enabled: focused && term.length >= 2, staleTime: 30_000,
  });
  const picks = focused ? (itemsQ.data ?? []).filter((i) => i.part_no !== typed) : [];

  const pick = async (item: Item) => {
    setFocused(false);
    let kids: Item[] = [];
    if (item.assembly && !node?.children.length) {
      try {
        const r = await api.get<{ tree: Item }>(`/projects/${pid}/bom/items/tree?part_no=${encodeURIComponent(item.part_no)}`);
        kids = r.tree.children;
      } catch (e) {
        toast(errText(e), true);
      }
    }
    change((r) => {
      const at = locate(r, sel);
      if (!at) return;
      const { qty, children, key } = at.node;
      Object.assign(at.node, item, { qty, key, children: kids.length ? kids.map(withKeys) : children });
    });
    if (kids.length) toast(tx("{0} alt kalemleriyle eklendi", item.part_no));
  };

  // ---------- start and send ----------
  const startEmpty = () => {
    const r = blank(true, temin[0] ?? "");
    r.part_no = project?.root_part_no ?? "";
    open(r);
    setDirty(true);
    setTimeout(() => partInput.current?.focus(), 0);
  };
  const startFrom = async (vid: string) => {
    try {
      const r = await api.get<{ tree: Item | null }>(`/projects/${pid}/bom/versions/${vid}/tree`);
      if (r.tree) {
        open(withKeys(r.tree));
        setDirty(true);
      }
    } catch (e) {
      toast(errText(e), true);
    }
  };
  // With a BOM there is already a tree: the file is matched against the current one, not an empty draft
  const startExcel = async () => {
    const base = project?.current_version_id ?? versionsQ.data?.[0]?.id;
    if (base) await startFrom(String(base));
    else startEmpty();
    setExcel(true);
  };
  const discard = async () => {
    setAskDelete(false);
    setDirty(false);
    try {
      await api.del(`/projects/${pid}/bom/draft`);
      rev.current = 0;
      setRoot(null);
      setSavedAt("");
      setConflict("");
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const reloadDraft = async () => {
    try {
      const r = await api.get<{ draft: Draft | null }>(`/projects/${pid}/bom/draft`);
      setConflict("");
      setDirty(false);
      rev.current = r.draft?.rev ?? 0;
      if (r.draft) open(withKeys(r.draft.tree));
    } catch (e) {
      toast(errText(e), true);
    }
  };
  const send = async () => {
    if (!root) return;
    setSending(true);
    setErrors([]);
    setDirty(false);
    latest.current.dirty = false;
    while (saving.current) await new Promise((r) => setTimeout(r, 50));
    try {
      await api.post(`/projects/${pid}/bom/tree/submit`, { tree: root, note });
      toast(tx("Sürüm oluşturuldu. Karşılaştırıp onaylayın."));
      navigate(`/p/${pid}/bom`);
    } catch (e) {
      setErrors(errText(e).split("\n"));
      setDirty(true);
    } finally {
      setSending(false);
    }
  };

  const rows = useMemo(() => (root ? flatten(root, collapsed) : []), [root, collapsed]);
  const total = useMemo(() => (root ? counts(root) : null), [root]);
  const versions = versionsQ.data ?? [];
  const toggle = (key: string) => setCollapsed((s) => {
    const c = new Set(s);
    if (c.has(key)) c.delete(key); else c.add(key);
    return c;
  });

  const header = (
    <PageHeader icon={Network} title={tx("Ürün ağacı")}
      sub={tx("Ürünün hangi montaj ve parçalardan, kaçar adet oluştuğunu elle kurun. Gönderdiğiniz ağaç BOM sürümü olur.")} />
  );

  if (!root) {
    return (
      <div className="page">
        {header}
        <div className="card tree-start">
          <h3>{tx("Nasıl oluşturulur?")}</h3>
          <ol>
            <li>{tx("En üste bitmiş ürünü yazın.")}</li>
            <li>{tx("Altına doğrudan monte edilen alt montajları ve parçaları ekleyin.")}</li>
            <li>{tx("Her satıra bir üst montajdaki adedini yazın. Toplam adet kendiliğinden hesaplanır.")}</li>
            <li>{tx("Satırın imalat mı hazır alım mı olduğunu seçin.")}</li>
            <li>{tx("Ağacı sürüm olarak gönderin, BOM sürümlerinden karşılaştırıp onaylayın.")}</li>
          </ol>
          {canEdit ? (
            <div className="row" style={{ alignItems: "center" }}>
              <button className="btn primary" disabled={!draftQ.data} onClick={startEmpty}><Plus size={16} />{" "}{tx("Boş ağaçla başla")}</button>
              <button className="btn" disabled={!draftQ.data} onClick={() => void startExcel()}><FileSpreadsheet size={16} />{" "}{versions.length ? tx("Excel ile eşleştir") : tx("Excel'den başla")}</button>
              {versions.length > 0 && (
                <select aria-label={tx("Başlangıç sürümü")} value="" onChange={(e) => void startFrom(e.target.value)}>
                  <option value="">{tx("Bir BOM sürümünden başla…")}</option>
                  {versions.map((v) => <option key={v.id} value={v.id}>#{v.seq} {v.filename} ({STATUS[v.status] ?? v.status})</option>)}
                </select>
              )}
            </div>
          ) : <div className="muted">{tx("Bu projede ürün ağacı taslağı yok.")}</div>}
        </div>
      </div>
    );
  }

  const saveText = saveError ? tx("Kaydedilemedi: {0}", saveError) : dirty ? tx("Kaydediliyor…")
    : savedAt ? tx("Taslak kaydedildi {0}", new Date(savedAt).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })) : "";
  const buying = node?.assembly && node.procurement === "Hazır Alım";

  return (
    <div className="page">
      {header}
      {conflict && (
        <div className="card tree-alert">
          <span>{conflict}</span>
          <button className="btn small" onClick={() => void reloadDraft()}>{tx("Son taslağı yükle")}</button>
          <button className="btn small" onClick={() => void flush(true)}>{tx("Benimkini kaydet")}</button>
        </div>
      )}
      <div className="toolbar tree-bar">
        {canEdit && (
          <>
            <button className="btn small" disabled={!past.length} onClick={undo}><Undo2 size={14} />{" "}{tx("Geri al")}</button>
            {askDelete ? (
              <>
                <button className="btn small danger" onClick={() => void discard()}>{tx("Taslak silinsin")}</button>
                <button className="btn small" onClick={() => setAskDelete(false)}>{tx("Vazgeç")}</button>
              </>
            ) : <button className="btn small" onClick={() => setAskDelete(true)}>{tx("Taslağı sil")}</button>}
            <button className="btn small" onClick={() => setExcel(true)}><FileSpreadsheet size={14} />{" "}{tx("Excel ile eşleştir")}</button>
          </>
        )}
        <button className="btn small" onClick={() => void exportTree()}>{tx("Excel'e aktar")}</button>
        <span className="muted">{tx("{0} satır · {1} farklı kalem", total?.rows.toLocaleString(LOCALE), total?.unique.toLocaleString(LOCALE))}</span>
        <span className={saveError ? "error" : "muted"}>{saveText}</span>
        <span style={{ flex: 1 }} />
        {canEdit && (
          <>
            <input placeholder={tx("Sürüm notu (isteğe bağlı)")} value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn primary" disabled={sending} onClick={() => void send()}>
              {sending ? tx("Gönderiliyor…") : tx("Sürüm olarak gönder")}
            </button>
          </>
        )}
      </div>
      {errors.length > 0 && (
        <div className="card tree-alert" role="alert">
          <ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      <div className="tree-layout">
        <div className="card tree-list" role="tree" aria-label={tx("Ürün ağacı")}>
          {rows.map(({ node: n, depth, level, total: sum }) => (
            <div key={n.key} role="treeitem" aria-selected={n.key === sel} aria-level={depth + 1}
              className={`tree-row${n.key === sel ? " on" : ""}`} style={{ paddingLeft: 6 + depth * 18 }}
              onClick={() => setSel(n.key)}>
              {n.children.length > 0 ? (
                <button className="tree-fold" aria-label={collapsed.has(n.key) ? tx("Aç") : tx("Kapat")}
                  onClick={(e) => { e.stopPropagation(); toggle(n.key); }}>
                  {collapsed.has(n.key) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                </button>
              ) : <span className="tree-fold" />}
              {n.assembly ? <Boxes size={15} className="tree-asm" /> : <Box size={15} className="muted" />}
              <span className="muted tree-lvl">{level}</span>
              <span className={`tree-no${n.part_no ? "" : " error"}`}>{n.part_no || tx("Numara yok")}</span>
              {n.name && <span className="muted">{n.name}</span>}
              {depth > 0 && <span className="muted tree-qty">{tx("{0} adet", n.qty)}{sum !== n.qty ? tx(" · toplam {0}", sum.toLocaleString(LOCALE)) : ""}</span>}
            </div>
          ))}
        </div>
        {node && (
          <fieldset className="card tree-form" disabled={!canEdit}>
            {canEdit && (
              <div className="tree-actions">
                <button className="btn small primary" onClick={() => add(false)}><Plus size={14} />{" "}{tx("Parça")}</button>
                <button className="btn small primary" onClick={() => add(true)}><Plus size={14} />{" "}{tx("Alt montaj")}</button>
                <button className="btn small" title={tx("Yukarı taşı")} aria-label={tx("Yukarı taşı")} disabled={index < 1} onClick={() => move(-1)}><ArrowUp size={14} /></button>
                <button className="btn small" title={tx("Aşağı taşı")} aria-label={tx("Aşağı taşı")} disabled={!parent || index >= parent.children.length - 1} onClick={() => move(1)}><ArrowDown size={14} /></button>
                <button className="btn small" title={tx("Üstteki montajın altına al")} aria-label={tx("Üstteki montajın altına al")} disabled={!before?.assembly} onClick={indent}><IndentIncrease size={14} /></button>
                <button className="btn small" title={tx("Bir seviye yukarı çıkar")} aria-label={tx("Bir seviye yukarı çıkar")} disabled={!parent || parent === root} onClick={outdent}><IndentDecrease size={14} /></button>
                <button className="btn small" title={tx("Kopyala")} aria-label={tx("Kopyala")} disabled={!parent} onClick={copy}><Copy size={14} /></button>
                <button className="btn small" title={tx("Sil")} aria-label={tx("Sil")} disabled={!parent} onClick={remove}><Trash2 size={14} /></button>
              </div>
            )}
            <label className="tree-pick">{tx("Parça numarası")}
              <input ref={partInput} value={node.part_no} maxLength={200} autoComplete="off"
                onChange={(e) => { setFocused(true); set("part_no", e.target.value); }}
                onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(false, !!parent); } }} />
              {picks.length > 0 && (
                <div className="tree-picks">
                  {picks.map((i) => (
                    <button key={i.part_no} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => void pick(i)}>
                      {i.assembly ? <Boxes size={14} /> : <Box size={14} />}
                      <span>{i.part_no}</span>
                      <span className="muted">{i.name || i.material}</span>
                    </button>
                  ))}
                </div>
              )}
            </label>
            <label>{tx("Parça adı")}
              <input value={node.name ?? ""} maxLength={300} onChange={(e) => set("name", e.target.value)} />
            </label>
            <div className="adm-two">
              <label>{tx("Tür")}
                <select value={node.assembly ? "a" : "p"} disabled={!parent || node.children.length > 0}
                  onChange={(e) => set("assembly", e.target.value === "a")}>
                  <option value="p">{tx("Parça")}</option>
                  <option value="a">{tx("Montaj")}</option>
                </select>
              </label>
              <label>{tx("Adet (üst montajda)")}
                <input type="number" min={1} max={1000000} step={1} value={parent ? node.qty : 1} disabled={!parent}
                  onChange={(e) => set("qty", Math.max(0, Math.min(1000000, Math.trunc(Number(e.target.value)) || 0)))} />
              </label>
            </div>
            <div className="adm-two">
              <label>{tx("Temin şekli")}
                <select value={node.procurement} onChange={(e) => set("procurement", e.target.value)}>
                  <option value="">{tx("Seçilmedi")}</option>
                  {temin.map((t) => <option key={t}>{tx(t)}</option>)}
                </select>
              </label>
              <label>{tx("Revizyon")}
                <input value={node.rev} maxLength={32} onChange={(e) => set("rev", e.target.value)} />
              </label>
            </div>
            <div className="adm-two">
              <label>{tx("Malzeme")}
                <input value={node.material} maxLength={200} onChange={(e) => set("material", e.target.value)} />
              </label>
              <label>{tx("Ağırlık (g)")}
                <input type="number" min={0} step="any" value={node.weight ?? ""}
                  onChange={(e) => set("weight", e.target.value === "" ? null : Math.max(0, Number(e.target.value)))} />
              </label>
            </div>
            <label>{tx("Kaplama")}
              <input value={node.coating} maxLength={200} onChange={(e) => set("coating", e.target.value)} />
            </label>
            {buying && <div className="muted">{tx("Hazır alım montajı tek kalem sayılır. İçindeki satırlar ayrıca takip edilmez.")}</div>}
            <div className="muted">{tx("Enter yeni satır açar. Daha önce kullanılan numarayı seçince bilgileri, montajsa alt kalemleri gelir. \"DIN 912 M10 x 60\" gibi adlar bağlantı elemanı olarak tanınır.")}</div>
          </fieldset>
        )}
      </div>
      {excel && root && (
        <TreeExcelModal pid={pid} tree={root} target={(node?.assembly ? node : root).part_no} onApply={applyExcel} onClose={() => setExcel(false)} />
      )}
    </div>
  );
}
