export function isPublicPath(pathname: string): boolean {
  return pathname === "/login";
}

export function safeNextPath(path: string | undefined): string {
  if (!path?.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
    return "/profiles";
  }
  const url = new URL(path, "http://app.local");
  const normalized = `${url.pathname}${url.search}${url.hash}`;
  if (url.origin !== "http://app.local" || normalized.startsWith("//") || url.pathname === "/login" || url.pathname === "/") {
    return "/profiles";
  }
  return normalized;
}
