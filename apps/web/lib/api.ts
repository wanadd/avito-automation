import { cookies } from "next/headers";
import { ApiError, ApiNetworkError } from "./api-errors";

export type Page = {
  items: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
};

export const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const cookieStore = await cookies();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers: {
        cookie: cookieStore.toString()
      }
    });
  } catch (error) {
    throw new ApiNetworkError(error instanceof Error ? error.message : undefined);
  }
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText);
  }
  return (await response.json()) as T;
}
