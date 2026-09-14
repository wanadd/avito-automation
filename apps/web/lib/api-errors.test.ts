import { describe, expect, it } from "vitest";
import { ApiError, ApiNetworkError, isAuthError } from "./api-errors";

describe("API error model", () => {
  it("identifies authentication and authorization failures", () => {
    expect(isAuthError(new ApiError(401, "Unauthorized"))).toBe(true);
    expect(isAuthError(new ApiError(403, "Forbidden"))).toBe(true);
  });

  it("keeps backend and network failures distinct from auth redirects", () => {
    expect(isAuthError(new ApiError(500, "Internal Server Error"))).toBe(false);
    expect(isAuthError(new ApiNetworkError())).toBe(false);
  });
});
