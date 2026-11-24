import { Button, Group, NativeSelect, Paper, SimpleGrid, TextInput, Title } from "@mantine/core";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { defaultFilters, readFilters, writeFilters } from "./filters";
import type { Period, ReportFilters as Filters } from "./filters";

const periodOptions: { value: Period; label: string }[] = [
  { value: "day", label: "День" },
  { value: "week", label: "Неделя" },
  { value: "month", label: "Месяц" },
  { value: "custom", label: "Свой период" },
];

const earliestDate = "0001-01-01";
const latestDate = "9999-12-31";

export function ReportFilters() {
  const [params, setParams] = useSearchParams();
  return (
    <FilterForm
      key={params.toString()}
      initial={readFilters(params)}
      onApply={(filters) => setParams(writeFilters(filters))}
    />
  );
}

interface FilterFormProps {
  initial: Filters;
  onApply: (filters: Filters) => void;
}

function FilterForm({ initial, onApply }: FilterFormProps): ReactNode {
  const [filters, setFilters] = useState(initial);

  function change<Key extends keyof Filters>(key: Key, value: Filters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onApply(filters);
  }

  function reset() {
    setFilters(defaultFilters);
    onApply(defaultFilters);
  }

  return (
    <Paper component="section" withBorder p="lg" aria-labelledby="filter-title">
      <form onSubmit={submit}>
        <Title id="filter-title" order={2} className="section-title">Фильтры</Title>
        <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing="md" mt="md">
          <NativeSelect
            label="Период"
            data={periodOptions}
            value={filters.period}
            onChange={(event) => change("period", event.currentTarget.value as Period)}
          />
          <TextInput
            label="Офис"
            placeholder="Все офисы"
            value={filters.office}
            onChange={(event) => change("office", event.currentTarget.value)}
          />
          <TextInput
            label="Группа"
            placeholder="Все группы"
            value={filters.group}
            onChange={(event) => change("group", event.currentTarget.value)}
          />
          <TextInput
            label="Сотрудник"
            placeholder="Все сотрудники"
            value={filters.employee}
            onChange={(event) => change("employee", event.currentTarget.value)}
          />
        </SimpleGrid>
        {filters.period === "custom" && (
          <SimpleGrid cols={{ base: 1, xs: 2 }} maw={510} spacing="md" mt="md">
            <TextInput
              type="date"
              label="Начало периода"
              value={filters.from}
              min={earliestDate}
              max={filters.to || latestDate}
              onChange={(event) => change("from", event.currentTarget.value)}
              required
            />
            <TextInput
              type="date"
              label="Конец периода"
              value={filters.to}
              min={filters.from || earliestDate}
              max={latestDate}
              onChange={(event) => change("to", event.currentTarget.value)}
              required
            />
          </SimpleGrid>
        )}
        <Group gap="xs" mt="lg">
          <Button type="submit">Применить</Button>
          <Button type="button" variant="subtle" onClick={reset}>Сбросить</Button>
        </Group>
      </form>
    </Paper>
  );
}
