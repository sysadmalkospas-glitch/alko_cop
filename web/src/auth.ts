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

const sessionEvents = new EventTarget();
let sessionGeneration = 0;

export function onSessionExpired(listener: () => void) {
  sessionEvents.addEventListener("expired", listener);
  return () => sessionEvents.removeEventListener("expired", listener);
}

export async function cabinetFetch(path: string, init?: RequestInit): Promise<Response> {
  const generation = sessionGeneration;
  const response = await fetch(path, init);
  if (response.status === 401 && generation === sessionGeneration && !init?.signal?.aborted) {
    sessionGeneration += 1;
    sessionEvents.dispatchEvent(new Event("expired"));
  }
  return response;
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
  sessionGeneration += 1;
  return response.json();
}

export async function signOut(): Promise<void> {
  const response = await fetch("/api/v1/auth/logout", { method: "POST" });
  if (!response.ok && response.status !== 401) throw new AuthError(response.status);
  sessionGeneration += 1;
}
