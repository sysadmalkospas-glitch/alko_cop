import {
  Alert, Badge, Button, Group, Pagination, Paper, Select, SimpleGrid, Stack, Table, Text, Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { cabinetFetch } from "./auth";
import { listAllDirectory } from "./settings/api";
import { useDirectoryRequest } from "./settings/loading";

const PAGE_SIZE = 50;
const REFRESH_MS = 30_000;
const REQUEST_TIMEOUT_MS = 8_000;
const MAX_OBSERVATION_AGE_MS = 60_000;

interface DirectoryLabel {
  id: number;
  name: string;
}

interface LiveComputer {
  id: number;
  name: string;
  office: DirectoryLabel | null;
  online: boolean;
  last_seen_at: string | null;
  session: {
    login: string;
    employee: DirectoryLabel | null;
    group: DirectoryLabel | null;
    process_name: string | null;
    window_title: string | null;
    last_input_at: string;
    sampled_at: string;
    is_idle: boolean;
  } | null;
}

interface LivePage {
  items: LiveComputer[];
  total: number;
  as_of: string;
}

const dateTimes = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "medium" });

async function loadFilters(signal: AbortSignal) {
  const [offices, groups] = await Promise.all([
    listAllDirectory("offices", signal),
    listAllDirectory("groups", signal),
  ]);
  return { offices, groups };
}

function validId(value: string | null): string | null {
  return value && /^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2_147_483_647 ? value : null;
}

function choices(options: DirectoryLabel[], selected: string | null) {
  const values = options.map((option) => ({ value: String(option.id), label: option.name }));
  if (selected !== null && !options.some((option) => String(option.id) === selected)) {
    values.push({ value: selected, label: `Запись №${selected}` });
  }
  return values;
}

export default function LiveOverview() {
  const [params, setParams] = useSearchParams();
  const office = validId(params.get("officeId"));
  const group = validId(params.get("groupId"));
  const filters = useDirectoryRequest(loadFilters);
  const directories = filters.status === "ready" ? filters.data : null;

  function select(name: "officeId" | "groupId", value: string | null) {
    const next = new URLSearchParams(params);
    if (value === null) {
      next.delete(name);
    } else {
      next.set(name, value);
    }
    setParams(next);
  }

  return (
    <>
      <Paper withBorder p="lg">
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label="Офис"
            placeholder="Все офисы"
            value={office}
            onChange={(value) => select("officeId", value)}
            data={choices(directories?.offices ?? [], office)}
            disabled={!directories}
            searchable clearable
          />
          <Select
            label="Группа"
            placeholder="Все группы"
            value={group}
            onChange={(value) => select("groupId", value)}
            data={choices(directories?.groups ?? [], group)}
            disabled={!directories}
            searchable clearable
          />
        </SimpleGrid>
        {filters.status === "error" && (
          <Alert color="red" role="alert" mt="md">
            <Group justify="space-between">
              <Text size="sm">Справочники для фильтров недоступны.</Text>
              <Button variant="light" onClick={filters.reload}>Повторить</Button>
            </Group>
          </Alert>
        )}
      </Paper>
      <LiveTable key={`${office ?? ""}/${group ?? ""}`} office={office} group={group} />
    </>
  );
}

type TableState = { page: number; data: LivePage } | { page: number; error: true };

function LiveTable({ office, group }: { office: string | null; group: string | null }) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<TableState>();
  const match = state?.page === page ? state : undefined;
  const data = match && "data" in match ? match.data : null;

  useEffect(() => {
    const controller = new AbortController();
    let expiryTimer: number | undefined;
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
    if (office !== null) query.set("office_id", office);
    if (group !== null) query.set("group_id", group);

    function display(data: LivePage, requestedAt: number) {
      // Age observations against the server clock even when the browser clock differs.
      const cutoff = Date.parse(data.as_of) + performance.now() - requestedAt - MAX_OBSERVATION_AGE_MS;
      let nextExpiry = Infinity;
      function fresh(at: string | null) {
        const remaining = at === null ? 0 : Date.parse(at) - cutoff;
        if (!(remaining > 0)) return false;
        nextExpiry = Math.min(nextExpiry, remaining);
        return true;
      }
      const items = data.items.map((row) => ({
        ...row,
        online: row.online && fresh(row.last_seen_at),
        session: fresh(row.session?.sampled_at ?? null) ? row.session : null,
      }));
      setState({ page, data: { ...data, items } });
      if (Number.isFinite(nextExpiry)) {
        expiryTimer = window.setTimeout(() => display(data, requestedAt), Math.ceil(nextExpiry) + 1);
      }
    }

    async function refresh() {
      const requestedAt = performance.now();
      try {
        const response = await cabinetFetch("/api/v1/reports/live-overview?" + query, {
          cache: "no-store",
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
        });
        if (!response.ok) throw new Error("Live overview request failed");
        const data: LivePage = await response.json();
        if (controller.signal.aborted) return;
        window.clearTimeout(expiryTimer);
        const lastPage = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
        if (page > lastPage) {
          setPage(lastPage);
          return;
        }
        display(data, requestedAt);
      } catch {
        if (!controller.signal.aborted) {
          window.clearTimeout(expiryTimer);
          setState({ page, error: true });
        }
      }
    }

    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, REFRESH_MS);
    return () => {
      controller.abort();
      window.clearTimeout(expiryTimer);
      window.clearInterval(timer);
    };
  }, [office, group, page, revision]);

  return (
    <Paper component="section" aria-labelledby="live-table-title" withBorder p="lg">
      <Stack gap="md">
        <Group justify="space-between">
          <Title id="live-table-title" order={2} className="section-title">Компьютеры</Title>
          <Button variant="subtle" onClick={() => setRevision((value) => value + 1)}>Обновить</Button>
        </Group>
        {!match && <Text size="sm" c="dimmed" role="status">Загружаем состояние компьютеров…</Text>}
        {match && "error" in match && <Alert color="red" role="alert">Не удалось обновить сводку.</Alert>}
        {data && (data.items.length ? <OverviewRows items={data.items} /> :
          <Text c="dimmed">По выбранным фильтрам нет компьютеров.</Text>)}
        {data && data.total > PAGE_SIZE && (
          <Pagination value={page} total={Math.ceil(data.total / PAGE_SIZE)} onChange={setPage}
            aria-label="Страницы оперативной сводки" />
        )}
      </Stack>
    </Paper>
  );
}

function Timestamp({ value }: { value: string | null }) {
  return value === null ? "—" : <time dateTime={value}>{dateTimes.format(new Date(value))}</time>;
}

function OverviewRows({ items }: { items: LiveComputer[] }) {
  const headings = ["Компьютер", "Статус", "Офис", "Сотрудник", "Программа и окно", "Последний ввод", "Последняя связь"];
  return (
    <Table.ScrollContainer minWidth={1000}>
      <Table striped highlightOnHover verticalSpacing="xs" aria-label="Оперативная сводка">
        <Table.Thead><Table.Tr>{headings.map((heading) => <Table.Th key={heading} scope="col">{heading}</Table.Th>)}</Table.Tr></Table.Thead>
        <Table.Tbody>
          {items.map(({ id, name, online, office, session, last_seen_at }) => (
            <Table.Tr key={id}>
              <Table.Th scope="row">{name}</Table.Th>
              <Table.Td>
                <Stack gap={4} align="start">
                  <Badge color={online ? "teal" : "gray"} variant="light">{online ? "На связи" : "Нет связи"}</Badge>
                  {session?.is_idle && <Badge color="orange" variant="light">Простой</Badge>}
                  {online && !session && <Text size="xs" c="dimmed">Нет данных сеанса</Text>}
                </Stack>
              </Table.Td>
              <Table.Td>{office?.name ?? "—"}</Table.Td>
              <Table.Td>
                {session ? (
                  <>
                    <Text size="sm">{session.employee?.name ?? session.login}</Text>
                    <Text size="xs" c="dimmed">{session.group?.name ?? (session.employee ? null : "Логин не привязан")}</Text>
                  </>
                ) : "—"}
              </Table.Td>
              <Table.Td miw={240} maw={340}>
                <Text size="sm">{session?.process_name ?? "—"}</Text>
                {session?.window_title && (
                  <Text size="xs" c="dimmed" lineClamp={2} title={session.window_title} style={{ overflowWrap: "anywhere" }}>
                    {session.window_title}
                  </Text>
                )}
              </Table.Td>
              <Table.Td><Timestamp value={session?.last_input_at ?? null} /></Table.Td>
              <Table.Td><Timestamp value={last_seen_at} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
