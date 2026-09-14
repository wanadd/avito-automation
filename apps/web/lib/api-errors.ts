export class ApiError extends Error {
  status: number;
  statusText: string;

  constructor(status: number, statusText: string) {
    super(`${status} ${statusText}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
  }
}

export class ApiNetworkError extends Error {
  constructor(message = "API network request failed") {
    super(message);
    this.name = "ApiNetworkError";
  }
}

export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}
