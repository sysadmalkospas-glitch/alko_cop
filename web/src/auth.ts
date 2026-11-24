export interface CabinetUser {
  id: number;
  login: string;
  role: string;
}

export class AuthError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Authentication request returned HTTP ${status}`);
    this.status = status;
  }
}

export async function getSession(signal: AbortSignal): Promise<CabinetUser | null> {
  const response = await fetch("/api/v1/auth/me", { signal });
  if (response.status === 401) return null;
  if (!response.ok) throw new AuthError(response.status);
  return response.json();
}

export async function signIn(login: string, password: string): Promise<CabinetUser> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login, password }),
  });
  if (!response.ok) throw new AuthError(response.status);
  return response.json();
}

export async function signOut(): Promise<void> {
  const response = await fetch("/api/v1/auth/logout", { method: "POST" });
  if (!response.ok && response.status !== 401) throw new AuthError(response.status);
}
