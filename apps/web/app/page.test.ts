import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(join(process.cwd(), "app", "page.tsx"), "utf-8");

describe("dashboard root auth behavior", () => {
  it("redirects anonymous auth failures to login deterministically", () => {
    expect(source).toContain('redirect("/login")');
    expect(source).toContain("isAuthError(error)");
  });

  it("does not convert non-auth API failures into login redirects", () => {
    expect(source).toContain("throw error;");
  });
});
