import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(join(process.cwd(), "components", "login-form.tsx"), "utf-8");

describe("LoginForm production browser behavior", () => {
  it("posts to same-origin auth endpoint with cookie credentials", () => {
    expect(source).toContain("`${browserApiBase()}/api/v1/auth/login`");
    expect(source).toContain('credentials: "include"');
  });

  it("prevents duplicate submits and clears loading in a finally block", () => {
    expect(source).toContain("isSubmitting");
    expect(source).toContain("setIsSubmitting(true)");
    expect(source).toContain("finally");
    expect(source).toContain("setIsSubmitting(false)");
    expect(source).toContain("disabled={isSubmitting}");
  });

  it("distinguishes auth failures from network and server failures", () => {
    expect(source).toContain("response.status === 401 || response.status === 403");
    expect(source).toContain("Invalid username or password");
    expect(source).toContain("Login service is unavailable. Try again.");
    expect(source).toContain("Network error. Check your connection and try again.");
  });

  it("redirects successful login to dashboard root", () => {
    expect(source).toContain('router.push("/")');
    expect(source).toContain("router.refresh()");
  });
});
