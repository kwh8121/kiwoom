import type { NextConfig } from "next";

// Directives that do not govern how scripts and styles load. Tightening
// script-src needs a per-request nonce, which has to be threaded through the
// request headers the Supabase SSR cookie callback rebuilds in the auth proxy;
// that is a separate change, and getting it wrong breaks session refresh.
// These four need no nonce and close the framing, form target, base URL and
// plugin vectors on their own.
const contentSecurityPolicy = [
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

// The app reads no camera, microphone or location, so say so rather than
// relying on a future reviewer noticing that it should not.
const permissionsPolicy = [
  "camera=()",
  "microphone=()",
  "geolocation=()",
  "payment=()",
  "usb=()",
].join(", ");

const nextConfig: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      {
        // Every path, so no route can be served without these.
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Redundant with frame-ancestors for current browsers, kept for
          // older ones that only understand this header.
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: permissionsPolicy },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
