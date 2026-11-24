export interface ChronologyFilters {
  employee_id: number;
  day: string;
  title: string;
  program: string;
}

export interface ChronologyRow {
  id: number;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  process_name: string | null;
  window_title: string | null;
  url: string | null;
  is_idle: boolean;
}

export interface ChronologyPage {
  items: ChronologyRow[];
  total: number;
  limit: number;
  offset: number;
  timezone: string;
  programs: string[];
}

export interface ChronologyEmployee {
  id: number;
  full_name: string;
}

const path = "/api/v1/reports/day-chronology";

export class ChronologyError extends Error {
  constructor(readonly status: number) {
    super("Day chronology request failed");
  }
}

async function readResponse(response: Response): Promise<Response> {
  if (!response.ok) throw new ChronologyError(response.status);
  return response;
}

async function reportRequest(endpoint: string, filters: ChronologyFilters, signal: AbortSignal) {
  return readResponse(await fetch(path + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
    signal,
    cache: "no-store",
  }));
}

export async function fetchChronology(
  filters: ChronologyFilters & { limit: number; offset: number },
  signal: AbortSignal,
): Promise<ChronologyPage> {
  return (await reportRequest("/query", filters, signal)).json();
}

export async function exportChronology(filters: ChronologyFilters, signal: AbortSignal): Promise<Blob> {
  return (await reportRequest("/export", filters, signal)).blob();
}

export async function searchChronologyEmployees(q: string, signal: AbortSignal): Promise<ChronologyEmployee[]> {
  const params = new URLSearchParams({ limit: "50", q });
  const response = await readResponse(await fetch("/api/v1/employees?" + params, { signal, cache: "no-store" }));
  const page: { items: ChronologyEmployee[] } = await response.json();
  return page.items;
}

export async function fetchChronologyEmployee(id: string, signal: AbortSignal): Promise<ChronologyEmployee> {
  const response = await readResponse(await fetch("/api/v1/employees/" + id, { signal, cache: "no-store" }));
  return response.json();
}
