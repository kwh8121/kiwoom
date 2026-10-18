import { beforeEach, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({
  claims: null as object | null,
  refresh: false,
}));
vi.mock("@supabase/ssr", () => ({
  createServerClient: (_url: string, _key: string, options: { cookies: {
    setAll: (cookies: { name: string; value: string; options: { path: string } }[], headers: Record<string, string>) => void;
  } }) => ({
    auth: {
      getClaims: async () => {
        if (auth.refresh) options.cookies.setAll(
          [{ name: "session", value: "test-session", options: { path: "/" } }],
          { "Cache-Control": "private, no-store", Expires: "0", Pragma: "no-cache" },
        );
        return { data: { claims: auth.claims }, error: null };
      },
    },
  }),
}));
import { updateSession } from "./proxy";

beforeEach(() => { auth.claims = null; auth.refresh = false; });

test("unauthenticated protected requests retain their local return path", async () => {
  const response = await updateSession(new NextRequest("http://localhost/profiles?tab=all"));
  expect(response.status).toBe(307);
  expect(response.headers.get("location")).toBe("http://localhost/login?next=%2Fprofiles%3Ftab%3Dall");
});

test("login remains public", async () => {
  const response = await updateSession(new NextRequest("http://localhost/login"));
  expect(response.headers.get("location")).toBeNull();
});

test.each([true, false])("refresh cookies and cache headers survive with claims=%s", async (signedIn) => {
  auth.claims = signedIn ? { sub: "test-user" } : null;
  auth.refresh = true;
  const request = new NextRequest("http://localhost/profiles");
  const response = await updateSession(request);
  expect(response.cookies.get("session")?.value).toBe("test-session");
  expect(request.cookies.get("session")?.value).toBe("test-session");
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect(response.headers.get("expires")).toBe("0");
  expect(response.headers.get("pragma")).toBe("no-cache");
  expect(response.headers.get("location") === null).toBe(signedIn);
});
