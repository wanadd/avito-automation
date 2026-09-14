import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function PublicationPage() {
  const page = await apiGet<Page>("/api/v1/operator/publication/jobs");
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Publication</h1>
        <span className="badge warn">NO LIVE AVITO MUTATION</span>
      </div>
      <DataTable empty="No publication jobs" rows={page.items} columns={[
        { key: "id", label: "Job", kind: "link", href: (row) => `/publication/jobs/${row.id}` },
        { key: "operation", label: "Operation" },
        { key: "marketplace", label: "Marketplace" },
        { key: "status", label: "Status", kind: "status" },
        { key: "attempts", label: "Attempts" },
        { key: "created_at", label: "Created", kind: "date" },
        { key: "error_code", label: "Error" }
      ]} />
    </div>
  );
}
