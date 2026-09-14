import { describe, expect, it } from "vitest";
import { money, statusTone, text } from "./format";

describe("operator formatting", () => {
  it("formats minor currency values", () => {
    expect(money(6300000)).toContain("63");
  });

  it("maps compact status taxonomy", () => {
    expect(statusTone("READY")).toBe("good");
    expect(statusTone("REVIEW_REQUIRED")).toBe("warn");
    expect(statusTone("BLOCKED")).toBe("bad");
  });

  it("uses dash for empty values", () => {
    expect(text(null)).toBe("—");
  });
});
