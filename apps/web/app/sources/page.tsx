import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function SourcesPage() {
  const page = await apiGet<Page>("/api/v1/operator/sources");
  return (
    <div className="stack">
      <div className="topbar"><h1>Source Health</h1><span className="muted">{page.total} sources</span></div>
      <DataTable empty="No sources" rows={page.items} columns={[
        { key: "name", label: "Source" },
        { key: "type", label: "Type" },
        { key: "enabled", label: "Enabled" },
        { key: "last_run", label: "Last run", kind: "date" },
        { key: "last_success", label: "Last success", kind: "date" },
        { key: "status", label: "Status", kind: "status" },
        { key: "error_summary", label: "Error" }
      ]} />
    </div>
  );
}
