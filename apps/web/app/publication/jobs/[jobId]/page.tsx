import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { apiGet } from "@/lib/api";
import { text } from "@/lib/format";

type JobDetail = {
  job: Record<string, unknown>;
  attempts: Record<string, unknown>[];
  state_history: Record<string, unknown>[];
  avito_real_mutation: string;
};

export default async function PublicationJobPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  const data = await apiGet<JobDetail>(`/api/v1/operator/publication/jobs/${jobId}`);
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Publication Job</h1>
        <StatusBadge value={data.job.status} />
      </div>
      <section className="section">
        <h2>Summary</h2>
        <p>Operation: {text(data.job.operation)}</p>
        <p>Error: {text(data.job.error_code)}</p>
        <p>{data.avito_real_mutation}</p>
        <ActionButton path={`/api/v1/control/publication-jobs/${jobId}/retry`} label="Retry" confirmText="Retry this job?" />{" "}
        <ActionButton path={`/api/v1/control/publication-jobs/${jobId}/cancel`} label="Cancel" confirmText="Cancel this job?" />
      </section>
      <section className="section">
        <h2>Attempts</h2>
        <DataTable empty="No attempts" rows={data.attempts} columns={[
          { key: "attempt_number", label: "Attempt" },
          { key: "status", label: "Status", kind: "status" },
          { key: "error_code", label: "Error" },
          { key: "started_at", label: "Started", kind: "date" }
        ]} />
      </section>
      <section className="section">
        <h2>Prepared internal payload</h2>
        <code className="code">{JSON.stringify(data.job.prepared_payload ?? {}, null, 2)}</code>
      </section>
      <section className="section">
        <h2>State history</h2>
        <DataTable empty="No state history" rows={data.state_history} columns={[
          { key: "created_at", label: "Time", kind: "date" },
          { key: "event_type", label: "Event" },
          { key: "old_status", label: "Old" },
          { key: "new_status", label: "New", kind: "status" }
        ]} />
      </section>
    </div>
  );
}
