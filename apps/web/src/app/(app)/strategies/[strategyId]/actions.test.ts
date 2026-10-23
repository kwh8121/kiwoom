import { beforeEach, expect, test, vi } from "vitest";
const mock = vi.hoisted(() => ({ rpc: vi.fn(), from: vi.fn(), claims: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient: async () => ({ auth: { getClaims: mock.claims }, from: mock.from, rpc: mock.rpc }) }));
vi.mock("next/navigation", () => ({ redirect: mock.redirect }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
import { cloneStrategy, requestSearchRun, saveVersion } from "./actions";
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
  expect(await cloneStrategy(strategyId)).toEqual({ error: "로그인이 필요합니다." });
  expect(mock.from).not.toHaveBeenCalled(); expect(mock.rpc).not.toHaveBeenCalled();
});

// cloneStrategy inserts the draft first and saves its version second, so each
// early return has to be pinned: a late failure leaves a recoverable draft.
const cloneId = "55555555-5555-4555-8555-555555555555";
const versionId = "66666666-6666-4666-8666-666666666666";
/** Routes each table to a queued result so clone's multi-step flow can be scripted. */
function scriptClone(overrides: { source?: unknown; version?: unknown; insert?: unknown } = {}) {
  const source = overrides.source ?? { data: { id: strategyId, name: "원본 전략", profile_id: profileId, current_version_id: versionId }, error: null };
  const version = overrides.version ?? { data: { definition: valid }, error: null };
  const inserted = overrides.insert ?? { data: { id: cloneId }, error: null };
  const inserts: Record<string, unknown>[] = [];
  mock.from.mockImplementation((table: string) => {
    let inserting = false;
    const query: Record<string, unknown> = {};
    query.select = vi.fn(() => query);
    query.eq = vi.fn(() => query);
    query.insert = vi.fn((payload: Record<string, unknown>) => { inserting = true; inserts.push(payload); return query; });
    // Resolve lazily: whether this is the insert is only known once it is called.
    const result = () => {
      if (table === "strategy_versions") return version;
      if (table === "strategies") return inserting ? inserted : source;
      return { data: [{ id: conditionId, profile_id: profileId, is_active: true }], error: null };
    };
    query.maybeSingle = vi.fn(() => Promise.resolve(result()));
    query.single = vi.fn(() => Promise.resolve(result()));
    query.then = (resolve: (r: unknown) => unknown) => Promise.resolve(result()).then(resolve);
    return query as never;
  });
  return inserts;
}
test("cloneStrategy rejects a non-uuid id before touching the database", async () => {
  expect(await cloneStrategy("not-a-uuid")).toEqual({ error: "전략을 확인해 주세요." });
  expect(mock.from).not.toHaveBeenCalled();
});
test("cloneStrategy requires a saved version", async () => {
  scriptClone({ source: { data: { id: strategyId, name: "초안", profile_id: profileId, current_version_id: null }, error: null } });
  expect(await cloneStrategy(strategyId)).toEqual({ error: "저장된 전략이 필요합니다." });
});
test("cloneStrategy refuses a missing or unreadable source strategy", async () => {
  scriptClone({ source: { data: null, error: null } });
  expect(await cloneStrategy(strategyId)).toEqual({ error: "저장된 전략이 필요합니다." });
});
test("cloneStrategy refuses a stored definition that no longer parses", async () => {
  scriptClone({ version: { data: { definition: { schemaVersion: 1, exchange: "K" } }, error: null } });
  expect(await cloneStrategy(strategyId)).toEqual({ error: "전략 정의를 불러오지 못했습니다." });
});
test("cloneStrategy reports a failed draft insert", async () => {
  scriptClone({ insert: { data: null, error: { message: "boom" } } });
  expect(await cloneStrategy(strategyId)).toEqual({ error: "전략을 복제하지 못했습니다." });
});
test("cloneStrategy copies the definition and redirects to the new strategy", async () => {
  const inserts = scriptClone();
  await expect(cloneStrategy(strategyId)).rejects.toThrow(`REDIRECT:/strategies/${cloneId}`);
  expect(inserts[0]).toEqual({ name: "원본 전략 (복제)", profile_id: profileId, user_id: "user" });
  expect(mock.rpc).toHaveBeenCalledWith("create_strategy_version", { p_strategy_id: cloneId, p_definition: valid });
});
test("cloneStrategy truncates a long name so the clone suffix still fits", async () => {
  const inserts = scriptClone({ source: { data: { id: strategyId, name: "가".repeat(100), profile_id: profileId, current_version_id: versionId }, error: null } });
  await expect(cloneStrategy(strategyId)).rejects.toThrow("REDIRECT:");
  expect(inserts[0].name).toBe(`${"가".repeat(94)} (복제)`);
  expect((inserts[0].name as string).length).toBeLessThanOrEqual(100);
});
test("cloneStrategy leaves a recoverable draft when the version save fails", async () => {
  scriptClone();
  mock.rpc.mockResolvedValue({ data: null, error: { message: "CONDITION_INACTIVE" } });
  const result = await cloneStrategy(strategyId);
  expect(result).toEqual({ error: expect.stringContaining("복제 초안이 생성되었지만") });
  expect(mock.redirect).not.toHaveBeenCalled();
});
