import { describe, expect, it } from "vitest";
import { importSummary } from "./imports";

describe("importSummary", () => {
  it("summarizes telegram previews", () => {
    expect(importSummary({ candidate_product_lines: 3, valid_seen_items: 2 })).toBe("2/3 valid lines");
  });

  it("summarizes 1c previews", () => {
    expect(importSummary({ matched_rows: 1, unmatched_rows: 2 })).toBe("1 matched, 2 unmatched");
  });
});
