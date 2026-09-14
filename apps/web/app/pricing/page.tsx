import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function PricingPage() {
  const page = await apiGet<Page>("/api/v1/operator/pricing");
  return (
    <div className="stack">
      <div className="topbar"><h1>Pricing</h1><span className="muted">{page.total} rows</span></div>
      <DataTable empty="No pricing states" rows={page.items} columns={[
        { key: "product", label: "Product" },
        { key: "variant_id", label: "Variant", kind: "link", href: (row) => `/products/${row.variant_id}` },
        { key: "selected_source", label: "Source", kind: "status" },
        { key: "hard_floor", label: "Floor", kind: "money" },
        { key: "final_price", label: "Final", kind: "money" },
        { key: "profit", label: "Profit", kind: "money" },
        { key: "status", label: "Status", kind: "status" }
      ]} />
    </div>
  );
}
