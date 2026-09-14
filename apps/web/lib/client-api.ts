export function browserApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export function csrfFromDocument(): string {
  const match = document.cookie.split("; ").find((item) => item.startsWith("avito_operator_csrf="));
  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}
