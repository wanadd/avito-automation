import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function AuditPage() {
  const page = await apiGet<Page>("/api/v1/operator/audit");
  return (
    <div className="stack">
      <div className="topbar"><h1>Audit</h1><span className="muted">{page.total} events</span></div>
      <DataTable empty="No audit events" rows={page.items} columns={[
        { key: "timestamp", label: "Time", kind: "date" },
        { key: "actor", label: "Actor" },
        { key: "action", label: "Action" },
        { key: "entity", label: "Entity" },
        { key: "entity_id", label: "Entity ID" }
      ]} />
    </div>
  );
}
