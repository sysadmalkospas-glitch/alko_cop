import { Button, Center, Loader, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { Cabinet } from "./Cabinet";
import { Login } from "./Login";
import { getSession } from "./auth";
import type { CabinetUser } from "./auth";

type Session =
  | { status: "checking" | "unavailable" | "signed-out" }
  | { status: "signed-in"; user: CabinetUser };

export function App() {
  const [session, setSession] = useState<Session>({ status: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getSession(controller.signal).then(
      (user) => {
        if (controller.signal.aborted) return;
        setSession(user ? { status: "signed-in", user } : { status: "signed-out" });
      },
      () => {
        if (!controller.signal.aborted) setSession({ status: "unavailable" });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setSession({ status: "checking" });
    setAttempt((current) => current + 1);
  }

  if (session.status === "signed-in") {
    return <Cabinet user={session.user} onLogout={() => setSession({ status: "signed-out" })} />;
  }
  if (session.status === "signed-out") {
    return <Login onLogin={(user) => setSession({ status: "signed-in", user })} />;
  }
  return (
    <Center component="main" className="session-status">
      {session.status === "checking" ? (
        <Stack align="center" role="status">
          <Loader size="sm" />
          <Text>Проверяем сеанс</Text>
        </Stack>
      ) : (
        <Stack align="center">
          <Text role="alert">Не удалось подключиться к серверу.</Text>
          <Button onClick={retry}>Повторить</Button>
        </Stack>
      )}
    </Center>
  );
}
