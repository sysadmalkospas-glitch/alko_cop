import { Button, Group } from "@mantine/core";
import { type ReactNode, useState } from "react";
import { type DirectoryRow, type EditableDirectory, saveDirectory } from "./api";
import { DirectoryEditor } from "./DirectoryEditor";
import { DirectoryTable } from "./DirectoryTable";

type Payload = Parameters<typeof saveDirectory>[2];

interface ManagedDirectoryProps<K extends EditableDirectory> {
  resource: K;
  title: string;
  editName: string;
  searchLabel?: string;
  columns: { heading: string; cell: (row: DirectoryRow<K>) => ReactNode }[];
  fields: (row: DirectoryRow<K> | null) => ReactNode;
  payload: (data: FormData) => Payload;
  canAdd?: boolean;
  canSave?: boolean;
  extraAction?: (row: DirectoryRow<K>) => ReactNode;
  empty?: string;
}

export function ManagedDirectory<K extends EditableDirectory>({
  resource, title, editName, searchLabel = "Поиск по названию", columns, fields, payload,
  canAdd = true, canSave, extraAction, empty,
}: ManagedDirectoryProps<K>) {
  const [selected, setSelected] = useState<DirectoryRow<K> | null>();
  const [revision, setRevision] = useState(0);

  return (
    <>
      <DirectoryTable
        resource={resource}
        title={title}
        searchLabel={searchLabel}
        columns={columns}
        rowKey={(row) => row.id}
        actions={(row) => (
          <Group gap="xs" wrap="nowrap">
            <Button size="compact-sm" variant="subtle" onClick={() => setSelected(row)}>Изменить</Button>
            {extraAction?.(row)}
          </Group>
        )}
        add={canAdd ? () => setSelected(null) : undefined}
        revision={revision}
        empty={empty}
      />
      {selected !== undefined && (
        <DirectoryEditor
          title={selected === null ? `Добавить ${editName}` : `Изменить ${editName}`}
          onClose={() => setSelected(undefined)}
          canSubmit={canSave}
          onSave={(data) => saveDirectory(resource, selected?.id, payload(data))}
          onSaved={() => {
            setSelected(undefined);
            setRevision((value) => value + 1);
          }}
        >
          {fields(selected)}
        </DirectoryEditor>
      )}
    </>
  );
}
