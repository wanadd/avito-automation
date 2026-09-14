import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { apiGet } from "@/lib/api";

type BatchPage = {
  id: string;
  import_type: string;
  mode: string;
  status: string;
  filename: string | null;
  created_at: string;
  confirmed_at: string | null;
};

export default async function ImportsPage() {
  const batches = await apiGet<BatchPage[]>("/api/v1/onboarding/imports");
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Imports</h1>
        <div className="inlineActions">
          <Link className="button secondary" href="/imports/telegram">Telegram</Link>
          <Link className="button secondary" href="/imports/onec">1C</Link>
        </div>
      </div>
      <DataTable
        empty="No import batches"
        rows={batches as unknown as Record<string, unknown>[]}
        columns={[
          { key: "import_type", label: "Type" },
          { key: "mode", label: "Mode" },
          { key: "status", label: "Status", kind: "status" },
          { key: "filename", label: "File" },
          { key: "created_at", label: "Created", kind: "date" },
          { key: "confirmed_at", label: "Confirmed", kind: "date" }
        ]}
      />
    </div>
  );
}
