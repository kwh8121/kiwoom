import { beforeEach, expect, test, vi } from "vitest";
const mock = vi.hoisted(() => ({ from: vi.fn(), claims: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient: async () => ({ auth: { getClaims: mock.claims }, from: mock.from }) }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
import { createProfile } from "./actions";

const form = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
};
function scriptInsert(error: { code: string; message: string } | null) {
  mock.from.mockImplementation(() => ({ insert: vi.fn(() => Promise.resolve({ error })) }) as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.claims.mockResolvedValue({ data: { claims: { sub: "user" } }, error: null });
});

// An alias selects the worker's local broker credentials, so it must be
// registered to the account by an operator before a profile can use it. These
// two failures need different instructions: one is an operator step the user
// cannot perform, the other is a name already in use.
test("an unregistered alias says the alias needs operator registration", async () => {
  scriptInsert({ code: "42501", message: "new row violates row-level security policy" });

  const state = await createProfile({}, form({ alias: "unregistered", mode: "demo", display_name: "" }));

  expect(state.error).toContain("등록");
  expect(state.error).not.toContain("중복");
});

test("a taken alias says the alias is already in use", async () => {
  scriptInsert({ code: "23505", message: "duplicate key value violates unique constraint" });

  const state = await createProfile({}, form({ alias: "taken", mode: "demo", display_name: "" }));

  expect(state.error).toContain("사용 중");
});

test("a registered and free alias creates the profile", async () => {
  scriptInsert(null);

  const state = await createProfile({}, form({ alias: "mine", mode: "demo", display_name: "운영" }));

  expect(state).toEqual({ success: "프로필을 등록했습니다." });
});
