import { cabinetFetch } from "../auth";

export interface Office {
  id: number;
  name: string;
  timezone: string;
}

export interface GroupRecord {
  id: number;
  name: string;
  office_id: number | null;
  profile_id: number | null;
}

export interface Position {
  id: number;
  name: string;
}

export interface MonitoringProfile {
  id: number;
  name: string;
  is_default: boolean;
}

export interface Employee {
  id: number;
  full_name: string;
  group_id: number | null;
  position_id: number | null;
  is_dismissed: boolean;
}

export interface EmployeeLogin {
  id: number;
  login: string;
}

export interface Computer {
  id: number;
  name: string;
  hostname: string;
  office_id: number | null;
  profile_id: number | null;
  agent_version: string | null;
  last_seen_at: string | null;
}

export interface UnknownLogin {
  login: string;
  last_seen_at: string;
  last_computer_id: number | null;
}

interface DirectoryShapes {
  offices: Office;
  groups: GroupRecord;
  positions: Position;
  employees: Employee;
  computers: Computer;
  "monitoring-profiles": MonitoringProfile;
  "logins/unknown": UnknownLogin;
}

export type DirectoryPath = keyof DirectoryShapes;
export type DirectoryRow<K extends DirectoryPath> = DirectoryShapes[K];

export interface Page<T> {
  items: T[];
  total: number;
}

export type EditableDirectory = "offices" | "groups" | "positions" | "employees" | "computers";
type Payload = Record<string, string | number | boolean | null>;

const errorMessages = {
  401: "Сеанс завершён. Войдите снова.",
  403: "Нет доступа к этой операции.",
  404: "Запись больше недоступна. Обновите список.",
  409: "Изменения конфликтуют с другой записью. Обновите список и проверьте значения.",
  422: "Проверьте значения полей.",
} as const;

const conflictMessages = new Map([
  ["Duplicate directory value", "Такая запись уже существует."],
  ["Directory record is in use", "Запись используется в других справочниках."],
  ["Referenced directory record does not exist", "Связанная запись больше недоступна. Обновите список."],
]);

class DirectoryError extends Error {
  constructor(readonly status: number, readonly conflict?: string) {
    super("Directory request failed");
  }
}

export function directoryErrorMessage(error: unknown) {
  if (error instanceof DirectoryError && error.conflict) return error.conflict;
  return error instanceof DirectoryError && error.status in errorMessages
    ? errorMessages[error.status as keyof typeof errorMessages]
    : "Не удалось выполнить запрос. Попробуйте ещё раз.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await cabinetFetch(`/api/v1/${path}`, init);
  if (response.status === 409) {
    const body: { detail?: unknown } | null = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new DirectoryError(409, typeof detail === "string" ? conflictMessages.get(detail) : undefined);
  }
  if (!response.ok) throw new DirectoryError(response.status);
  if (response.status === 204) return undefined as T;
  return response.json();
}

interface PageQuery {
  limit: number;
  offset: number;
  q?: string;
}

function list<T>(path: string, { limit, offset, q }: PageQuery, signal: AbortSignal) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  return request<Page<T>>(`${path}?${params}`, { signal });
}

export function listDirectory<K extends DirectoryPath>(resource: K, query: PageQuery, signal: AbortSignal) {
  return list<DirectoryRow<K>>(resource, query, signal);
}

async function listAll<T>(loadPage: (offset: number) => Promise<Page<T>>) {
  const rows: T[] = [];
  for (;;) {
    const page = await loadPage(rows.length);
    rows.push(...page.items);
    if (page.items.length === 0 || rows.length >= page.total) return rows;
  }
}

export function listAllDirectory<K extends DirectoryPath>(resource: K, signal: AbortSignal) {
  return listAll((offset) => listDirectory(resource, { limit: 200, offset }, signal));
}

function write(method: "POST" | "PATCH", body: Payload): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function saveDirectory(resource: EditableDirectory, id: number | undefined, payload: Payload) {
  if (id === undefined) return request(resource, write("POST", payload));
  return request(`${resource}/${id}`, write("PATCH", payload));
}

export function listAllEmployeeLogins(employeeId: number, signal: AbortSignal) {
  const path = `employees/${employeeId}/logins`;
  return listAll((offset) => list<EmployeeLogin>(path, { limit: 200, offset }, signal));
}

export function bindLogin(employeeId: number, login: string) {
  return request(`employees/${employeeId}/logins`, write("POST", { login }));
}

export function unbindLogin(employeeId: number, loginId: number) {
  return request(`employees/${employeeId}/logins/${loginId}`, { method: "DELETE" });
}

export function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

export function formId(data: FormData, name: string) {
  const value = formText(data, name);
  return value ? Number(value) : null;
}
