import { beforeEach, describe, expect, it, vi } from "vitest";
const { createServerClient } = vi.hoisted(() => ({ createServerClient: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient }));
import { getRuns } from "./runs";

type Row = { id: string; [key: string]: unknown };
function mockHistory(runs: Row[], metadata: Record<string, Row[]> = {}) {
  let runsLoaded = false;
  const filters: { table: string; column: string; ids: string[] }[] = [];
  const from = vi.fn((table: string) => {
    let ids: string[] | undefined;
    let limit = 1000;
    const query = {
      select: () => query,
      order: vi.fn().mockReturnThis(),
      limit: (count: number) => { limit = count; return query; },
      in: (column: string, values: string[]) => {
        expect(runsLoaded).toBe(true);
        filters.push({ table, column, ids: values });
        ids = values;
        return query;
      },
      then: (resolve: (value: unknown) => unknown) => {
        if (table === "runs") runsLoaded = true;
        const rows = table === "runs" ? runs : metadata[table] ?? [];
        const selectedIds = ids;
        const filtered = selectedIds ? rows.filter(row => selectedIds.includes(row.id)) : rows;
        return Promise.resolve({ data: filtered.slice(0, limit), error: null }).then(resolve);
      },
    };
    query.order.mockReturnValue(query);
    return query;
  });
  createServerClient.mockResolvedValue({ from });
  return { from, filters };
}

beforeEach(() => vi.resetAllMocks());
describe("recent run history metadata", () => {
  it("loads referenced metadata beyond unrelated 1000-row caps using distinct IDs", async () => {
    const run = { id: "run", strategy_id: "recent-strategy", strategy_version_id: "recent-version", profile_id: "recent-profile" };
    const unrelated = Array.from({ length: 1001 }, (_, i) => ({ id: `unrelated-${i}` }));
    const { filters } = mockHistory([run, { ...run, id: "second-run" }], {
      strategies: [...unrelated, { id: "recent-strategy", name: "최근 전략" }],
      strategy_versions: [...unrelated, { id: "recent-version", version: 1002 }],
      broker_profiles: [...unrelated, { id: "recent-profile", alias: "demo" }],
    });
    const result = await getRuns();
    expect(result.strategies).toEqual([{ id: "recent-strategy", name: "최근 전략" }]);
    expect(result.versions).toEqual([{ id: "recent-version", version: 1002 }]);
    expect(result.profiles).toEqual([{ id: "recent-profile", alias: "demo" }]);
    expect(filters).toEqual([
      { table: "strategies", column: "id", ids: ["recent-strategy"] },
      { table: "strategy_versions", column: "id", ids: ["recent-version"] },
      { table: "broker_profiles", column: "id", ids: ["recent-profile"] },
    ]);
  });
  it("keeps only the latest fifty and never queries metadata for an empty history", async () => {
    const populated = mockHistory(Array.from({ length: 60 }, (_, i) => ({ id: String(i), strategy_id: null, strategy_version_id: null, profile_id: "profile" })), { broker_profiles: [{ id: "profile" }] });
    expect((await getRuns()).runs).toHaveLength(50);
    expect(populated.filters).toEqual([{ table: "broker_profiles", column: "id", ids: ["profile"] }]);
    const empty = mockHistory([]);
    expect(await getRuns()).toEqual({ runs: [], strategies: [], versions: [], profiles: [] });
    expect(empty.from.mock.calls).toEqual([["runs"]]);
  });
});
