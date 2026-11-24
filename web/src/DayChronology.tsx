import {
  Alert, Button, Group, Loader, NativeSelect, Pagination, Paper, Select, SimpleGrid,
  Stack, Table, Text, TextInput, Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ChronologyError, exportChronology, fetchChronology, fetchChronologyEmployee, searchChronologyEmployees,
} from "./dayChronologyApi";
import type { ChronologyEmployee, ChronologyPage, ChronologyRow } from "./dayChronologyApi";
import { readReportDay } from "./reportDate";

const pageSize = 50;

function readEmployee(value: string | null): string | null {
  return value && /^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2_147_483_647 ? value : null;
}

export function DayChronology() {
  const [params, setParams] = useSearchParams();
  const employee = readEmployee(params.get("employeeId"));
  const day = readReportDay(params.get("day"));
  const reportKey = (employee ?? "") + "/" + day;

  function select(employeeId: string, selectedDay: string) {
    const next = new URLSearchParams(params);
    next.set("employeeId", employeeId);
    next.set("day", selectedDay);
    setParams(next);
  }

  return (
    <>
      <ChronologySelection key={reportKey} initialEmployee={employee} initialDay={day} onSelect={select} />
      {employee && <ChronologyReport key={reportKey} employee={employee} day={day} />}
    </>
  );
}

interface ChronologySelectionProps {
  initialEmployee: string | null;
  initialDay: string;
  onSelect: (employee: string, day: string) => void;
}

function ChronologySelection({ initialEmployee, initialDay, onSelect }: ChronologySelectionProps) {
  const [employee, setEmployee] = useState(initialEmployee);
  const [day, setDay] = useState(initialDay);
  const [selected, setSelected] = useState<ChronologyEmployee | null>(null);
  const [search, setSearch] = useState("");
  const [query] = useDebouncedValue(search, 250);
  const [choices, setChoices] = useState<{ query: string; items: ChronologyEmployee[] }>();
  const [directoryError, setDirectoryError] = useState(false);

  useEffect(() => {
    if (!initialEmployee) return;
    const abort = new AbortController();
    fetchChronologyEmployee(initialEmployee, abort.signal).then(
      (item) => { if (!abort.signal.aborted) setSelected((current) => current ?? item); },
      () => { /* The report displays an error for a missing selected employee. */ },
    );
    return () => abort.abort();
  }, [initialEmployee]);

  useEffect(() => {
    const abort = new AbortController();
    searchChronologyEmployees(query.trim(), abort.signal).then(
      (items) => {
        if (abort.signal.aborted) return;
        setChoices({ query, items });
        setDirectoryError(false);
      },
      () => { if (!abort.signal.aborted) setDirectoryError(true); },
    );
    return () => abort.abort();
  }, [query]);

  const items = choices?.query === query ? choices.items : [];
  const options = selected && String(selected.id) === employee && !items.some((item) => item.id === selected.id)
    ? [selected, ...items]
    : items;
  const busy = !directoryError && (choices?.query !== query || search !== query);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (employee && day) onSelect(employee, day);
  }

  return (
    <Paper component="section" withBorder p="lg" aria-labelledby="chronology-selection">
      <form onSubmit={submit}>
        <Title order={2} id="chronology-selection" className="section-title">Сотрудник и дата</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }} mt="md">
          <Select
            label="Сотрудник"
            placeholder="Найти по имени"
            searchable
            clearable
            required
            searchValue={search}
            onSearchChange={setSearch}
            value={employee}
            onChange={(value) => {
              setEmployee(value);
              setSelected(options.find((item) => String(item.id) === value) ?? null);
            }}
            filter={({ options: remoteOptions }) => remoteOptions}
            data={options.map((item) => ({ value: String(item.id), label: item.full_name }))}
            rightSection={busy ? <Loader size="xs" /> : undefined}
            nothingFoundMessage={busy ? "Загрузка…" : directoryError ? "Справочник недоступен" : "Сотрудники не найдены"}
          />
          <TextInput type="date" label="Дата" required value={day} min="0001-01-01" max="9999-12-30"
            onChange={(event) => setDay(event.currentTarget.value)} />
        </SimpleGrid>
        <Button type="submit" mt="md" disabled={!employee || !day}>Показать</Button>
      </form>
    </Paper>
  );
}

interface ReportQuery {
  title: string;
  program: string;
  page: number;
}

type ReportState =
  | { request: ReportQuery; value: ChronologyPage }
  | { request: ReportQuery; error: string };

function describeError(error: unknown): string {
  if (error instanceof ChronologyError) {
    if (error.status === 401) return "Сеанс завершён. Войдите в кабинет снова.";
    if (error.status === 404) return "Сотрудник не найден.";
    if (error.status === 413) return "В отчёте слишком много строк для одного листа Excel.";
    if (error.status === 422) return "Проверьте дату и параметры отчёта.";
  }
  return "Не удалось получить отчёт. Повторите попытку.";
}

function ChronologyReport({ employee, day }: { employee: string; day: string }) {
  const [title, setTitle] = useState("");
  const [program, setProgram] = useState("");
  const [query, setQuery] = useState<ReportQuery>({ title: "", program: "", page: 1 });
  const [result, setResult] = useState<ReportState>();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string>();
  const exportAbort = useRef<AbortController | null>(null);
  const active = result?.request === query ? result : undefined;
  const report = active && "value" in active ? active.value : null;
  const programs = result && "value" in result ? result.value.programs : [];

  useEffect(() => {
    const abort = new AbortController();
    fetchChronology({
      employee_id: Number(employee), day, title: query.title, program: query.program,
      limit: pageSize, offset: (query.page - 1) * pageSize,
    }, abort.signal).then(
      (value) => { if (!abort.signal.aborted) setResult({ request: query, value }); },
      (error: unknown) => { if (!abort.signal.aborted) setResult({ request: query, error: describeError(error) }); },
    );
    return () => abort.abort();
  }, [employee, day, query]);

  useEffect(() => () => exportAbort.current?.abort(), []);

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setExportError(undefined);
    setQuery({ title: title.trim(), program, page: 1 });
  }

  async function download() {
    if (exporting) return;
    const abort = new AbortController();
    exportAbort.current = abort;
    setExporting(true);
    setExportError(undefined);
    try {
      const file = await exportChronology({
        employee_id: Number(employee), day, title: query.title, program: query.program,
      }, abort.signal);
      if (abort.signal.aborted) return;
      const fileUrl = URL.createObjectURL(file);
      const link = document.createElement("a");
      link.href = fileUrl;
      link.download = "alkocop-chronology-" + day + ".xlsx";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(fileUrl), 0);
    } catch (error) {
      if (!abort.signal.aborted) setExportError(describeError(error));
    } finally {
      if (!abort.signal.aborted) setExporting(false);
    }
  }

  return (
    <Paper component="section" withBorder p="lg" aria-labelledby="chronology-data">
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={2} id="chronology-data" className="section-title">Отрезки активности</Title>
          <Button variant="outline" disabled={!report?.total} loading={exporting} onClick={download}>Скачать Excel</Button>
        </Group>
        <form onSubmit={apply}>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Заголовок окна" value={title} maxLength={300}
              onChange={(event) => setTitle(event.currentTarget.value)} />
            <NativeSelect label="Программа" value={program}
              data={[{ value: "", label: "Все программы" }, ...programs]}
              onChange={(event) => setProgram(event.currentTarget.value)} />
          </SimpleGrid>
          <Button type="submit" variant="light" mt="sm">Применить</Button>
        </form>
        {exportError && <Alert color="red" role="alert">{exportError}</Alert>}
        {!active && <Text size="sm" c="dimmed" role="status">Загружаем отчёт…</Text>}
        {active && "error" in active && (
          <Alert color="red" role="alert">
            <Group justify="space-between">
              <Text size="sm">{active.error}</Text>
              <Button variant="light" onClick={() => setQuery({ ...query })}>Повторить</Button>
            </Group>
          </Alert>
        )}
        {report && (
          <>
            <Group justify="space-between">
              <Text size="sm" c="dimmed" role="status">Записей: {report.total.toLocaleString("ru-RU")}</Text>
              <Text size="sm" c="dimmed">Часовой пояс: {report.timezone}</Text>
            </Group>
            {report.items.length ? <ChronologyTable rows={report.items} timezone={report.timezone} />
              : <Text c="dimmed">По выбранным параметрам нет отрезков активности.</Text>}
            {report.total > pageSize && <Pagination total={Math.ceil(report.total / pageSize)} value={query.page}
              onChange={(page) => setQuery({ ...query, page })} aria-label="Страницы отчёта" />}
          </>
        )}
      </Stack>
    </Paper>
  );
}

function formatDuration(seconds: number): string {
  if (seconds > 0 && seconds < 1) return "<1 с";
  const whole = Math.floor(seconds);
  const h = Math.floor(whole / 3600);
  const m = Math.floor(whole / 60) % 60;
  const s = whole % 60;
  return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
}

function ChronologyTable({ rows, timezone }: { rows: ChronologyRow[]; timezone: string }) {
  const clock = new Intl.DateTimeFormat("ru-RU", {
    timeZone: timezone, hourCycle: "h23", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const headings = ["Начало", "Конец", "Длительность", "Программа", "Заголовок окна", "Адрес сайта", "Простой"];
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table striped highlightOnHover verticalSpacing="xs" aria-label="Хронометраж дня">
        <Table.Thead><Table.Tr>{headings.map((label) => <Table.Th key={label} scope="col">{label}</Table.Th>)}</Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>{clock.format(new Date(row.started_at))}</Table.Td>
              <Table.Td>{clock.format(new Date(row.ended_at))}</Table.Td>
              <Table.Td>{formatDuration(row.duration_seconds)}</Table.Td>
              {[row.process_name, row.window_title, row.url].map((value, index) => (
                <Table.Td key={index}>
                  <Text size="sm" title={value ?? undefined} lineClamp={2} style={{ overflowWrap: "anywhere" }}>
                    {value || "—"}
                  </Text>
                </Table.Td>
              ))}
              <Table.Td>{row.is_idle ? "Да" : "Нет"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
