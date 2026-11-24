import { Alert, Button, Code, Group, Modal, Stack, Text } from "@mantine/core";
import { useCallback, useState } from "react";
import {
  bindLogin, directoryErrorMessage, type Employee, listAllDirectory, listAllEmployeeLogins, type UnknownLogin, unbindLogin,
} from "./api";
import { DateCell } from "./DateCell";
import { type Choice, DirectoryEditor, DirectoryOptionsStatus, DirectorySelect } from "./DirectoryEditor";
import { DirectoryTable } from "./DirectoryTable";
import { useDirectoryRequest } from "./loading";

async function loadEmployeeOptions(signal: AbortSignal): Promise<Choice[]> {
  const employees = await listAllDirectory("employees", signal);
  const names = new Map<string, number>();
  for (const { full_name } of employees) names.set(full_name, (names.get(full_name) ?? 0) + 1);
  return employees.map(({ id, full_name, is_dismissed }) => {
    const name = (names.get(full_name) ?? 0) > 1 ? `${full_name} (№${id})` : full_name;
    return { id, label: is_dismissed ? `${name} · уволен` : name };
  });
}

async function loadComputerNames(signal: AbortSignal) {
  return new Map((await listAllDirectory("computers", signal)).map(({ id, name }) => [id, name]));
}

export function UnknownLoginsDirectory() {
  const [selected, setSelected] = useState<UnknownLogin>();
  const [revision, setRevision] = useState(0);
  const computers = useDirectoryRequest(loadComputerNames);

  return (
    <>
      <DirectoryTable
        resource="logins/unknown"
        title="Неизвестные логины"
        searchLabel="Поиск по логину Windows"
        columns={[
          { heading: "Логин Windows", cell: (row) => <Code>{row.login}</Code> },
          { heading: "Компьютер", cell: (row) => {
            if (row.last_computer_id === null) return "—";
            const label = computers.status === "ready" ? computers.data.get(row.last_computer_id) : undefined;
            return label ?? `Компьютер №${row.last_computer_id}`;
          } },
          { heading: "Последнее появление", cell: (row) => <DateCell timestamp={row.last_seen_at} /> },
        ]}
        rowKey={(row) => row.login}
        actions={(row) => <Button size="compact-sm" variant="subtle" onClick={() => setSelected(row)}>Привязать</Button>}
        revision={revision}
        empty="Неизвестных логинов нет."
      />
      {selected && (
        <BindLoginDialog
          login={selected.login}
          onClose={() => setSelected(undefined)}
          onSaved={() => {
            setSelected(undefined);
            setRevision((value) => value + 1);
          }}
        />
      )}
    </>
  );
}

function BindLoginDialog({ login, onClose, onSaved }: { login: string; onClose: () => void; onSaved: () => void }) {
  const options = useDirectoryRequest(loadEmployeeOptions);
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  return (
    <DirectoryEditor
      title="Привязать логин Windows"
      onClose={onClose}
      onSaved={onSaved}
      onSave={() => employeeId === null ? Promise.reject(new Error("Employee is required")) : bindLogin(employeeId, login)}
      submitLabel="Привязать"
      canSubmit={options.status === "ready" && employeeId !== null}
    >
      <Text>Логин <Code>{login}</Code></Text>
      {options.status === "ready" ? (
        options.data.length ? (
          <DirectorySelect
            name="employee_id"
            label="Сотрудник"
            empty="Выберите сотрудника"
            choices={options.data}
            required
            onChange={setEmployeeId}
          />
        ) : <Text c="dimmed">Сначала добавьте сотрудника в справочник.</Text>
      ) : <DirectoryOptionsStatus options={options} />}
    </DirectoryEditor>
  );
}

export function EmployeeLoginsDialog({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const load = useCallback((signal: AbortSignal) => listAllEmployeeLogins(employee.id, signal), [employee.id]);
  const rows = useDirectoryRequest(load);
  const [pending, setPending] = useState<number>();
  const [error, setError] = useState<string>();

  async function detach(loginId: number, login: string) {
    if (pending !== undefined || !window.confirm(`Отвязать логин ${login} от сотрудника?`)) return;
    setPending(loginId);
    setError(undefined);
    try {
      await unbindLogin(employee.id, loginId);
      rows.reload();
    } catch (cause) {
      setError(directoryErrorMessage(cause));
    } finally {
      setPending(undefined);
    }
  }

  return (
    <Modal opened onClose={onClose} title="Логины Windows" centered closeButtonProps={{ "aria-label": "Закрыть" }}>
      <Stack>
        <Text fw={600}>{employee.full_name}</Text>
        {error && <Alert color="red" role="alert">{error}</Alert>}
        <DirectoryOptionsStatus options={rows} />
        {rows.status === "ready" && (rows.data.length ? (
          rows.data.map(({ id, login }) => (
            <Group key={id} justify="space-between">
              <Code>{login}</Code>
              <Button
                size="compact-sm"
                variant="subtle"
                color="red"
                disabled={pending !== undefined && pending !== id}
                loading={pending === id}
                onClick={() => { void detach(id, login); }}
              >
                Отвязать
              </Button>
            </Group>
          ))
        ) : <Text c="dimmed">У сотрудника пока нет привязанных логинов.</Text>)}
      </Stack>
    </Modal>
  );
}
