import { ActionButton } from "@/components/action-button";
import { StatusBadge } from "@/components/status-badge";
import { apiGet } from "@/lib/api";
import { text } from "@/lib/format";

type Settings = {
  app_env: string;
  auto_prepare_publication: boolean;
  publication_max_attempts: number;
  publication_retry_base_seconds: number;
  telegram_control_configured: boolean;
  avito_live_enabled: boolean;
  backup_configured: boolean;
  cookie_secure: boolean;
  session_ttl_seconds: number;
};

type Health = {
  api: string;
  database: string;
  redis: string;
  worker: string;
  scheduler: string;
  avito_real_mutation: string;
};

export default async function SettingsPage() {
  const settings = await apiGet<Settings>("/api/v1/operator/settings");
  const health = await apiGet<Health>("/api/v1/operator/system/health");
  return (
    <div className="stack">
      <div className="topbar"><h1>Settings</h1><StatusBadge value={settings.app_env} /></div>
      <div className="two">
        <section className="section">
          <h2>Runtime</h2>
          <p>Auto prepare: {text(settings.auto_prepare_publication)}</p>
          <p>Publication max attempts: {settings.publication_max_attempts}</p>
          <p>Retry base seconds: {settings.publication_retry_base_seconds}</p>
          <p>Telegram operators: {settings.telegram_control_configured ? "configured" : "not configured"}</p>
          <p>Cookie secure: {text(settings.cookie_secure)}</p>
          <p>Session TTL: {settings.session_ttl_seconds}s</p>
        </section>
        <section className="section">
          <h2>System Health</h2>
          <p>API: <StatusBadge value={health.api} /></p>
          <p>DB: <StatusBadge value={health.database} /></p>
          <p>Redis: <StatusBadge value={health.redis} /></p>
          <p>Worker: <StatusBadge value={health.worker} /></p>
          <p>Scheduler: <StatusBadge value={health.scheduler} /></p>
          <p>{health.avito_real_mutation}</p>
          <ActionButton path="/api/v1/operator/backups/smoke" label="Run backup smoke" confirmText="Run a dev backup smoke now?" />
        </section>
      </div>
    </div>
  );
}
