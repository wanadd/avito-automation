import { cookies } from "next/headers";

export type Page = {
  items: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
};

export const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const cookieStore = await cookies();
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: {
      cookie: cookieStore.toString()
    }
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}
