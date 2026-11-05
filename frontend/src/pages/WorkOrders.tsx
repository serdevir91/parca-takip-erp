import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { saveRev } from "../api/conflict";
import { curSign } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import { MakerInput, ProjectSelect, WO_COLORS, fmtDay, fmtMoney, fmtQty, numOrNull, trIncludes, type WoWarning, type WorkOrder } from "./erp/common";
import WoDetail from "./erp/WoDetail";
import { LOCALE, tx } from "../api/i18n";

type ListResp = { rows: WorkOrder[]; statuses: Record<string, string> };

/** İş emirleri: all projects at /work-orders, one project at /p/:pid/work-orders. */
export default function WorkOrders() {
  const { pid, project } = useProject();
  const canEdit = useAuth().can("workorders", "edit");
  const toast = useToast();
  const refresh = useRefresh();
  const [status, setStatus] = useState("open");
  const [projectFilter, setProjectFilter] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<WorkOrder | "new" | null>(null);
  const [completing, setCompleting] = useState<WorkOrder | null>(null);
  const [detail, setDetail] = useState<WorkOrder | null>(null);

  const projectId = pid || projectFilter;
  const list = useQuery({
    queryKey: ["work-orders", projectId ?? 0, status],
    queryFn: () => {
      const p = new URLSearchParams();
      if (projectId) p.set("project_id", String(projectId));
      if (status) p.set("status", status);
      return api.get<ListResp>(`/work-orders?${p}`);
    },
  });
  const rows = useMemo(
    () => (list.data?.rows ?? []).filter((r) => !q.trim() || trIncludes(`${r.no} ${r.part_no} ${r.description} ${r.firm_name} ${r.project_name ?? ""}`, q)),
    [list.data, q],
  );

  const setSt = useMutation({
    mutationFn: ({ w, s }: { w: WorkOrder; s: string }) => api.post<WorkOrder>(`/work-orders/${w.id}/status`, { status: s }),
    onSuccess: (w) => { toast(`${w.no}: ${w.status_label}`); refresh(); },
    onError: (e) => toast(errText(e), true),
  });
  const del = useMutation({
    mutationFn: (w: WorkOrder) => api.del(`/work-orders/${w.id}`),
    onSuccess: () => { toast(tx("İş emri silindi")); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  return (
    <Page>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, marginRight: 8 }}>{tx("İş Emirleri")}{project ? ` · ${project.name}` : ""}</h2>
          {canEdit && <button className="btn primary" onClick={() => setEditing("new")}>{tx("+ Yeni iş emri")}</button>}
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={tx("Durum")}>
            <option value="open">{tx("Açık iş emirleri")}</option>
            <option value="">{tx("Tümü")}</option>
            {Object.entries(list.data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{tx(v)}</option>)}
          </select>
          {!pid && <ProjectSelect value={projectFilter} onChange={setProjectFilter} emptyLabel={tx("Tüm projeler")} />}
          <input placeholder={tx("Ara (no, parça, firma)…")} value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{tx("{0} iş emri", rows.length.toLocaleString(LOCALE))}</span>
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr>
                  <th>{tx("İş emri no")}</th>{!pid && <th>{tx("Proje")}</th>}<th>{tx("Parça no")}</th><th>{tx("Açıklama")}</th><th className="num">{tx("Miktar")}</th>
                  <th className="num">{tx("Üretilen")}</th><th>{tx("Yapan")}</th><th>{tx("Durum")}</th><th className="num">{tx("Rota")}</th><th>{tx("Başlangıç")}</th><th>{tx("Termin")}</th><th className="num">{tx("Maliyet")}</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((w) => {
                  const open = w.status === "planned" || w.status === "in_progress";
                  return (
                    <tr key={w.id} className="clickable" onClick={() => setDetail(w)}>
                      <td><b>{w.no}</b></td>
                      {!pid && <td>{w.project_name ?? <span className="muted">{tx("Stok")}</span>}</td>}
                      <td className="mono">{w.part_no}</td>
                      <td>{w.description}</td>
                      <td className="num">{fmtQty(w.qty)}</td>
                      <td className="num">{fmtQty(w.done_qty)}</td>
                      <td>{w.firm_name ? <>{w.firm_name} <span className="badge">{tx("Fason")}</span></> : tx("İç üretim")}</td>
                      <td><span className="badge" style={statusStyle(WO_COLORS[w.status])}>{w.status_label}</span></td>
                      <td className="num">{w.ops_total ? `${w.ops_done}/${w.ops_total}` : ""}</td>
                      <td>{fmtDay(w.start_date)}</td>
                      <td className={w.overdue ? "error" : undefined}>{fmtDay(w.due_date)}{w.overdue ? tx(" (gecikti)") : ""}</td>
                      <td className="num">{fmtMoney(w.total_cost)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {canEdit && (
                          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                            {w.status === "planned" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ w, s: "in_progress" })}>{tx("Başlat")}</button>}
                            {open && <button className="btn small primary" onClick={() => setCompleting(w)}>{tx("Üretim girişi")}</button>}
                            {open && <button className="btn small" onClick={() => setEditing(w)}>{tx("Düzenle")}</button>}
                            {w.status === "planned" && <button className="btn small danger" disabled={del.isPending} onClick={() => confirm(tx("{0} silinsin mi?", w.no)) && del.mutate(w)}>{tx("Sil")}</button>}
                            {w.status === "in_progress" && w.done_qty === 0 && <button className="btn small danger" disabled={setSt.isPending} onClick={() => confirm(tx("{0} iptal edilsin mi?", w.no)) && setSt.mutate({ w, s: "cancelled" })}>{tx("İptal")}</button>}
                            {w.status === "in_progress" && <button className="btn small" disabled={setSt.isPending} title={tx("Üretileni ve maliyetini korur, kalan miktarı kapatır")}
                              onClick={() => confirm(tx("{0} {1} / {2} üretimle kapatılsın mı? Sonra değiştirilemez.", w.no, fmtQty(w.done_qty), fmtQty(w.qty))) && setSt.mutate({ w, s: "closed" })}>{tx("Kısa kapat")}</button>}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!rows.length && <tr><td colSpan={13} className="muted">{tx("İş emri yok.")}</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          {tx("İş emri başlatıldığında parça \"Devam ediyor\" olur; üretim girişi tamamlanınca parça \"Üretildi\" olarak işaretlenir.")}
        </p>
      </div>
      {editing && <WoForm wo={editing === "new" ? undefined : editing} projectId={pid || null} onClose={() => setEditing(null)} />}
      {completing && <CompleteModal wo={completing} onClose={() => setCompleting(null)} />}
      {detail && <WoDetail wo={rows.find((r) => r.id === detail.id) ?? detail} onClose={() => setDetail(null)} />}
    </Page>
  );
}

function useRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const k of ["work-orders", "requirements", "costs", "stock", "parts"]) void qc.invalidateQueries({ queryKey: [k] });
  };
}

function WoForm({ wo, projectId, onClose }: { wo?: WorkOrder; projectId: number | null; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [project, setProject] = useState<number | null>(wo ? wo.project_id : projectId);
  const [partNo, setPartNo] = useState(wo?.part_no ?? "");
  const [desc, setDesc] = useState(wo?.description ?? "");
  const [qty, setQty] = useState(String(wo?.qty ?? 1));
  const [maker, setMaker] = useState(wo?.firm_name ?? "");
  const [start, setStart] = useState(wo?.start_date ?? "");
  const [due, setDue] = useState(wo?.due_date ?? "");
  const [cost, setCost] = useState(wo?.unit_cost == null ? "" : String(wo.unit_cost));
  const [note, setNote] = useState(wo?.note ?? "");
  const save = useMutation({
    mutationFn: () => {
      const body = { description: desc, qty: numOrNull(qty) ?? 0, firm_name: maker.trim(), start_date: start || null,
        due_date: due || null, unit_cost: numOrNull(cost), note };
      return wo ? saveRev(wo.rev, (rev) => api.put<WorkOrder>(`/work-orders/${wo.id}`, { ...body, rev }))
        : api.post<WorkOrder>("/work-orders", { ...body, project_id: project, part_no: partNo.trim() });
    },
    onSuccess: (w) => { toast(wo ? tx("İş emri güncellendi") : tx("{0} oluşturuldu", w.no)); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={wo ? tx("İş emrini düzenle: {0}", wo.no) : tx("Yeni iş emri")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending || (!wo && !partNo.trim())} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <div className="adm-form">
        {!wo && <Field label={tx("Proje")}><ProjectSelect value={project} onChange={setProject} emptyLabel={tx("(Stok için, projesiz)")} /></Field>}
        <Field label={tx("Parça no")}>{wo ? <input disabled value={wo.part_no} /> : <input autoFocus value={partNo} onChange={(e) => setPartNo(e.target.value)} />}</Field>
        <Field label={tx("Açıklama")}><input value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <Field label={tx("Miktar")}><input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label={tx("Yapan")}><MakerInput value={maker} onChange={setMaker} /></Field>
        <div className="adm-form two">
          <Field label={tx("Başlangıç")}><input type="date" value={start ?? ""} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label={tx("Termin")}><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        </div>
        <Field label={tx("Birim maliyet ({0})", curSign())} hint={tx("Fason fiyatı veya iç üretim maliyeti; proje maliyetine eklenir.")}>
          <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
        </Field>
        <Field label={tx("Not")}><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function CompleteModal({ wo, onClose }: { wo: WorkOrder; onClose: () => void }) {
  const toast = useToast();
  const refresh = useRefresh();
  const [qty, setQty] = useState(String(wo.remaining));
  const [note, setNote] = useState("");
  const [warnings, setWarnings] = useState<WoWarning[] | null>(null);
  const save = useMutation({
    mutationFn: () => api.post<WorkOrder & { warnings: WoWarning[] }>(`/work-orders/${wo.id}/complete`, { qty: numOrNull(qty) ?? 0, note }),
    onSuccess: (w) => {
      toast(tx("{0}: {1} / {2} üretildi", w.no, fmtQty(w.done_qty), fmtQty(w.qty)));
      refresh();
      if (w.warnings.length) setWarnings(w.warnings);
      else onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  if (warnings) {
    return (
      <Modal title={tx("Eksik malzeme: {0}", wo.no)} onClose={onClose} footer={<button className="btn primary" onClick={onClose}>{tx("Tamam")}</button>}>
        <p>{tx("Üretim girişi kaydedildi, ancak şu malzemeler stoktan tam çıkılamadı:")}</p>
        <ul className="scan-warn">{warnings.map((w) => <li key={w.code}>{w.message}</li>)}</ul>
        <p className="muted">{tx("Stoktaki kadarı çıkıldı. İş emri açıksa eksik kalan sonraki üretim girişinde yeniden denenir.")}</p>
      </Modal>
    );
  }
  return (
    <Modal title={tx("Üretim girişi: {0}", wo.no)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Vazgeç")}</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{tx("Kaydet")}</button>
      </>}>
      <p><b className="mono">{wo.part_no}</b>{" "}{tx("{0} · kalan {1}", wo.description, fmtQty(wo.remaining))}</p>
      <div className="adm-form">
        <Field label={tx("Üretilen miktar")}><input autoFocus inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label={tx("Not")}><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <p className="muted">{wo.project_id ? tx("Üretilen parçalar stoğa girer ve projeye çıkılır.") : tx("Üretilen parçalar stoğa girer.")}</p>
    </Modal>
  );
}
