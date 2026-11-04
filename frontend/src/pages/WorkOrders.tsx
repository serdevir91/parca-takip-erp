import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { curSign } from "../api/system";
import { useAuth } from "../api/auth";
import { Page, useProject } from "../components/Layout";
import { errText, useToast } from "../components/Toast";
import { statusStyle } from "../theme/theme";
import { Field, Loading, Modal } from "./admin/shared";
import { MakerInput, ProjectSelect, WO_COLORS, fmtDay, fmtMoney, fmtQty, numOrNull, trIncludes, type WoWarning, type WorkOrder } from "./erp/common";
import WoDetail from "./erp/WoDetail";

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
    onSuccess: () => { toast("İş emri silindi"); refresh(); },
    onError: (e) => toast(errText(e), true),
  });

  return (
    <Page>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, marginRight: 8 }}>İş Emirleri{project ? ` · ${project.name}` : ""}</h2>
          {canEdit && <button className="btn primary" onClick={() => setEditing("new")}>+ Yeni iş emri</button>}
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Durum">
            <option value="open">Açık iş emirleri</option>
            <option value="">Tümü</option>
            {Object.entries(list.data?.statuses ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {!pid && <ProjectSelect value={projectFilter} onChange={setProjectFilter} emptyLabel="Tüm projeler" />}
          <input placeholder="Ara (no, parça, firma)…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="muted">{rows.length.toLocaleString("tr-TR")} iş emri</span>
        </div>
        <Loading error={list.error} loading={list.isLoading} />
        {list.data && (
          <div className="adm-scroll">
            <table className="simple erp-table">
              <thead>
                <tr>
                  <th>İş emri no</th>{!pid && <th>Proje</th>}<th>Parça no</th><th>Açıklama</th><th className="num">Miktar</th>
                  <th className="num">Üretilen</th><th>Yapan</th><th>Durum</th><th className="num">Rota</th><th>Başlangıç</th><th>Termin</th><th className="num">Maliyet</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((w) => {
                  const open = w.status === "planned" || w.status === "in_progress";
                  return (
                    <tr key={w.id} className="clickable" onClick={() => setDetail(w)}>
                      <td><b>{w.no}</b></td>
                      {!pid && <td>{w.project_name ?? <span className="muted">Stok</span>}</td>}
                      <td className="mono">{w.part_no}</td>
                      <td>{w.description}</td>
                      <td className="num">{fmtQty(w.qty)}</td>
                      <td className="num">{fmtQty(w.done_qty)}</td>
                      <td>{w.firm_name ? <>{w.firm_name} <span className="badge">Fason</span></> : "İç üretim"}</td>
                      <td><span className="badge" style={statusStyle(WO_COLORS[w.status])}>{w.status_label}</span></td>
                      <td className="num">{w.ops_total ? `${w.ops_done}/${w.ops_total}` : ""}</td>
                      <td>{fmtDay(w.start_date)}</td>
                      <td className={w.overdue ? "error" : undefined}>{fmtDay(w.due_date)}{w.overdue ? " (gecikti)" : ""}</td>
                      <td className="num">{fmtMoney(w.total_cost)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {canEdit && (
                          <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                            {w.status === "planned" && <button className="btn small" disabled={setSt.isPending} onClick={() => setSt.mutate({ w, s: "in_progress" })}>Başlat</button>}
                            {open && <button className="btn small primary" onClick={() => setCompleting(w)}>Üretim girişi</button>}
                            {open && <button className="btn small" onClick={() => setEditing(w)}>Düzenle</button>}
                            {w.status === "planned" && <button className="btn small danger" disabled={del.isPending} onClick={() => confirm(`${w.no} silinsin mi?`) && del.mutate(w)}>Sil</button>}
                            {w.status === "in_progress" && w.done_qty === 0 && <button className="btn small danger" disabled={setSt.isPending} onClick={() => confirm(`${w.no} iptal edilsin mi?`) && setSt.mutate({ w, s: "cancelled" })}>İptal</button>}
                            {w.status === "in_progress" && <button className="btn small" disabled={setSt.isPending} title="Üretileni ve maliyetini korur, kalan miktarı kapatır"
                              onClick={() => confirm(`${w.no} ${fmtQty(w.done_qty)} / ${fmtQty(w.qty)} üretimle kapatılsın mı? Sonra değiştirilemez.`) && setSt.mutate({ w, s: "closed" })}>Kısa kapat</button>}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!rows.length && <tr><td colSpan={13} className="muted">İş emri yok.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          İş emri başlatıldığında parça "Devam ediyor" olur; üretim girişi tamamlanınca parça "Üretildi" olarak işaretlenir.
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
      return wo ? api.put<WorkOrder>(`/work-orders/${wo.id}`, body)
        : api.post<WorkOrder>("/work-orders", { ...body, project_id: project, part_no: partNo.trim() });
    },
    onSuccess: (w) => { toast(wo ? "İş emri güncellendi" : `${w.no} oluşturuldu`); refresh(); onClose(); },
    onError: (e) => toast(errText(e), true),
  });
  return (
    <Modal title={wo ? `İş emrini düzenle: ${wo.no}` : "Yeni iş emri"} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending || (!wo && !partNo.trim())} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <div className="adm-form">
        {!wo && <Field label="Proje"><ProjectSelect value={project} onChange={setProject} emptyLabel="(Stok için, projesiz)" /></Field>}
        <Field label="Parça no">{wo ? <input disabled value={wo.part_no} /> : <input autoFocus value={partNo} onChange={(e) => setPartNo(e.target.value)} />}</Field>
        <Field label="Açıklama"><input value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <Field label="Miktar"><input inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Yapan"><MakerInput value={maker} onChange={setMaker} /></Field>
        <div className="adm-form two">
          <Field label="Başlangıç"><input type="date" value={start ?? ""} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Termin"><input type="date" value={due ?? ""} onChange={(e) => setDue(e.target.value)} /></Field>
        </div>
        <Field label={`Birim maliyet (${curSign()})`} hint="Fason fiyatı veya iç üretim maliyeti; proje maliyetine eklenir.">
          <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
        </Field>
        <Field label="Not"><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
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
      toast(`${w.no}: ${fmtQty(w.done_qty)} / ${fmtQty(w.qty)} üretildi`);
      refresh();
      if (w.warnings.length) setWarnings(w.warnings);
      else onClose();
    },
    onError: (e) => toast(errText(e), true),
  });
  if (warnings) {
    return (
      <Modal title={`Eksik malzeme: ${wo.no}`} onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Tamam</button>}>
        <p>Üretim girişi kaydedildi, ancak şu malzemeler stoktan tam çıkılamadı:</p>
        <ul className="scan-warn">{warnings.map((w) => <li key={w.code}>{w.message}</li>)}</ul>
        <p className="muted">Stoktaki kadarı çıkıldı. Eksik kalan, proje maliyetine yansımaz; iş emri açıksa sonraki üretim girişinde yeniden denenir.</p>
      </Modal>
    );
  }
  return (
    <Modal title={`Üretim girişi: ${wo.no}`} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Vazgeç</button>
        <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Kaydet</button>
      </>}>
      <p><b className="mono">{wo.part_no}</b> {wo.description} · kalan {fmtQty(wo.remaining)}</p>
      <div className="adm-form">
        <Field label="Üretilen miktar"><input autoFocus inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Not"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <p className="muted">{wo.project_id ? "Üretilen parçalar stoğa girer ve projeye çıkılır." : "Üretilen parçalar stoğa girer."}</p>
    </Modal>
  );
}
