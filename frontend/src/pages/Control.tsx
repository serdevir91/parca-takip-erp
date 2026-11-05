import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../api/auth";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import DataGrid, { type GridColumn } from "../components/DataGrid";
import { statusStyle } from "../theme/theme";
import { LOCALE, tx } from "../api/i18n";

// Backend: backend/app/api/control.py
const OPEN = "Açık";
const RESOLVED = "Çözüldü";

type Severity = "error" | "warning" | "info";

type Issue = {
  key: string;
  id: number | null;
  kind: string;
  part_no: string;
  message: string;
  levels: string[];
  severity: Severity | string;
  manual: boolean;
  present: boolean;
  status: string;
  note: string;
  resolved_by: string;
  resolved_at: string | null;
  created_by: string;
};

type ControlResp = {
  items: Issue[];
  stale: Issue[];
  kinds: Record<string, number>;
  counts: { total: number; open: number; resolved: number; error: number };
};

const SEV_LABEL: Record<string, string> = { error: tx("Hata"), warning: tx("Uyarı"), info: tx("Bilgi") };
const SEV_ORDER: Record<string, number> = { error: 0, warning: 1, info: 2 };
const SEV_COLOR: Record<string, string> = { error: "FFC7CE", warning: "FFEB9C", info: "DDEBF7" };
const RESOLVED_COLOR = "C6EFCE";

type StatusFilter = "open" | "resolved" | "all";

const fmt = (n: number) => n.toLocaleString(LOCALE);
const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" }) : "");

type ResolveTarget = { issue: Issue; action: "resolve" | "unresolve" };

export default function Control() {
  const { pid } = useProject();
  const canEdit = useAuth().can("control", "edit");
  const toast = useToast();
  const qc = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>("open");
  const [kind, setKind] = useState<string>("");
  const [severity, setSeverity] = useState<string>("");
  const [target, setTarget] = useState<ResolveTarget | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showStale, setShowStale] = useState(false);

  const q = useQuery({
    queryKey: ["control", pid],
    queryFn: () => api.get<ControlResp>(`/projects/${pid}/control`),
    enabled: !!pid,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["control", pid] });

  const { mutate: delIssue } = useMutation({
    mutationFn: (id: number) => api.del(`/projects/${pid}/control/issues/${id}`),
    onSuccess: () => { toast(tx("Konu silindi")); invalidate(); },
    onError: (e) => toast(errText(e), true),
  });

  const items = q.data?.items ?? [];

  // Per-kind summary (open / total, worst severity) over all items, independent of filters.
  const groups = useMemo(() => {
    const m = new Map<string, { kind: string; total: number; open: number; sev: string }>();
    for (const i of items) {
      let g = m.get(i.kind);
      if (!g) { g = { kind: i.kind, total: 0, open: 0, sev: i.severity }; m.set(i.kind, g); }
      g.total++;
      if (i.status === OPEN) g.open++;
      if ((SEV_ORDER[i.severity] ?? 9) < (SEV_ORDER[g.sev] ?? 9)) g.sev = i.severity;
    }
    return [...m.values()].sort((a, b) => (SEV_ORDER[a.sev] ?? 9) - (SEV_ORDER[b.sev] ?? 9) || b.open - a.open || a.kind.localeCompare(b.kind, "tr"));
  }, [items]);

  const counts = useMemo(() => {
    const c = { total: items.length, open: 0, resolved: 0, error: 0, warning: 0, info: 0 };
    for (const i of items) {
      if (i.status === OPEN) {
        c.open++;
        if (i.severity === "error") c.error++;
        else if (i.severity === "warning") c.warning++;
        else c.info++;
      } else c.resolved++;
    }
    return c;
  }, [items]);

  const rows = useMemo(() => {
    const r = items.filter((i) =>
      (status === "all" || (status === "open" ? i.status === OPEN : i.status === RESOLVED)) &&
      (!kind || i.kind === kind) && (!severity || i.severity === severity));
    return r.sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) ||
      a.kind.localeCompare(b.kind, "tr") || a.part_no.localeCompare(b.part_no, "tr"));
  }, [items, status, kind, severity]);

  const columns = useMemo<GridColumn<Issue>[]>(() => [
    {
      id: "severity", header: tx("Önem"), size: 80,
      accessorFn: (r) => SEV_LABEL[r.severity] ?? r.severity,
      cellStyle: (r) => statusStyle(r.status === RESOLVED ? RESOLVED_COLOR : SEV_COLOR[r.severity]),
    },
    { id: "kind", header: tx("Tür"), size: 230, accessorKey: "kind" },
    {
      id: "part_no", header: tx("Parça No"), size: 200, accessorKey: "part_no",
      cell: ({ row }) => {
        const pno = row.original.part_no;
        if (!pno) return <span className="muted">-</span>;
        const first = pno.split(" / ")[0];
        return <Link to={`/p/${pid}/parts?q=${encodeURIComponent(first)}`} title={tx("Parça listesinde göster")} onClick={(e) => e.stopPropagation()}>{pno}</Link>;
      },
    },
    {
      id: "message", header: tx("Açıklama"), size: 380, accessorKey: "message",
      cell: ({ row }) => <span title={tx(row.original.message)}>{tx(row.original.message)}</span>,
    },
    { id: "levels", header: tx("Seviye"), size: 90, accessorFn: (r) => (r.levels ?? []).join(", ") },
    {
      id: "status", header: tx("Durum"), size: 90, accessorKey: "status",
      cellStyle: (r) => (r.status === RESOLVED ? statusStyle(RESOLVED_COLOR) : undefined),
    },
    {
      id: "note", header: tx("Not"), size: 220, accessorKey: "note",
      cell: ({ row }) => <span title={row.original.note}>{row.original.note}</span>,
    },
    { id: "resolved_by", header: tx("Çözen"), size: 110, accessorKey: "resolved_by" },
    { id: "resolved_at", header: tx("Çözüm Tarihi"), size: 130, accessorFn: (r) => fmtDate(r.resolved_at) },
    { id: "source", header: tx("Kaynak"), size: 100, accessorFn: (r) => (r.manual ? tx("Manuel ({0})", r.created_by || "-") : tx("Otomatik")) },
    {
      id: "_act", header: "", size: canEdit ? 150 : 1, noFilter: true, enableSorting: false,
      cell: ({ row }) => {
        if (!canEdit) return null;
        const i = row.original;
        return (
          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
            {i.status === OPEN
              ? <button className="btn small primary" onClick={(e) => { e.stopPropagation(); setTarget({ issue: i, action: "resolve" }); }}>{tx("Çözüldü")}</button>
              : <button className="btn small" onClick={(e) => { e.stopPropagation(); setTarget({ issue: i, action: "unresolve" }); }}>{tx("Yeniden aç")}</button>}
            {i.manual && i.id != null && (
              <button className="btn small danger" title={tx("Konuyu sil")} onClick={(e) => {
                e.stopPropagation();
                if (confirm(tx("\"{0}\" konusu silinsin mi?", i.message))) delIssue(i.id!);
              }}>{tx("Sil")}</button>
            )}
          </div>
        );
      },
    },
  ], [pid, canEdit, delIssue]);

  const toolbar = (
    <div className="row">
      <div className="tabs ctl-tabs">
        <button className={status === "open" ? "active" : ""} onClick={() => setStatus("open")}>{tx("Açık ({0})", fmt(counts.open))}</button>
        <button className={status === "resolved" ? "active" : ""} onClick={() => setStatus("resolved")}>{tx("Çözüldü ({0})", fmt(counts.resolved))}</button>
        <button className={status === "all" ? "active" : ""} onClick={() => setStatus("all")}>{tx("Hepsi ({0})", fmt(counts.total))}</button>
      </div>
      <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={tx("Tür")}>
        <option value="">{tx("Tüm türler")}</option>
        {groups.map((g) => <option key={g.kind} value={g.kind}>{tx(g.kind)} ({fmt(g.total)})</option>)}
      </select>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label={tx("Önem")}>
        <option value="">{tx("Tüm önem dereceleri")}</option>
        <option value="error">{tx("Hata")}</option>
        <option value="warning">{tx("Uyarı")}</option>
        <option value="info">{tx("Bilgi")}</option>
      </select>
      {canEdit && <button className="btn small primary" onClick={() => setShowNew(true)}>{tx("+ Yeni konu")}</button>}
      <button className="btn small" onClick={() => q.refetch()} disabled={q.isFetching}>{q.isFetching ? tx("Yenileniyor…") : tx("Yenile")}</button>
    </div>
  );

  if (q.isLoading) return <Page><div className="muted">{tx("Kontroller hesaplanıyor…")}</div></Page>;
  if (q.isError) return <Page><div className="error">{errText(q.error)}</div><button className="btn" onClick={() => q.refetch()}>{tx("Tekrar dene")}</button></Page>;

  const stale = q.data?.stale ?? [];

  return (
    <Page full>
      <div className="ctl-head">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{tx("Kontrol Listesi")}</h2>
          <div className="row">
            <span className="badge err">{tx("{0} hata", fmt(counts.error))}</span>
            <span className="badge warn">{tx("{0} uyarı", fmt(counts.warning))}</span>
            <span className="badge">{tx("{0} bilgi", fmt(counts.info))}</span>
            <span className="muted">{tx("açık · {0} çözüldü", fmt(counts.resolved))}</span>
          </div>
        </div>
        {groups.length === 0 ? (
          <div className="ok" style={{ marginTop: 8 }}>{tx("Sorun bulunamadı. Tüm kontroller temiz.")}</div>
        ) : (
          <div className="ctl-groups">
            {groups.map((g) => (
              <button key={g.kind} className={"ctl-group" + (kind === g.kind ? " active" : "")}
                style={statusStyle(g.open ? SEV_COLOR[g.sev] : RESOLVED_COLOR)}
                title={tx("{0} · {1} açık / {2} toplam", SEV_LABEL[g.sev] ?? g.sev, fmt(g.open), fmt(g.total))}
                onClick={() => setKind(kind === g.kind ? "" : g.kind)}>
                <span className="ctl-kind">{tx(g.kind)}</span>
                <b>{fmt(g.open)}</b><span className="muted"> / {fmt(g.total)}</span>
              </button>
            ))}
          </div>
        )}
        {stale.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <button className="btn small" onClick={() => setShowStale((v) => !v)}>
              {showStale ? "▾" : "▸"}{" "}{tx("Artık tespit edilmeyen kayıtlar ({0})", fmt(stale.length))}
            </button>
            {showStale && (
              <div className="ctl-stale">
                <table className="simple">
                  <thead><tr><th>{tx("Tür")}</th><th>{tx("Parça No")}</th><th>{tx("Açıklama")}</th><th>{tx("Durum")}</th><th>{tx("Not")}</th><th>{tx("Çözen")}</th></tr></thead>
                  <tbody>
                    {stale.slice(0, 300).map((s) => (
                      <tr key={s.key}><td>{tx(s.kind)}</td><td>{s.part_no}</td><td>{tx(s.message)}</td><td>{tx(s.status)}</td><td>{s.note}</td><td>{s.resolved_by}</td></tr>
                    ))}
                  </tbody>
                </table>
                {stale.length > 300 && <div className="muted">{tx("İlk 300 kayıt gösteriliyor.")}</div>}
              </div>
            )}
          </div>
        )}
      </div>
      <DataGrid<Issue>
        stateKey="Kontrol listesi" exportName={tx("Kontrol listesi")}
        data={rows}
        columns={columns}
        getRowId={(r) => r.key}
        toolbar={toolbar}
        rowStyle={(r) => (r.status === RESOLVED ? { opacity: 0.75 } : undefined)}
        emptyText={status === "open" ? tx("Açık konu yok.") : tx("Kayıt yok.")}
      />
      {target && <ResolveModal pid={pid} target={target} onClose={() => setTarget(null)} />}
      {showNew && <NewIssueModal pid={pid} onClose={() => setShowNew(false)} />}
    </Page>
  );
}

function ResolveModal({ pid, target, onClose }: { pid: number; target: ResolveTarget; onClose: () => void }) {
  const { issue, action } = target;
  const [note, setNote] = useState(issue.note ?? "");
  const toast = useToast();
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.post<Issue>(`/projects/${pid}/control/${action}`, { key: issue.key, note: note.trim() }),
    onSuccess: () => {
      toast(action === "resolve" ? tx("Çözüldü olarak işaretlendi") : tx("Konu yeniden açıldı"));
      qc.invalidateQueries({ queryKey: ["control", pid] });
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{action === "resolve" ? tx("Çözüldü olarak işaretle") : tx("Konuyu yeniden aç")}</h3>
        <div className="muted" style={{ marginBottom: 4 }}>{issue.kind}{issue.part_no ? ` · ${issue.part_no}` : ""}</div>
        <div style={{ marginBottom: 10 }}>{tx(issue.message)}</div>
        <label className="muted" htmlFor="ctl-note">{tx("Not")}{" "}{action === "unresolve" ? tx("(boş bırakılırsa mevcut not korunur)") : tx("(isteğe bağlı)")}</label>
        <textarea id="ctl-note" rows={4} style={{ width: "100%" }} value={note} autoFocus
          onChange={(e) => setNote(e.target.value)} placeholder={tx("Ör. Tasarımcı ile kontrol edildi, BOM doğru.")} />
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
          <button className="btn primary" disabled={m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? tx("Kaydediliyor…") : action === "resolve" ? tx("Çözüldü") : tx("Yeniden aç")}
          </button>
        </div>
      </div>
    </div>
  );
}

function NewIssueModal({ pid, onClose }: { pid: number; onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [partNo, setPartNo] = useState("");
  const [sev, setSev] = useState<Severity>("warning");
  const toast = useToast();
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.post<Issue>(`/projects/${pid}/control/issues`, { message: message.trim(), part_no: partNo.trim(), severity: sev }),
    onSuccess: () => {
      toast(tx("Konu eklendi"));
      qc.invalidateQueries({ queryKey: ["control", pid] });
      onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{tx("Yeni konu")}</h3>
        <div className="grid" style={{ gap: 8 }}>
          <label>{tx("Parça No (isteğe bağlı)")}<br /><input style={{ width: "100%" }} value={partNo} onChange={(e) => setPartNo(e.target.value)} /></label>
          <label>{tx("Önem")}<br />
            <select value={sev} onChange={(e) => setSev(e.target.value as Severity)}>
              <option value="error">{tx("Hata")}</option>
              <option value="warning">{tx("Uyarı")}</option>
              <option value="info">{tx("Bilgi")}</option>
            </select>
          </label>
          <label>{tx("Açıklama")}<br /><textarea rows={4} style={{ width: "100%" }} value={message} autoFocus onChange={(e) => setMessage(e.target.value)} /></label>
        </div>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
          <button className="btn primary" disabled={!message.trim() || m.isPending} onClick={() => m.mutate()}>
            {m.isPending ? tx("Kaydediliyor…") : tx("Ekle")}
          </button>
        </div>
      </div>
    </div>
  );
}
