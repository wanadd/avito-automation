import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function InventoryPage() {
  const page = await apiGet<Page>("/api/v1/operator/inventory");
  return (
    <div className="stack">
      <div className="topbar"><h1>Inventory</h1><span className="muted">{page.total} rows</span></div>
      <DataTable empty="No inventory states" rows={page.items} columns={[
        { key: "product", label: "Product" },
        { key: "variant_id", label: "Variant", kind: "link", href: (row) => `/products/${row.variant_id}` },
        { key: "own_stock", label: "Own stock" },
        { key: "own_cost", label: "Own cost", kind: "money" },
        { key: "source_updated_at", label: "Updated", kind: "date" },
        { key: "stale", label: "Stale" }
      ]} />
    </div>
  );
}
