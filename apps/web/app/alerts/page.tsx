import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function AlertsPage() {
  const page = await apiGet<Page>("/api/v1/operator/alerts");
  const rows = page.items.map((item) => ({
    ...item,
    action: item.id
  }));
  return (
    <div className="stack">
      <div className="topbar"><h1>Alerts</h1><span className="muted">{page.total} alerts</span></div>
      <DataTable empty="No open alerts" rows={rows} columns={[
        { key: "severity", label: "Severity", kind: "status" },
        { key: "type", label: "Type" },
        { key: "entity_type", label: "Entity" },
        { key: "message", label: "Message" },
        { key: "status", label: "Status", kind: "status" },
        { key: "created_at", label: "Created", kind: "date" }
      ]} />
      <section className="section">
        <h2>Manual actions</h2>
        {page.items.slice(0, 5).map((item) => (
          <p key={String(item.id)}>
            {String(item.type)}{" "}
            <ActionButton path={`/api/v1/operator/alerts/${item.id}/acknowledge`} label="Acknowledge" />{" "}
            <ActionButton path={`/api/v1/operator/alerts/${item.id}/resolve`} label="Resolve" confirmText="Resolve this alert?" />
          </p>
        ))}
        {page.items.length === 0 ? <p className="muted">No manual alert actions.</p> : null}
      </section>
    </div>
  );
}
