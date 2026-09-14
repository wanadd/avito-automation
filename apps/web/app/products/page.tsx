import { DataTable } from "@/components/data-table";
import { apiGet, type Page } from "@/lib/api";

export default async function ProductsPage() {
  const page = await apiGet<Page>("/api/v1/operator/products");
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Products</h1>
        <span className="muted">{page.total} variants</span>
      </div>
      <DataTable
        empty="No products"
        rows={page.items}
        columns={[
          { key: "brand", label: "Brand" },
          { key: "model", label: "Model" },
          { key: "variant_id", label: "Variant", kind: "link", href: (row) => `/products/${row.variant_id}` },
          { key: "model_code", label: "Code" },
          { key: "storage_gb", label: "Storage" },
          { key: "condition", label: "Condition", kind: "status" }
        ]}
      />
    </div>
  );
}
