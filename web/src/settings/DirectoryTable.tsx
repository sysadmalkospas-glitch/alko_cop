import { Alert, Button, Group, Loader, Pagination, Paper, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { type FormEvent, type ReactNode, useCallback, useState } from "react";
import { type DirectoryPath, type DirectoryRow, listDirectory } from "./api";
import { useDirectoryRequest } from "./loading";

const PAGE_SIZE = 25;

interface Column<T> {
  heading: string;
  cell: (row: T) => ReactNode;
}

interface DirectoryTableProps<K extends DirectoryPath> {
  resource: K;
  title: string;
  searchLabel: string;
  columns: Column<DirectoryRow<K>>[];
  rowKey: (row: DirectoryRow<K>) => number | string;
  actions: (row: DirectoryRow<K>) => ReactNode;
  add?: () => void;
  revision: number;
  empty?: string;
}

export function DirectoryTable<K extends DirectoryPath>({
  resource, title, searchLabel, columns, rowKey, actions, add, revision, empty,
}: DirectoryTableProps<K>) {
  const [submitted, setSubmitted] = useState("");
  const [page, setPage] = useState(1);
  const load = useCallback(async (signal: AbortSignal) => {
    const loadPage = (value: number) => listDirectory(resource, {
      q: submitted, offset: (value - 1) * PAGE_SIZE, limit: PAGE_SIZE,
    }, signal);
    const first = await loadPage(page);
    const finalPage = Math.max(1, Math.ceil(first.total / PAGE_SIZE));
    return page > finalPage
      ? { ...await loadPage(finalPage), page: finalPage }
      : { ...first, page };
  }, [resource, submitted, page]);
  const rows = useDirectoryRequest(load, revision);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("q");
    setSubmitted(typeof value === "string" ? value.trim() : "");
    setPage(1);
  }

  return (
    <Paper withBorder p={{ base: "md", md: "lg" }}>
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={2} size="h3">{title}</Title>
          {add && <Button onClick={add}>Добавить</Button>}
        </Group>
        <Group justify="space-between" align="end">
          <form onSubmit={search} className="directory-search">
            <TextInput name="q" aria-label={searchLabel} placeholder={searchLabel} maxLength={300} />
            <Button type="submit" variant="light">Найти</Button>
          </form>
          <Button variant="subtle" onClick={rows.reload}>Обновить</Button>
        </Group>
        {rows.status === "loading" && <Group role="status"><Loader size="sm" />Загрузка справочника</Group>}
        {rows.status === "error" && <Alert color="red" role="alert">{rows.message}</Alert>}
        {rows.status === "ready" && (
          rows.data.items.length ? (
            <>
              <Table.ScrollContainer minWidth={columns.length > 4 ? 720 : 470}>
                <Table striped highlightOnHover aria-label={title}>
                  <Table.Thead>
                    <Table.Tr>
                      {columns.map(({ heading }) => <Table.Th key={heading} scope="col">{heading}</Table.Th>)}
                      <Table.Th scope="col">Действия</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {rows.data.items.map((row) => (
                      <Table.Tr key={rowKey(row)}>
                        {columns.map(({ heading, cell }) => <Table.Td key={heading}>{cell(row)}</Table.Td>)}
                        <Table.Td>{actions(row)}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              <Group justify="space-between">
                <Text size="sm" c="dimmed">Всего записей {rows.data.total}</Text>
                {rows.data.total > PAGE_SIZE && (
                  <Pagination total={Math.ceil(rows.data.total / PAGE_SIZE)} value={rows.data.page} onChange={setPage} size="sm" />
                )}
              </Group>
            </>
          ) : (
            <Text c="dimmed">{submitted ? "По вашему запросу ничего не найдено." : empty ?? "Записей пока нет."}</Text>
          )
        )}
      </Stack>
    </Paper>
  );
}
