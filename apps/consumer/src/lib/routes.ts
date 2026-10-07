export const LOGIN_PATH = "/login";

export function isPublicPath(pathname: string) {
  return pathname === LOGIN_PATH || pathname.startsWith("/ask/");
}

export function safeNextPath(value: unknown) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  return value;
}
