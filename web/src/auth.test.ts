import assert from "node:assert/strict";
import { test } from "node:test";
import { AuthError, cabinetFetch, onSessionExpired, signIn } from "./auth.ts";

test("only a current cabinet request with an expired session triggers sign-in", async (t) => {
  let expire = 0;
  const unsubscribe = onSessionExpired(() => { expire += 1; });
  t.after(unsubscribe);

  const fetchMock = t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  await assert.rejects(signIn("test", "bad password"), (error) => error instanceof AuthError && error.status === 401);
  assert.equal(expire, 0);

  await Promise.all([cabinetFetch("/api/v1/offices"), cabinetFetch("/api/v1/employees")]);
  assert.equal(expire, 1);

  const controller = new AbortController();
  controller.abort();
  await cabinetFetch("/api/v1/offices", { signal: controller.signal });
  assert.equal(expire, 1);

  let finishOldRequest!: (response: Response) => void;
  const oldResponse = new Promise<Response>((resolve) => { finishOldRequest = resolve; });
  fetchMock.mock.mockImplementationOnce(() => oldResponse);
  const oldRequest = cabinetFetch("/api/v1/offices");
  fetchMock.mock.mockImplementationOnce(async () => Response.json({ id: 1, login: "test", role: "admin" }));
  await signIn("test", "new password");
  finishOldRequest(new Response(null, { status: 401 }));
  await oldRequest;
  assert.equal(expire, 1);
});
