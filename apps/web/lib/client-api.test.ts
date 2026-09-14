import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApiBase, csrfFromDocument } from "./client-api";

describe("browser API addressing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses same-origin browser requests", () => {
    expect(browserApiBase()).toBe("");
    expect(`${browserApiBase()}/api/v1/auth/login`).toBe("/api/v1/auth/login");
  });

  it("does not fall back to localhost or build-time public API hosts", () => {
    expect(browserApiBase()).not.toContain("localhost");
    expect(browserApiBase()).not.toContain("NEXT_PUBLIC_API_BASE_URL");
  });

  it("keeps CSRF extraction from browser cookies", () => {
    vi.stubGlobal("document", { cookie: "other=1; avito_operator_csrf=token-123" });
    expect(csrfFromDocument()).toBe("token-123");
  });
});
