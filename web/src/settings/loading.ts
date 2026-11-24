import { useEffect, useState } from "react";
import { directoryErrorMessage } from "./api";

type Result<T> = { status: "ready"; data: T } | { status: "error"; message: string };
type Request<T> = { version: number; revision: number; load: (signal: AbortSignal) => Promise<T> };

export function useDirectoryRequest<T>(load: Request<T>["load"], revision = 0) {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ request: Request<T>; value: Result<T> }>();
  useEffect(() => {
    const controller = new AbortController();
    const request = { version, revision, load };
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setResult({ request, value: { status: "ready", data } });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ request, value: { status: "error", message: directoryErrorMessage(error) } });
        }
      },
    );
    return () => controller.abort();
  }, [load, revision, version]);

  const current = result?.request.version === version && result.request.revision === revision && result.request.load === load
    ? result.value
    : { status: "loading" as const };
  return { ...current, reload: () => setVersion((value) => value + 1) };
}
