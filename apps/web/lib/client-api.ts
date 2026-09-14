export function browserApiBase(): string {
  return "";
}

export function csrfFromDocument(): string {
  const match = document.cookie.split("; ").find((item) => item.startsWith("avito_operator_csrf="));
  return match ? decodeURIComponent(match.split("=")[1] ?? "") : "";
}
