import { expect, it } from "vitest";
import { formatKst, kstDate } from "./time";
it("formats explicit KST independent of the host timezone", () => {
  expect(formatKst("2026-10-17T04:59:43Z")).toBe("2026-10-17 13:59:43 KST");
  expect(formatKst("2026-10-17T23:59:43Z")).toBe("2026-10-18 08:59:43 KST");
});

it("resolves the KST calendar date across the UTC day boundary", () => {
  expect(kstDate("2026-10-17T04:59:43Z")).toBe("2026-10-17");
  // 23:59 UTC is already the next morning in Seoul, and the trading day the
  // closure calendar is keyed on is the KST one.
  expect(kstDate("2026-10-17T23:59:43Z")).toBe("2026-10-18");
  expect(kstDate("2026-10-17T15:00:00Z")).toBe("2026-10-18");
  expect(kstDate("2026-10-17T14:59:59Z")).toBe("2026-10-17");
});

it("returns null instead of throwing for a date it cannot read", () => {
  // getRun feeds this a column value. A throw here would turn an unreadable
  // timestamp into a 500 on the run page.
  expect(kstDate(null)).toBeNull();
  expect(kstDate("not a date")).toBeNull();
});
