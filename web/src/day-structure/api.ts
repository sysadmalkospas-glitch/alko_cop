import { cabinetFetch } from "../auth";
import { listAllDirectory } from "../settings/api";

export const PAGE_SIZE = 30;

export type ActivityStatus = "active" | "idle" | "no_data";

export interface Interval {
  starts_at: string;
  ends_at: string;
}

export interface ActivityInterval extends Interval {
  status: ActivityStatus;
  process_name: string | null;
  window_title: string | null;
}

interface ScheduleInterval extends Interval {
  is_break: boolean;
}

export interface EmployeeTimeline {
  employee_id: number;
  full_name: string;
  activity: ActivityInterval[];
  schedule: ScheduleInterval[];
}

export interface DayStructure extends Interval {
  day: string;
  timezone: string;
  total: number;
  rows: EmployeeTimeline[];
}

export class DayStructureError extends Error {}

export async function loadGroupChoices(signal: AbortSignal) {
  const [groups, offices] = await Promise.all([
    listAllDirectory("groups", signal), listAllDirectory("offices", signal),
  ]);
  const officeNames = new Map(offices.map(({ id, name }) => [id, name]));
  return groups.map(({ id, name, office_id }) => {
    const office = office_id === null ? undefined : officeNames.get(office_id);
    return { value: String(id), label: office ? name + " · " + office : name };
  });
}

export async function loadDayStructure(group: string, day: string, page: number, signal: AbortSignal): Promise<DayStructure> {
  const params = new URLSearchParams({
    group_id: group, day, limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE),
  });
  const response = await cabinetFetch("/api/v1/reports/day-structure?" + params, { signal, cache: "no-store" });
  if (!response.ok) {
    switch (response.status) {
      case 404: throw new DayStructureError("Группа не найдена.");
      case 422: throw new DayStructureError("Проверьте выбранную группу и дату.");
      default: throw new DayStructureError("Не удалось загрузить отчёт.");
    }
  }
  return response.json();
}
