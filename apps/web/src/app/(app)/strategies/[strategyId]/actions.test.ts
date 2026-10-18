import { beforeEach, expect, test, vi } from "vitest";
const mock = vi.hoisted(() => ({ rpc: vi.fn(), from: vi.fn(), claims: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient: async () => ({ auth: { getClaims: mock.claims }, from: mock.from, rpc: mock.rpc }) }));
vi.mock("next/navigation", () => ({ redirect: mock.redirect }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
import { requestSearchRun, saveVersion } from "./actions";
const strategyId = "11111111-1111-4111-8111-111111111111";
const profileId = "22222222-2222-4222-8222-222222222222";
const conditionId = "33333333-3333-4333-8333-333333333333";
const key = "44444444-4444-4444-8444-444444444444";
const valid = { schemaVersion: 1 as const, profileId, exchange: "K" as const, expr: { type: "condition" as const, conditionId } };
beforeEach(() => {
  vi.clearAllMocks();
  mock.claims.mockResolvedValue({ data: { claims: { sub: "user" } }, error: null });
  mock.from.mockImplementation((table: string) => {
    const result = table === "strategies" ? { data: { id: strategyId, profile_id: profileId }, error: null } : { data: [{ id: conditionId, profile_id: profileId, is_active: true }], error: null };
    const query = { select: vi.fn(), eq: vi.fn(), maybeSingle: vi.fn().mockResolvedValue(result), then: (resolve: (r: unknown) => unknown) => Promise.resolve(result).then(resolve) };
    query.select.mockReturnValue(query); query.eq.mockReturnValue(query); return query;
  });
  mock.rpc.mockResolvedValue({ data: { version: 1, id: "run-id" }, error: null });
  mock.redirect.mockImplementation((path: string) => { throw new Error(`REDIRECT:${path}`); });
});
test("saveVersion rejects invalid definition without calling rpc", async () => {
  expect(await saveVersion(strategyId, { ...valid, expr: { type: "and", children: [] } })).toEqual({ ok: false, issues: ["TOO_FEW_CHILDREN"] });
  expect(mock.rpc).not.toHaveBeenCalled();
});
test("saveVersion maps CONDITION_INACTIVE", async () => {
  mock.rpc.mockResolvedValue({ data: null, error: { message: "CONDITION_INACTIVE" } });
  expect(await saveVersion(strategyId, valid)).toEqual({ ok: false, error: expect.stringContaining("다시 저장") });
});
test("requestSearchRun maps PROFILE_BUSY", async () => {
  mock.rpc.mockResolvedValue({ data: null, error: { message: "PROFILE_BUSY" } });
  expect(await requestSearchRun(strategyId, key)).toEqual({ error: expect.stringContaining("실행 중") });
});
test("saveVersion uses typed composite RPC result", async () => {
  expect(await saveVersion(strategyId, valid)).toEqual({ ok: true, version: 1 });
  expect(mock.rpc).toHaveBeenCalledWith("create_strategy_version", { p_strategy_id: strategyId, p_definition: valid });
});
test("saveVersion rejects profile mismatch before rpc", async () => {
  expect(await saveVersion(strategyId, { ...valid, profileId: key })).toEqual({ ok: false, issues: ["PROFILE_MISMATCH"] });
  expect(mock.rpc).not.toHaveBeenCalled();
});
test("requestSearchRun preserves client idempotency key and redirects", async () => {
  await expect(requestSearchRun(strategyId, key)).rejects.toThrow("REDIRECT:/runs/run-id");
  expect(mock.rpc).toHaveBeenCalledWith("request_run", { p_kind: "search", p_profile_id: profileId, p_strategy_id: strategyId, p_idempotency_key: key });
});
test("actions deny unauthenticated calls before data access", async () => {
  mock.claims.mockResolvedValue({ data: null, error: null });
  expect(await saveVersion(strategyId, valid)).toEqual({ ok: false, error: "로그인이 필요합니다." });
  expect(await requestSearchRun(strategyId, key)).toEqual({ error: "로그인이 필요합니다." });
  expect(mock.from).not.toHaveBeenCalled(); expect(mock.rpc).not.toHaveBeenCalled();
});
