import { Text } from "@mantine/core";

const formatter = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" });

function formatTime(timestamp: string) {
  const date = new Date(timestamp);
  return Number.isFinite(date.getTime()) ? formatter.format(date) : null;
}

export function DateCell({ timestamp }: { timestamp: string }) {
  const formatted = formatTime(timestamp);
  return formatted === null ? "—" : <Text component="time" dateTime={timestamp} size="sm">{formatted}</Text>;
}
