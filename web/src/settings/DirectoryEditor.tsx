import { Alert, Button, Group, Loader, Modal, Select, Stack } from "@mantine/core";
import { type FormEvent, type ReactNode, useState } from "react";
import { directoryErrorMessage } from "./api";
import { useDirectoryRequest } from "./loading";

export function DirectoryEditor({
  title, onClose, onSave, onSaved, children, submitLabel = "Сохранить", canSubmit = true,
}: {
  title: string;
  onClose: () => void;
  onSave: (data: FormData) => Promise<unknown>;
  onSaved: () => void;
  children: ReactNode;
  submitLabel?: string;
  canSubmit?: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string>();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !canSubmit) return;
    const data = new FormData(event.currentTarget);
    setMessage(undefined);
    setSaving(true);
    try {
      await onSave(data);
      onSaved();
    } catch (error) {
      setMessage(directoryErrorMessage(error));
      setSaving(false);
    }
  }

  return (
    <Modal opened onClose={() => { if (!saving) onClose(); }} title={title} centered closeButtonProps={{ "aria-label": "Закрыть" }}>
      <form onSubmit={submit}>
        <Stack>
          {children}
          {message && <Alert color="red" role="alert">{message}</Alert>}
          <Group justify="end">
            <Button variant="default" onClick={onClose} disabled={saving}>Отмена</Button>
            <Button type="submit" loading={saving} disabled={!canSubmit}>{submitLabel}</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

export interface Choice {
  id: number;
  label: string;
}

export function DirectorySelect({
  name, label, empty, selected, choices, required, onChange,
}: {
  name: string;
  label: string;
  empty: string;
  selected?: number | null;
  choices: Choice[];
  required?: boolean;
  onChange?: (id: number | null) => void;
}) {
  const options = choices.map(({ id, label: optionLabel }) => ({ value: String(id), label: optionLabel }));
  if (selected != null && !choices.some(({ id }) => id === selected)) {
    options.push({ value: String(selected), label: `Запись №${selected}` });
  }
  return (
    <Select
      searchable
      clearable={!required}
      required={required}
      name={name}
      label={label}
      placeholder={empty}
      nothingFoundMessage="Нет подходящих записей"
      data={options}
      limit={50}
      defaultValue={selected == null ? null : String(selected)}
      onChange={(value) => onChange?.(value === null ? null : Number(value))}
    />
  );
}

export function DirectoryOptionsStatus({ options }: { options: ReturnType<typeof useDirectoryRequest<unknown>> }) {
  if (options.status === "loading") return <Group role="status"><Loader size="sm" />Загрузка списка для выбора</Group>;
  return options.status === "error" && (
    <Alert color="red" role="alert">
      <Stack align="start" gap="xs">
        {options.message}
        <Button variant="light" onClick={options.reload}>Повторить</Button>
      </Stack>
    </Alert>
  );
}
