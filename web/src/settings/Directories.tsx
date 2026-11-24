import { Badge, Button, Checkbox, Stack, Text, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { type Employee, formId, formText, listAllDirectory } from "./api";
import { type Choice, DirectoryOptionsStatus, DirectorySelect } from "./DirectoryEditor";
import { DateCell } from "./DateCell";
import { EmployeeLoginsDialog } from "./Logins";
import { useDirectoryRequest } from "./loading";
import { ManagedDirectory } from "./ManagedDirectory";

export function OfficesDirectory() {
  return (
    <ManagedDirectory
      resource="offices"
      title="Офисы"
      editName="офис"
      columns={[
        { heading: "Название", cell: (row) => row.name },
        { heading: "Часовой пояс", cell: (row) => row.timezone },
      ]}
      fields={(row) => (
        <>
          <TextInput required name="name" label="Название" defaultValue={row?.name} maxLength={200} data-autofocus />
          <TextInput
            required
            name="timezone"
            label="Часовой пояс"
            description="Название часового пояса IANA"
            defaultValue={row?.timezone ?? "Europe/Moscow"}
            maxLength={64}
          />
        </>
      )}
      payload={(data) => ({ name: formText(data, "name"), timezone: formText(data, "timezone") })}
    />
  );
}

export function PositionsDirectory() {
  return (
    <ManagedDirectory
      resource="positions"
      title="Должности"
      editName="должность"
      columns={[{ heading: "Название", cell: (row) => row.name }]}
      fields={(row) => <TextInput required name="name" label="Название" defaultValue={row?.name} maxLength={200} data-autofocus />}
      payload={(data) => ({ name: formText(data, "name") })}
    />
  );
}

function getLabel(choices: Choice[], id: number | null, empty: string) {
  if (id === null) return empty;
  return choices.find((choice) => choice.id === id)?.label ?? `Запись №${id}`;
}

async function loadOfficeAndProfileChoices(signal: AbortSignal) {
  const [offices, profiles] = await Promise.all([
    listAllDirectory("offices", signal),
    listAllDirectory("monitoring-profiles", signal),
  ]);
  return {
    offices: offices.map(({ id, name }) => ({ id, label: name })),
    profiles: profiles.map(({ id, name, is_default }) => ({ id, label: is_default ? `${name} (по умолчанию)` : name })),
  };
}

export function GroupsDirectory() {
  const options = useDirectoryRequest(loadOfficeAndProfileChoices);
  const { offices, profiles } = options.status === "ready" ? options.data : { offices: [], profiles: [] };
  return (
    <ManagedDirectory
      resource="groups"
      title="Группы"
      editName="группу"
      columns={[
        { heading: "Название", cell: (row) => row.name },
        { heading: "Офис", cell: (row) => getLabel(offices, row.office_id, "Без офиса") },
        { heading: "Профиль", cell: (row) => getLabel(profiles, row.profile_id, "По умолчанию") },
      ]}
      canSave={options.status === "ready"}
      fields={(row) => options.status === "ready" ? (
        <>
          <TextInput required name="name" label="Название" defaultValue={row?.name} maxLength={200} data-autofocus />
          <DirectorySelect name="office_id" label="Офис" empty="Без офиса" selected={row?.office_id} choices={offices} />
          <DirectorySelect name="profile_id" label="Профиль мониторинга" empty="По умолчанию" selected={row?.profile_id} choices={profiles} />
        </>
      ) : <DirectoryOptionsStatus options={options} />}
      payload={(data) => ({ name: formText(data, "name"), office_id: formId(data, "office_id"), profile_id: formId(data, "profile_id") })}
    />
  );
}

async function loadEmployeeChoices(signal: AbortSignal) {
  const [groups, offices, positions] = await Promise.all([
    listAllDirectory("groups", signal),
    listAllDirectory("offices", signal),
    listAllDirectory("positions", signal),
  ]);
  const officeNames = new Map(offices.map(({ id, name }) => [id, name]));
  return {
    groups: groups.map(({ id, name, office_id }) => {
      const office = office_id === null ? undefined : officeNames.get(office_id);
      return { id, label: office ? `${name} · ${office}` : name };
    }),
    positions: positions.map(({ id, name }) => ({ id, label: name })),
  };
}

export function EmployeesDirectory() {
  const options = useDirectoryRequest(loadEmployeeChoices);
  const [employee, setEmployee] = useState<Employee>();
  const { groups, positions } = options.status === "ready" ? options.data : { groups: [], positions: [] };
  return (
    <>
      <ManagedDirectory
        resource="employees"
        title="Сотрудники"
        editName="сотрудника"
        searchLabel="Поиск по ФИО"
        columns={[
          { heading: "ФИО", cell: (row) => row.full_name },
          { heading: "Группа", cell: (row) => getLabel(groups, row.group_id, "Без группы") },
          { heading: "Должность", cell: (row) => getLabel(positions, row.position_id, "Без должности") },
          { heading: "Статус", cell: (row) => row.is_dismissed ? "Уволен" : "Работает" },
        ]}
        extraAction={(row) => <Button size="compact-sm" variant="subtle" onClick={() => setEmployee(row)}>Логины Windows</Button>}
        canSave={options.status === "ready"}
        fields={(row) => options.status === "ready" ? (
          <>
            <TextInput required name="full_name" label="ФИО" defaultValue={row?.full_name} maxLength={300} data-autofocus />
            <DirectorySelect name="group_id" label="Группа" empty="Без группы" selected={row?.group_id} choices={groups} />
            <DirectorySelect name="position_id" label="Должность" empty="Без должности" selected={row?.position_id} choices={positions} />
            <Checkbox name="is_dismissed" label="Сотрудник уволен" defaultChecked={row?.is_dismissed} />
          </>
        ) : <DirectoryOptionsStatus options={options} />}
        payload={(data) => ({
          full_name: formText(data, "full_name"), group_id: formId(data, "group_id"),
          position_id: formId(data, "position_id"), is_dismissed: data.has("is_dismissed"),
        })}
      />
      {employee && <EmployeeLoginsDialog employee={employee} onClose={() => setEmployee(undefined)} />}
    </>
  );
}

const STALE_AFTER_MS = 10 * 60 * 1000;

export function ComputersDirectory() {
  const options = useDirectoryRequest(loadOfficeAndProfileChoices);
  const { offices, profiles } = options.status === "ready" ? options.data : { offices: [], profiles: [] };
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <ManagedDirectory
      resource="computers"
      title="Компьютеры"
      editName="компьютер"
      canAdd={false}
      empty="Компьютеры появятся после регистрации Windows-агента."
      columns={[
        { heading: "Компьютер", cell: (row) => (
          <Stack gap={2}>
            <Text size="sm">{row.name}</Text>
            {row.name !== row.hostname && <Text size="xs" c="dimmed">{row.hostname}</Text>}
          </Stack>
        ) },
        { heading: "Офис", cell: (row) => getLabel(offices, row.office_id, "Без офиса") },
        { heading: "Профиль", cell: (row) => getLabel(profiles, row.profile_id, "По умолчанию") },
        { heading: "Версия агента", cell: (row) => row.agent_version ?? "—" },
        { heading: "Последняя связь", cell: (row) => {
          if (row.last_seen_at === null || !Number.isFinite(Date.parse(row.last_seen_at))) return <Text size="sm" c="dimmed">Нет данных</Text>;
          const stale = now - new Date(row.last_seen_at).getTime() > STALE_AFTER_MS;
          return (
            <Stack gap={4} align="start">
              <DateCell timestamp={row.last_seen_at} />
              {stale && <Badge color="red" variant="light">Нет связи более 10 мин</Badge>}
            </Stack>
          );
        } },
      ]}
      canSave={options.status === "ready"}
      fields={(row) => options.status === "ready" ? (
        <>
          <TextInput
            name="name"
            label="Название"
            description="Если пусто, используется имя компьютера в Windows."
            placeholder={row?.hostname}
            defaultValue={row?.name === row?.hostname ? "" : row?.name}
            maxLength={255}
            data-autofocus
          />
          <DirectorySelect name="office_id" label="Офис" empty="Без офиса" selected={row?.office_id} choices={offices} />
          <DirectorySelect name="profile_id" label="Профиль мониторинга" empty="По умолчанию" selected={row?.profile_id} choices={profiles} />
        </>
      ) : <DirectoryOptionsStatus options={options} />}
      payload={(data) => ({ name: formText(data, "name") || null, office_id: formId(data, "office_id"), profile_id: formId(data, "profile_id") })}
    />
  );
}
