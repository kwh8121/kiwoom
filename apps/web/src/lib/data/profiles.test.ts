import { beforeEach, describe, expect, it, vi } from "vitest";
const { createServerClient } = vi.hoisted(() => ({ createServerClient: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createServerClient }));
import { getProfiles } from "./profiles";

type Row = Record<string, unknown>;

// One worker can serve several owners, so its heartbeat row carries every alias
// it polls. The table exposes that whole roster; the view narrows it to the
// caller's own aliases.
function mockProfiles(tables: Record<string, Row[]>) {
  const from = vi.fn((table: string) => {
    const query = {
      select: () => query,
      order: () => query,
      then: (resolve: (value: unknown) => unknown) =>
        Promise.resolve({ data: tables[table] ?? [], error: null }).then(resolve),
    };
    return query;
  });
  createServerClient.mockResolvedValue({ from });
  return from;
}

beforeEach(() => vi.resetAllMocks());

describe("profile worker reachability", () => {
  it("reports only the aliases the caller owns from a shared worker", async () => {
    mockProfiles({
      broker_profiles: [{ id: "p1", alias: "mine", created_at: "2026-10-01T00:00:00Z" }],
      worker_heartbeats: [{ aliases: ["mine", "someone-else"], seen_at: "2026-10-23T00:00:00Z" }],
      my_worker_heartbeats: [{ aliases: ["mine"], seen_at: "2026-10-23T00:00:00Z" }],
      latest_profile_sync_runs: [],
    });

    const { heartbeats } = await getProfiles();

    expect(heartbeats).toEqual([{ aliases: ["mine"], seen_at: "2026-10-23T00:00:00Z" }]);
  });

  // A view cannot declare its columns non-null, so the row type admits nulls the
  // query can never produce. An uninterpretable row is not evidence of a
  // reachable worker, so it is dropped rather than read as a stale timestamp.
  it("drops a heartbeat row with no alias list or timestamp", async () => {
    mockProfiles({
      broker_profiles: [{ id: "p1", alias: "mine", created_at: "2026-10-01T00:00:00Z" }],
      my_worker_heartbeats: [
        { aliases: null, seen_at: "2026-10-23T00:00:00Z" },
        { aliases: ["mine"], seen_at: null },
        { aliases: ["mine"], seen_at: "2026-10-23T00:00:00Z" },
      ],
      latest_profile_sync_runs: [],
    });

    const { heartbeats } = await getProfiles();

    expect(heartbeats).toEqual([{ aliases: ["mine"], seen_at: "2026-10-23T00:00:00Z" }]);
  });
});
