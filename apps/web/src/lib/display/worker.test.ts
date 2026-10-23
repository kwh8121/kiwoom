import { describe, expect, it } from "vitest";
import { workerStatus } from "./worker";

const NOW = new Date("2026-10-17T05:00:00Z");
const iso = (seconds: number) => new Date(NOW.getTime() + seconds * 1000).toISOString();
describe("workerStatus", () => {
  it.each([[-10, "online"], [-45, "online"], [-45.001, "stale"], [-60, "stale"]])("classifies heartbeat at %s seconds", (seconds, expected) => {
    expect(workerStatus([{ aliases: ["kiwoom-demo"], seen_at: iso(Number(seconds)) }], "kiwoom-demo", NOW)).toBe(expected);
  });
  it("ignores other aliases and reports missing workers", () => {
    expect(workerStatus([{ aliases: ["other"], seen_at: iso(-5) }], "kiwoom-demo", NOW)).toBe("not_serving");
    expect(workerStatus([], "kiwoom-demo", NOW)).toBe("not_serving");
  });
  it("prefers any fresh matching worker over older workers", () => {
    expect(workerStatus([{ aliases: ["kiwoom-demo"], seen_at: iso(-60) }, { aliases: ["other", "kiwoom-demo"], seen_at: iso(-2) }], "kiwoom-demo", NOW)).toBe("online");
  });
});
