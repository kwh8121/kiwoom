import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// Local Auth config is what the E2E signs in against, and it is the reference
// the hosted project is set to match, so the floor belongs under test.
const config = readFileSync(
  fileURLToPath(new URL("../../../../../supabase/config.toml", import.meta.url)),
  "utf-8",
);

function setting(key: string): string {
  const match = config.match(new RegExp(`^${key}\\s*=\\s*(.+)$`, "m"));
  if (!match) throw new Error(`${key} is not set in supabase/config.toml`);
  return match[1].trim();
}

it("rejects passwords a person could plausibly guess", () => {
  // Supabase's own floor is 6, which permits a password worth brute forcing.
  // Length is what makes a password hard to guess; composition rules mostly
  // push people toward predictable substitutions, so this raises the length
  // and leaves password_requirements empty on purpose.
  expect(Number(setting("minimum_password_length"))).toBeGreaterThanOrEqual(12);
});

it("keeps public signup closed while password login stays available", () => {
  // A longer password only matters while the only accounts are ones the
  // operator created.
  expect(setting("enable_signup")).toBe("false");
});
