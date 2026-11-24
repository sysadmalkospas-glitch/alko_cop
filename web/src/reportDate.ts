export function readReportDay(value: string | null): string {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith("0000")) {
    const day = new Date(value);
    if (Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value) return value;
  }
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow" }).format(new Date());
}
