import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const pageSource = readFileSync(join(process.cwd(), "app", "suppliers", "page.tsx"), "utf-8");
const managementSource = readFileSync(join(process.cwd(), "components", "supplier-management.tsx"), "utf-8");

describe("Suppliers operator workflow", () => {
  it("renders useful empty state and create supplier action", () => {
    expect(pageSource).toContain("SupplierManagement");
    expect(managementSource).toContain("No suppliers yet. Create the first supplier to map incoming supplier sources.");
    expect(managementSource).toContain("Create supplier");
  });

  it("creates suppliers through authenticated same-origin operator API", () => {
    expect(managementSource).toContain("/api/v1/operator/suppliers");
    expect(managementSource).toContain('credentials: "include"');
    expect(managementSource).toContain('"X-CSRF-Token": csrfFromDocument()');
  });

  it("shows validation and API errors instead of console-only failure", () => {
    expect(managementSource).toContain("Supplier name is required.");
    expect(managementSource).toContain("Supplier already exists.");
    expect(managementSource).toContain("Supplier create failed.");
    expect(managementSource).toContain("Network error while creating supplier.");
  });
});
