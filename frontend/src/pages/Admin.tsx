import { useState, type ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Page } from "../components/Layout";
import { useUpdate } from "../components/UpdateCheck";
import UsersTab from "./admin/Users";
import FirmsTab from "./admin/Firms";
import SettingsTab from "./admin/Settings";
import FastenerRulesTab from "./admin/FastenerRules";
import T35ConfigTab from "./admin/T35Config";
import AuditLogTab from "./admin/AuditLog";
import BackupsTab from "./admin/Backups";

const TABS: { id: string; label: string; C: ComponentType }[] = [
  { id: "users", label: "Kullanıcılar", C: UsersTab },
  { id: "firms", label: "Firmalar", C: FirmsTab },
  { id: "settings", label: "Ayarlar", C: SettingsTab },
  { id: "fasteners", label: "Bağlantı Elemanı Kuralları", C: FastenerRulesTab },
  { id: "t35", label: "T-35 Ayarları", C: T35ConfigTab },
  { id: "audit", label: "Denetim Kaydı", C: AuditLogTab },
  { id: "backups", label: "Yedekler", C: BackupsTab },
];
const TAB_KEY = "admin.tab";

function readTab(): string {
  try {
    const t = localStorage.getItem(TAB_KEY);
    if (t && TABS.some((x) => x.id === t)) return t;
  } catch {
    /* storage blocked: fall back to the first tab */
  }
  return TABS[0].id;
}

export default function Admin() {
  const [tab, setTab] = useState(readTab);
  const pick = (id: string) => {
    setTab(id);
    try {
      localStorage.setItem(TAB_KEY, id);
    } catch {
      /* ignore */
    }
  };
  const Current = (TABS.find((t) => t.id === tab) ?? TABS[0]).C;
  return (
    <Page>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Yönetim</h2>
        <VersionBox />
      </div>
      <div className="tabs adm-tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "active" : ""} onClick={() => pick(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="adm-body">
        <Current />
      </div>
    </Page>
  );
}

function VersionBox() {
  const { info, checking, available, check, message } = useUpdate();
  const ver = useQuery({
    queryKey: ["version"],
    queryFn: () => api.get<{ version: string; update_feed_url?: string | null }>("/version"),
    staleTime: 60_000,
  });
  const server = info.server ?? ver.data?.version;
  return (
    <div className="adm-version">
      <div className="muted">
        Arayüz sürümü <b>{info.current}</b>
        {server && <> · Sunucu sürümü <b>{server}</b></>}
        {ver.error && !info.server && <span className="error"> · Sunucu sürümü alınamadı</span>}
      </div>
      <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
        <button className="btn small" disabled={checking} onClick={() => void check(true)}>
          {checking ? "Denetleniyor…" : "Güncellemeleri denetle"}
        </button>
      </div>
      {available && (
        <div className="warn">
          Yeni sürüm var{info.feed?.version ? `: ${info.feed.version}` : info.server ? `: ${info.server}` : ""}.
          {info.server && info.server !== info.current && " Sayfayı yenileyerek güncel arayüzü yükleyin."}
          {info.feed?.url && <> <a href={info.feed.url} target="_blank" rel="noreferrer">Ayrıntılar</a></>}
        </div>
      )}
      {info.feed?.notes && available && <div className="muted adm-small" style={{ whiteSpace: "pre-wrap" }}>{info.feed.notes}</div>}
      {message && !available && <div className={message.startsWith("Güncel") ? "ok" : "error"}>{message}</div>}
    </div>
  );
}
