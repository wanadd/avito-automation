import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const pageSource = readFileSync(join(process.cwd(), "app", "telegram-prices", "page.tsx"), "utf-8");
const formSource = readFileSync(join(process.cwd(), "components", "telegram-source-map-form.tsx"), "utf-8");
const layoutSource = readFileSync(join(process.cwd(), "app", "layout.tsx"), "utf-8");

describe("Telegram prices operator UI", () => {
  it("lists production Telegram price sources and ingestions", () => {
    expect(pageSource).toContain("/api/v1/telegram-prices/status");
    expect(pageSource).toContain("/api/v1/telegram-prices/sources");
    expect(pageSource).toContain("/api/v1/telegram-prices/ingestions");
  });

  it("maps sources and reprocesses batches through same-origin authenticated API calls", () => {
    expect(formSource).toContain("`${browserApiBase()}/api/v1/telegram-prices/sources/${sourceId}/map`");
    expect(formSource).toContain('credentials: "include"');
    expect(formSource).toContain('"X-CSRF-Token": csrfFromDocument()');
    expect(pageSource).toContain("/api/v1/telegram-prices/ingestions/${batch.id}/reprocess");
  });

  it("adds Telegram prices to operator navigation", () => {
    expect(layoutSource).toContain('["/telegram-prices", "Telegram Prices"]');
  });
});
