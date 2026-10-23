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

test.each(["/a/..//evil.example", "/%2e%2e//evil.example", "/a/../\\evil.example"])(
  "rejects normalized external redirect path %s",
  (path) => {
    expect(safeNextPath(path)).toBe("/profiles");
  },
);

test("preserves normalized local pathname, query, and hash", () => {
  expect(safeNextPath("/runs/../profiles?tab=all#saved")).toBe("/profiles?tab=all#saved");
});
