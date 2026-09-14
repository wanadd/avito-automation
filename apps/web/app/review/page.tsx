import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { apiGet } from "@/lib/api";

export default async function ReviewPage() {
  const items = await apiGet<Record<string, unknown>[]>("/api/v1/control/review-queue?limit=50");
  return (
    <div className="stack">
      <div className="topbar"><h1>Review Queue</h1><ActionButton path="/api/v1/control/recalculate" label="Recalculate" /></div>
      <DataTable empty="No review items" rows={items} columns={[
        { key: "priority", label: "Priority" },
        { key: "listing_id", label: "Listing" },
        { key: "generic_readiness", label: "Readiness", kind: "status" },
        { key: "reason", label: "Reason" },
        { key: "price_minor", label: "Price", kind: "money" },
        { key: "updated_at", label: "Updated", kind: "date" }
      ]} />
    </div>
  );
}
