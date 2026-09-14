import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { apiGet } from "@/lib/api";
import { money, text } from "@/lib/format";

type Detail = {
  identity: Record<string, unknown>;
  supplier: Record<string, unknown>[];
  inventory: Record<string, unknown> | null;
  pricing: Record<string, unknown> | null;
  facts: Record<string, unknown> | null;
  content: Record<string, unknown> | null;
  images: Record<string, unknown> | null;
  listing: Record<string, unknown> | null;
  publication: {
    binding: Record<string, unknown> | null;
    latest_job: Record<string, unknown> | null;
    avito_real_mutation: string;
  };
  audit: Record<string, unknown>[];
};

export default async function ProductDetailPage({ params }: { params: Promise<{ variantId: string }> }) {
  const { variantId } = await params;
  const data = await apiGet<Detail>(`/api/v1/operator/products/${variantId}`);
  return (
    <div className="stack">
      <div className="topbar">
        <h1>{text(data.identity.brand)} {text(data.identity.model)}</h1>
        <StatusBadge value={data.listing?.readiness ?? "NO_LISTING"} />
      </div>
      <div className="two">
        <section className="section">
          <h2>Identity</h2>
          <p>Model code: {text(data.identity.model_code)}</p>
          <p>RAM/storage: {text(data.identity.ram_gb)} / {text(data.identity.storage_gb)}</p>
          <p>Color: {text(data.identity.color)}</p>
          <p>Condition: {text(data.identity.condition)}</p>
          <p className="muted">{text(data.identity.canonical_key)}</p>
        </section>
        <section className="section">
          <h2>Pricing + Inventory</h2>
          <p>Stock: {text(data.inventory?.own_stock_total)}</p>
          <p>Cost: {money(data.inventory?.own_cost_minor)}</p>
          <p>Final price: {money(data.pricing?.final_price_minor)}</p>
          <p>Floor: {money(data.pricing?.hard_floor_minor)}</p>
          <p>Decision: <StatusBadge value={data.pricing?.stock_decision ?? "UNKNOWN"} /></p>
        </section>
      </div>
      <section className="section">
        <h2>Supplier</h2>
        <DataTable
          empty="No supplier offers"
          rows={data.supplier}
          columns={[
            { key: "supplier_id", label: "Supplier" },
            { key: "price_minor", label: "Price", kind: "money" },
            { key: "availability", label: "Availability", kind: "status" },
            { key: "updated_at", label: "Updated", kind: "date" }
          ]}
        />
      </section>
      <div className="two">
        <section className="section">
          <h2>Facts + Content</h2>
          <p>Facts hash: {text(data.facts?.fact_hash)}</p>
          <p>Content: <StatusBadge value={data.content?.status ?? "NONE"} /></p>
          <p>Title: {text(data.content?.title)}</p>
          <p>Images: <StatusBadge value={data.images?.status ?? "NONE"} /></p>
        </section>
        <section className="section">
          <h2>Publication</h2>
          <p>Binding: <StatusBadge value={data.publication.binding?.status ?? "UNBOUND"} /></p>
          <p>Sync: <StatusBadge value={data.publication.binding?.sync_state ?? "NOT_PREPARED"} /></p>
          <p>Latest job: <StatusBadge value={data.publication.latest_job?.status ?? "NONE"} /></p>
          <p>{data.publication.avito_real_mutation}</p>
        </section>
      </div>
      <section className="section">
        <h2>Audit</h2>
        <DataTable
          empty="No audit events"
          rows={data.audit}
          columns={[
            { key: "created_at", label: "Time", kind: "date" },
            { key: "action", label: "Action" },
            { key: "actor_type", label: "Actor" }
          ]}
        />
      </section>
    </div>
  );
}
