import { DataTable } from "@/components/data-table";
import { apiGet } from "@/lib/api";

type Dashboard = {
  counts: Record<string, number>;
  recent_failures: Record<string, unknown>[];
  recent_review_items: Record<string, unknown>[];
  recent_publication_jobs: Record<string, unknown>[];
  source_freshness: Record<string, unknown>[];
};

const countLabels: Record<string, string> = {
  products: "Products",
  variants: "Variants",
  ready_listings: "Ready",
  review_required: "Review",
  approved: "Approved",
  no_stock: "No stock",
  pricing_review: "Pricing review",
  supplier_stale: "Supplier stale",
  supplier_conflicts: "Conflicts",
  publication_queued: "Queued",
  publication_blocked: "Blocked",
  publication_failed: "Failed",
  dry_run_success: "Dry-run OK",
  open_alerts: "Open alerts"
};

export default async function DashboardPage() {
  const data = await apiGet<Dashboard>("/api/v1/operator/dashboard");
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Dashboard</h1>
        <span className="badge neutral">NO LIVE AVITO MUTATION</span>
      </div>
      <div className="grid">
        {Object.entries(countLabels).map(([key, label]) => (
          <div className="card" key={key}>
            <span className="muted">{label}</span>
            <strong>{data.counts[key] ?? 0}</strong>
          </div>
        ))}
      </div>
      <div className="two">
        <section className="section">
          <h2>Recent review</h2>
          <DataTable
            empty="No review items"
            rows={data.recent_review_items}
            columns={[
              { key: "title", label: "Listing" },
              { key: "readiness", label: "Status", kind: "status" },
              { key: "updated_at", label: "Updated", kind: "date" }
            ]}
          />
        </section>
        <section className="section">
          <h2>Recent publication jobs</h2>
          <DataTable
            empty="No publication jobs"
            rows={data.recent_publication_jobs}
            columns={[
              { key: "id", label: "Job", kind: "link", href: (row) => `/publication/jobs/${row.id}` },
              { key: "status", label: "Status", kind: "status" },
              { key: "error_code", label: "Error" }
            ]}
          />
        </section>
      </div>
      <section className="section">
        <h2>Source freshness</h2>
        <DataTable
          empty="No sources"
          rows={data.source_freshness}
          columns={[
            { key: "name", label: "Source" },
            { key: "type", label: "Type" },
            { key: "enabled", label: "Enabled" },
            { key: "updated_at", label: "Updated", kind: "date" }
          ]}
        />
      </section>
    </div>
  );
}
