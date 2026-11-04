import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { errText, useToast } from "./Toast";

type Item = { key: string; kind: string; title: string; detail: string; link: string; date: string | null; urgent: boolean };
const QK = ["notifications"];

export default function Notifications() {
  const qc = useQueryClient();
  const toast = useToast();
  const go = useNavigate();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: QK,
    queryFn: () => api.get<{ count: number; items: Item[] }>("/notifications"),
    refetchInterval: 60_000,
  });
  const read = useMutation({
    mutationFn: (keys: string[]) => api.post("/notifications/read", { keys }),
    onError: (e) => toast(errText(e), true),
    onSettled: () => void qc.invalidateQueries({ queryKey: QK }),
  });
  const items = q.data?.items ?? [];
  const count = q.data?.count ?? 0;

  return (
    <>
      <button className="icon-btn bell" title="Bildirimler" aria-label={`Bildirimler: ${count}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Bell size={17} />
        {count > 0 && <span className="bell-count">{count > 99 ? "99+" : count}</span>}
      </button>
      {open && (
        <>
          <div className="notif-back" onClick={() => setOpen(false)} />
          <div className="notif-pop" role="dialog" aria-label="Bildirimler">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <b>Bildirimler</b>
              {items.length > 0 && (
                <button className="btn small" disabled={read.isPending} onClick={() => read.mutate(items.map((i) => i.key))}>Tümünü kapat</button>
              )}
            </div>
            {!items.length && <p className="muted">Bekleyen bildirim yok.</p>}
            <ul>
              {items.map((i) => (
                <li key={i.key} className={i.urgent ? "urgent" : undefined}>
                  <button className="notif-go" onClick={() => { setOpen(false); go(i.link); }}>
                    <span className="muted">{i.kind}</span>
                    <b>{i.title}</b>
                    {i.detail && <span>{i.detail}</span>}
                  </button>
                  <button className="icon-btn" title="Kapat" aria-label="Bildirimi kapat" onClick={() => read.mutate([i.key])}><X size={15} /></button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
