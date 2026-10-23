import { beforeEach, expect, test, vi } from "vitest";
const mock = vi.hoisted(() => ({ from: vi.fn(), claims: vi.fn(), redirect: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient: async () => ({ auth: { getClaims: mock.claims }, from: mock.from }) }));
vi.mock("next/navigation", () => ({ redirect: mock.redirect }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
import { createStrategy } from "./actions";
const profileId = "22222222-2222-4222-8222-222222222222";
const strategyId = "11111111-1111-4111-8111-111111111111";
const form = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
};
let inserts: Record<string, unknown>[];
function scriptInsert(result: unknown = { data: { id: strategyId }, error: null }) {
  inserts = [];
  mock.from.mockImplementation(() => {
    const query: Record<string, unknown> = {};
    query.insert = vi.fn((payload: Record<string, unknown>) => { inserts.push(payload); return query; });
    query.select = vi.fn(() => query);
    query.single = vi.fn(() => Promise.resolve(result));
    return query as never;
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  mock.claims.mockResolvedValue({ data: { claims: { sub: "user" } }, error: null });
  mock.redirect.mockImplementation((path: string) => { throw new Error(`REDIRECT:${path}`); });
  scriptInsert();
});
test("creates the strategy under the caller and redirects to it", async () => {
  await expect(createStrategy({}, form({ profileId, name: "  전략  " }))).rejects.toThrow(`REDIRECT:/strategies/${strategyId}`);
  // The name is trimmed and ownership comes from the session, never the form.
  expect(inserts[0]).toEqual({ profile_id: profileId, name: "전략", user_id: "user" });
});
test.each([
  ["a non-uuid profile", { profileId: "nope", name: "전략" }],
  ["a blank name", { profileId, name: "   " }],
  ["a name over 100 characters", { profileId, name: "가".repeat(101) }],
  ["a missing profile field", { name: "전략" }],
])("rejects %s before any insert", async (_label, fields) => {
  expect(await createStrategy({}, form(fields))).toEqual({ error: expect.stringContaining("1~100자") });
  expect(mock.from).not.toHaveBeenCalled();
});
test("accepts the 100 character boundary", async () => {
  await expect(createStrategy({}, form({ profileId, name: "가".repeat(100) }))).rejects.toThrow("REDIRECT:");
});
test("denies an unauthenticated caller before any insert", async () => {
  mock.claims.mockResolvedValue({ data: null, error: null });
  expect(await createStrategy({}, form({ profileId, name: "전략" }))).toEqual({ error: "로그인이 필요합니다." });
  expect(mock.from).not.toHaveBeenCalled();
});
test("reports a rejected insert, which is how RLS denies a foreign profile", async () => {
  scriptInsert({ data: null, error: { message: "new row violates row-level security policy" } });
  expect(await createStrategy({}, form({ profileId, name: "전략" }))).toEqual({ error: expect.stringContaining("프로필을 확인해 주세요") });
  expect(mock.redirect).not.toHaveBeenCalled();
});
