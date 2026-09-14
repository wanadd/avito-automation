import { statusTone } from "@/lib/format";

export function StatusBadge({ value }: { value: unknown }) {
  return <span className={`badge ${statusTone(value)}`}>{String(value ?? "UNKNOWN")}</span>;
}
