export type ImportPreview = {
  candidate_product_lines?: number;
  valid_seen_items?: number;
  computed_ratio?: number;
  matched_rows?: number;
  unmatched_rows?: number;
  would_update_stock?: number;
  would_update_cost?: number;
};

export function importSummary(preview: ImportPreview | null | undefined): string {
  if (!preview) {
    return "No preview";
  }
  if (typeof preview.candidate_product_lines === "number") {
    return `${preview.valid_seen_items ?? 0}/${preview.candidate_product_lines} valid lines`;
  }
  if (typeof preview.matched_rows === "number") {
    return `${preview.matched_rows} matched, ${preview.unmatched_rows ?? 0} unmatched`;
  }
  return "Preview ready";
}
