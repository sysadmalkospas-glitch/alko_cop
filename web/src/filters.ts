export type Period = "day" | "week" | "month" | "custom";

export interface ReportFilters {
  period: Period;
  from: string;
  to: string;
  office: string;
  group: string;
  employee: string;
}

export const defaultFilters: ReportFilters = {
  period: "day",
  from: "",
  to: "",
  office: "",
  group: "",
  employee: "",
};

function isPeriod(value: string | null): value is Period {
  return value === "day" || value === "week" || value === "month" || value === "custom";
}

function readDate(params: URLSearchParams, key: string): string {
  const value = params.get(key) ?? "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return "";

  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : "";
}

export function readFilters(params: URLSearchParams): ReportFilters {
  const savedPeriod = params.get("period");
  const period = isPeriod(savedPeriod) ? savedPeriod : defaultFilters.period;
  return {
    period,
    from: period === "custom" ? readDate(params, "from") : "",
    to: period === "custom" ? readDate(params, "to") : "",
    office: params.get("office")?.trim() ?? "",
    group: params.get("group")?.trim() ?? "",
    employee: params.get("employee")?.trim() ?? "",
  };
}

export function writeFilters(filters: ReportFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.period !== defaultFilters.period) params.set("period", filters.period);
  if (filters.period === "custom") {
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
  }
  for (const key of ["office", "group", "employee"] as const) {
    const value = filters[key].trim();
    if (value) params.set(key, value);
  }
  return params;
}
