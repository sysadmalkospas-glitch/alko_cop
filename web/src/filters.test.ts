import assert from "node:assert/strict";
import { test } from "node:test";
import { defaultFilters, readFilters, writeFilters } from "./filters.ts";

test("sharing a report URL preserves the date range and Russian filter values", () => {
  const filters = {
    period: "custom" as const,
    from: "2024-02-29",
    to: "2024-03-12",
    office: "Клиника № 2",
    group: "Рабочая группа",
    employee: "Иванова & Петров",
  };
  const url = new URL("https://alkocop.example/reports/time-tracking");
  url.search = writeFilters(filters).toString();
  assert.deepEqual(readFilters(new URL(url.href).searchParams), filters);
});

test("defaults produce a clean URL and period presets remove the custom dates", () => {
  assert.equal(writeFilters(defaultFilters).toString(), "");
  assert.equal(writeFilters({
    ...defaultFilters,
    period: "week",
    from: "2024-01-01",
    to: "2024-01-02",
    group: "  ",
  }).toString(), "period=week");
});

test("unexpected periods and invalid dates fall back to editable fields", () => {
  assert.deepEqual(readFilters(new URLSearchParams("period=tomorrow")), defaultFilters);
  assert.deepEqual(
    readFilters(new URLSearchParams("period=custom&from=2025-02-29&to=2025-03-02")),
    { ...defaultFilters, period: "custom", to: "2025-03-02" },
  );
});
