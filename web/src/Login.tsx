import { Alert, Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useState } from "react";
import type { FormEvent } from "react";
import { AuthError, signIn } from "./auth";
import type { CabinetUser } from "./auth";

function loginError(error: unknown): string {
  if (error instanceof AuthError) {
    if (error.status === 401) return "Проверьте логин и пароль.";
    if (error.status === 422) return "Проверьте формат логина.";
    if (error.status === 429) return "Слишком много попыток входа. Повторите позже.";
  }
  return "Не удалось войти. Повторите попытку.";
}

export function Login({ onLogin }: { onLogin: (user: CabinetUser) => void }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    const data = new FormData(event.currentTarget);
    setError("");
    setSubmitting(true);
    try {
      onLogin(await signIn(String(data.get("login")), String(data.get("password"))));
    } catch (error) {
      setError(loginError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <Paper className="login-card" radius="lg" p="xl" withBorder>
        <Text fw={750} c="pine.8" mb="xl">AlkoCop</Text>
        <Title order={1} className="login-heading">Вход в кабинет</Title>
        <form onSubmit={submit}>
          <Stack mt="xl" gap="md">
            <TextInput
              name="login"
              label="Логин"
              autoComplete="username"
              maxLength={128}
              required
            />
            <PasswordInput
              name="password"
              label="Пароль"
              autoComplete="current-password"
              maxLength={1024}
              visibilityToggleButtonProps={{ "aria-label": "Показать или скрыть пароль" }}
              required
            />
            {error && <Alert color="red" role="alert">{error}</Alert>}
            <Button type="submit" loading={submitting} mt="xs">Войти</Button>
          </Stack>
        </form>
      </Paper>
    </main>
  );
}
