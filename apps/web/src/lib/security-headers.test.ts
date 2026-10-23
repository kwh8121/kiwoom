import { describe, expect, it } from "vitest";
import nextConfig from "../../next.config";

async function headerMap() {
  const rules = await nextConfig.headers!();
  // One rule covers every path; a header that only some routes carry is a gap.
  expect(rules).toHaveLength(1);
  expect(rules[0].source).toBe("/:path*");
  return new Map(rules[0].headers.map(({ key, value }) => [key.toLowerCase(), value]));
}

describe("response security headers", () => {
  it("refuses to be framed and pins where forms and base URLs may point", async () => {
    const csp = (await headerMap()).get("content-security-policy")!;

    // These directives do not affect how scripts or styles load, so they hold
    // regardless of whether a nonce is wired through the auth proxy.
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toContain("object-src 'none'");
  });

  it("stops content-type sniffing and cross-origin referrer leakage", async () => {
    const headers = await headerMap();

    expect(headers.get("x-content-type-options")).toBe("nosniff");
    expect(headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
    expect(headers.get("x-frame-options")).toBe("DENY");
  });

  it("denies device access the app never asks for", async () => {
    const policy = (await headerMap()).get("permissions-policy")!;

    for (const feature of ["camera", "microphone", "geolocation"]) {
      expect(policy).toContain(`${feature}=()`);
    }
  });

  it("requires HTTPS for a year including subdomains", async () => {
    const hsts = (await headerMap()).get("strict-transport-security")!;

    expect(hsts).toContain("max-age=31536000");
    expect(hsts).toContain("includeSubDomains");
  });
});
