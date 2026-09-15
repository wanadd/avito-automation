import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { TelegramSourceMapForm } from "@/components/telegram-source-map-form";
import { apiGet, type Page } from "@/lib/api";

type TelegramStatus = {
  enabled: boolean;
  last_update_id: number | null;
  last_success_poll_at: string | null;
  last_api_error: string | null;
  last_successful_price_ingestion_at: string | null;
  pending_ingestion_count: number;
  failed_ingestion_count: number;
  unknown_source_count: number;
};

type TelegramSource = {
  id: string;
  telegram_channel_id: number;
  title: string | null;
  username: string | null;
  source_id: string | null;
  last_received_at: string | null;
};

type TelegramBatch = {
  id: string;
  telegram_price_source_id: string | null;
  source_id: string | null;
  status: string;
  duplicate: boolean;
  message_count: number;
  parsed_rows: number;
  accepted_rows: number;
  review_rows: number;
  failed_rows: number;
  received_at: string;
  processed_at: string | null;
  error: string | null;
};

type Supplier = {
  id: string;
  code: string;
  name: string;
};

export default async function TelegramPricesPage() {
  const [status, sources, batches, suppliers] = await Promise.all([
    apiGet<TelegramStatus>("/api/v1/telegram-prices/status"),
    apiGet<TelegramSource[]>("/api/v1/telegram-prices/sources"),
    apiGet<TelegramBatch[]>("/api/v1/telegram-prices/ingestions"),
    apiGet<Page>("/api/v1/operator/suppliers")
  ]);
  const supplierItems = suppliers.items as Supplier[];
  const sourceRows = sources.map((source) => ({
    ...source,
    mapped: source.source_id ? "MAPPED" : "PENDING",
    map_action: source.source_id ? "Mapped" : (
      <TelegramSourceMapForm
        sourceId={source.id}
        suppliers={supplierItems}
        suggestedName={source.title}
        pendingBatchIds={batches.filter((batch) => batch.telegram_price_source_id === source.id && batch.status === "PENDING_MAPPING").map((batch) => batch.id)}
      />
    )
  }));
  const batchRows = batches.map((batch) => ({
    ...batch,
    duplicate: batch.duplicate ? "yes" : "no",
    action: batch.status === "PENDING_MAPPING" ? "" : (
      <ActionButton path={`/api/v1/telegram-prices/ingestions/${batch.id}/reprocess`} label="Reprocess" body={{}} />
    )
  }));

  return (
    <div className="stack">
      <div className="topbar">
        <h1>Telegram Prices</h1>
        <span className="muted">{status.enabled ? "bot enabled" : "bot disabled"}</span>
      </div>
      <div className="grid">
        <div className="card"><span>Last update</span><strong>{status.last_update_id ?? "none"}</strong></div>
        <div className="card"><span>Pending mapping</span><strong>{status.pending_ingestion_count}</strong></div>
        <div className="card"><span>Unknown sources</span><strong>{status.unknown_source_count}</strong></div>
        <div className="card"><span>Failed</span><strong>{status.failed_ingestion_count}</strong></div>
      </div>
      {status.last_api_error ? <div className="empty">Telegram collector: {status.last_api_error}</div> : null}
      <section className="section stack">
        <h2>Sources</h2>
        <DataTable empty="No Telegram sources" rows={sourceRows} columns={[
          { key: "title", label: "Source" },
          { key: "telegram_channel_id", label: "Channel ID" },
          { key: "username", label: "Username" },
          { key: "mapped", label: "Mapping", kind: "status" },
          { key: "last_received_at", label: "Last received", kind: "date" },
          { key: "map_action", label: "Action" }
        ]} />
      </section>
      <section className="section stack">
        <h2>Ingestions</h2>
        <DataTable empty="No Telegram price ingestions" rows={batchRows} columns={[
          { key: "received_at", label: "Received", kind: "date" },
          { key: "status", label: "Status", kind: "status" },
          { key: "message_count", label: "Messages" },
          { key: "parsed_rows", label: "Rows" },
          { key: "accepted_rows", label: "Accepted" },
          { key: "review_rows", label: "Review" },
          { key: "duplicate", label: "Duplicate" },
          { key: "error", label: "Error" },
          { key: "action", label: "Action" }
        ]} />
      </section>
    </div>
  );
}
