export function money(value: unknown): string {
  if (typeof value !== "number") {
    return "—";
  }
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(value / 100);
}

export function dt(value: unknown): string {
  if (typeof value !== "string") {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export function statusTone(status: unknown): string {
  const text = String(status ?? "");
  if (["READY", "APPROVED", "DRY_RUN_SUCCESS", "DRY_RUN_OK", "SUCCEEDED", "OPEN"].includes(text)) {
    return "good";
  }
  if (["REVIEW_REQUIRED", "REVIEW", "STALE", "PENDING", "QUEUED", "ACKNOWLEDGED"].includes(text)) {
    return "warn";
  }
  if (["BLOCKED", "FAILED", "ERROR", "NO_STOCK", "OUT_OF_STOCK", "REJECTED"].includes(text)) {
    return "bad";
  }
  return "neutral";
}

export function text(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}
