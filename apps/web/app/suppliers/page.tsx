import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function SuppliersPage() {
  const page = await apiGet<Page>("/api/v1/operator/suppliers");
  return (
    <div className="stack">
      <div className="topbar"><h1>Suppliers</h1><span className="muted">{page.total} suppliers</span></div>
      <DataTable empty="No suppliers" rows={page.items} columns={[
        { key: "name", label: "Supplier" },
        { key: "code", label: "Code" },
        { key: "offer_count", label: "Offers" },
        { key: "in_stock_count", label: "In stock" },
        { key: "errors", label: "Errors" },
        { key: "updated_at", label: "Updated", kind: "date" }
      ]} />
    </div>
  );
}
