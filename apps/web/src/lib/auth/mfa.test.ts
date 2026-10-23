import { beforeEach, expect, test, vi } from "vitest";
const mock = vi.hoisted(() => ({ rpc: vi.fn(), claims: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({
  createServerClient: async () => ({ auth: { getClaims: mock.claims }, rpc: mock.rpc }),
}));
import { secondFactorPending } from "./mfa";

beforeEach(() => vi.resetAllMocks());

// The gate reuses public.mfa_satisfied(), the same function the row policies
// call, so the screens and the data boundary cannot drift apart.
test("a session that has not presented a verified factor is pending", async () => {
  mock.rpc.mockResolvedValue({ data: false, error: null });

  expect(await secondFactorPending()).toBe(true);
  expect(mock.rpc).toHaveBeenCalledWith("mfa_satisfied");
});

test("a session that satisfied the requirement is not pending", async () => {
  mock.rpc.mockResolvedValue({ data: true, error: null });

  expect(await secondFactorPending()).toBe(false);
});

test("an unreadable answer is treated as pending rather than as satisfied", async () => {
  // Failing open here would hand out the screens the policies then refuse to
  // fill, which reads as data loss.
  mock.rpc.mockResolvedValue({ data: null, error: { message: "boom" } });

  expect(await secondFactorPending()).toBe(true);
});
