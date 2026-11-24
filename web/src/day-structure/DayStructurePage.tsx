import {
  Alert, Button, Group, Loader, Pagination, Paper, Select, SimpleGrid, Stack, Text, TextInput, Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { readReportDay } from "../reportDate";
import { useDirectoryRequest } from "../settings/loading";
import { DayStructureError, loadDayStructure, loadGroupChoices, PAGE_SIZE } from "./api";
import type { DayStructure } from "./api";
import { Timeline } from "./Timeline";
import "./day-structure.css";

function readGroup(value: string | null) {
  return value && /^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2_147_483_647 ? value : null;
}

export default function DayStructurePage() {
  const [params, setParams] = useSearchParams();
  const day = readReportDay(params.get("day"));
  const group = readGroup(params.get("groupId"));
  const reportKey = (group ?? "") + "/" + day;

  function select(groupId: string, selectedDay: string) {
    const next = new URLSearchParams(params);
    next.set("groupId", groupId);
    next.set("day", selectedDay);
    setParams(next);
  }

  return (
    <>
      <Title order={1} className="page-heading">Структура дня</Title>
      <DaySelection key={reportKey} initialGroup={group} initialDay={day} onSelect={select} />
      {group && <GroupReport key={reportKey} group={group} day={day} />}
    </>
  );
}

function DaySelection({ initialGroup, initialDay, onSelect }: {
  initialGroup: string | null;
  initialDay: string;
  onSelect: (group: string, day: string) => void;
}) {
  const [group, setGroup] = useState(initialGroup);
  const [day, setDay] = useState(initialDay);
  const options = useDirectoryRequest(loadGroupChoices);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (group && day) onSelect(group, day);
  }

  return (
    <Paper component="section" withBorder p="lg" aria-labelledby="structure-selection">
      <form onSubmit={submit}>
        <Title order={2} id="structure-selection" className="section-title">Группа и дата</Title>
        <SimpleGrid cols={{ base: 1, sm: 2 }} maw={640} mt="md">
          <Select
            label="Группа" placeholder="Выберите группу" searchable required
            value={group} onChange={setGroup} data={options.status === "ready" ? options.data : []}
            rightSection={options.status === "loading" ? <Loader size="xs" /> : undefined}
            nothingFoundMessage={options.status === "loading" ? "Загрузка…" : "Группы не найдены"}
            limit={50}
          />
          <TextInput type="date" label="Дата" required value={day} min="0001-01-02" max="9999-12-30"
            onChange={(event) => setDay(event.currentTarget.value)} />
        </SimpleGrid>
        {options.status === "error" && (
          <Alert color="red" role="alert" my="sm">
            <Group justify="space-between">
              <Text size="sm">{options.message}</Text>
              <Button variant="light" onClick={options.reload}>Повторить</Button>
            </Group>
          </Alert>
        )}
        <Button type="submit" mt="md" disabled={!group || !day}>Показать</Button>
      </form>
    </Paper>
  );
}

type Result = { report: DayStructure } | { error: string };

function GroupReport({ group, day }: { group: string; day: string }) {
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; value: Result }>();
  const key = page + "/" + attempt;
  const pageResult = result?.key === key ? result.value : undefined;

  useEffect(() => {
    const abort = new AbortController();
    loadDayStructure(group, day, page, abort.signal).then(
      (report) => {
        if (abort.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(report.total / PAGE_SIZE));
        if (page > lastPage) setPage(lastPage);
        else setResult({ key, value: { report } });
      },
      (error: unknown) => {
        if (!abort.signal.aborted) {
          const message = error instanceof DayStructureError ? error.message : "Не удалось загрузить отчёт.";
          setResult({ key, value: { error: message } });
        }
      },
    );
    return () => abort.abort();
  }, [group, day, page, key]);

  return (
    <Paper component="section" withBorder p={{ base: "md", md: "lg" }} aria-labelledby="structure-timeline">
      <Stack gap="md">
        <Title order={2} id="structure-timeline" className="section-title">Шкала активности</Title>
        {!pageResult && <Group role="status"><Loader size="xs" />Загружаем отчёт…</Group>}
        {pageResult && "error" in pageResult && (
          <Alert color="red" role="alert">
            <Group justify="space-between">
              <Text size="sm">{pageResult.error}</Text>
              <Button variant="light" onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>
            </Group>
          </Alert>
        )}
        {pageResult && "report" in pageResult && (
          pageResult.report.total === 0 ? <Text c="dimmed">В группе нет сотрудников.</Text> : (
            <>
              <Timeline data={pageResult.report} />
              {pageResult.report.total > PAGE_SIZE && (
                <Pagination total={Math.ceil(pageResult.report.total / PAGE_SIZE)} value={page}
                  onChange={setPage} aria-label="Страницы отчёта" />
              )}
            </>
          )
        )}
      </Stack>
    </Paper>
  );
}
