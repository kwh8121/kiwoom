import { expect, test } from "vitest";
import { isPublicPath, safeNextPath } from "@/lib/auth/paths";

test("only /login is public", () => {
  expect(["/login", "/profiles", "/runs/abc", "/"].map(isPublicPath)).toEqual([true, false, false, false]);
});

test("login return paths stay within the application", () => {
  for (const path of [undefined, "https://example.com", "//example.com", "/\\example.com", "/login", "/login?next=/profiles", "/"]) {
    expect(safeNextPath(path)).toBe("/profiles");
  }
  expect(safeNextPath("/runs/abc?tab=results")).toBe("/runs/abc?tab=results");
});
