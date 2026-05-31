import { CSRF_HEADER, NEPSIS_CSRF_COOKIE } from "@/lib/securityConstants";

function csrfTokenFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${NEPSIS_CSRF_COOKIE}=`;
  const match = document.cookie
    .split("; ")
    .find((segment) => segment.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

export function withCsrfHeader(input?: HeadersInit): Headers {
  const headers = new Headers(input);
  const token = csrfTokenFromCookie();
  if (token && !headers.has(CSRF_HEADER)) {
    headers.set(CSRF_HEADER, token);
  }
  return headers;
}
