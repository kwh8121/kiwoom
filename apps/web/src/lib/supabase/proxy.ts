import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isPublicPath } from "@/lib/auth/paths";
import type { Database } from "./database.types";

export async function updateSession(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });
  const authHeaders = new Headers();
  const supabase = createServerClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(cookiesToSet, headers) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          const previousCookies = response.cookies.getAll();
          response = NextResponse.next({ request });
          previousCookies.forEach((cookie) => response.cookies.set(cookie));
          cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
          Object.entries(headers).forEach(([name, value]) => authHeaders.set(name, value));
          authHeaders.forEach((value, name) => response.headers.set(name, value));
        },
      },
    },
  );
  const { data, error } = await supabase.auth.getClaims();
  if ((error || !data?.claims) && /^\/runs\/[^/]+\/csv$/.test(request.nextUrl.pathname)) {
    const notFound = new NextResponse(null, { status: 404 });
    response.cookies.getAll().forEach((cookie) => notFound.cookies.set(cookie));
    authHeaders.forEach((value, name) => notFound.headers.set(name, value));
    notFound.headers.set("Cache-Control", "private, no-store");
    return notFound;
  }
  if ((error || !data?.claims) && !isPublicPath(request.nextUrl.pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    url.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    const redirect = NextResponse.redirect(url);
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
    authHeaders.forEach((value, name) => redirect.headers.set(name, value));
    return redirect;
  }
  return response;
}
