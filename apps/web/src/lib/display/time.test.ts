import { expect, it } from "vitest";
import { formatKst } from "./time";
it("formats explicit KST independent of the host timezone", () => {
  expect(formatKst("2026-10-17T04:59:43Z")).toBe("2026-10-17 13:59:43 KST");
  expect(formatKst("2026-10-17T23:59:43Z")).toBe("2026-10-18 08:59:43 KST");
});
