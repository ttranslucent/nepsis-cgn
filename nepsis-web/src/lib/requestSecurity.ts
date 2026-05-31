import {
  readCookieFromHeader,
  verifyCsrfToken,
} from "@/lib/nepsisAuth";
import { CSRF_HEADER, NEPSIS_CSRF_COOKIE, NEPSIS_USER_COOKIE } from "@/lib/securityConstants";

export { CSRF_HEADER };

function forbidden(error: string): Response {
  return Response.json({ error }, { status: 403 });
}

function requestOrigin(request: Request): string {
  return new URL(request.url).origin;
}

function originsMatch(origin: string, expectedOrigin: string): boolean {
  if (origin === expectedOrigin) {
    return true;
  }
  if (process.env.NODE_ENV === "production") {
    return false;
  }
  try {
    const actual = new URL(origin);
    const expected = new URL(expectedOrigin);
    const loopbackHosts = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
    return (
      actual.protocol === expected.protocol &&
      actual.port === expected.port &&
      loopbackHosts.has(actual.hostname) &&
      loopbackHosts.has(expected.hostname)
    );
  } catch {
    return false;
  }
}

export function requireSameOriginRequest(request: Request): Response | null {
  const expectedOrigin = requestOrigin(request);
  const origin = request.headers.get("origin");
  if (origin) {
    return originsMatch(origin, expectedOrigin) ? null : forbidden("Same-origin request required");
  }

  const referer = request.headers.get("referer");
  if (referer) {
    try {
      return originsMatch(new URL(referer).origin, expectedOrigin)
        ? null
        : forbidden("Same-origin request required");
    } catch {
      return forbidden("Same-origin request required");
    }
  }

  const fetchSite = request.headers.get("sec-fetch-site")?.toLowerCase();
  if (fetchSite && fetchSite !== "same-origin" && fetchSite !== "none") {
    if (fetchSite === "same-site" && process.env.NODE_ENV !== "production") {
      return null;
    }
    return forbidden("Same-origin request required");
  }

  return null;
}

export function requireCsrfToken(request: Request): Response | null {
  const sameOriginFailure = requireSameOriginRequest(request);
  if (sameOriginFailure) {
    return sameOriginFailure;
  }

  const cookieHeader = request.headers.get("cookie") ?? "";
  const sessionToken = readCookieFromHeader(cookieHeader, NEPSIS_USER_COOKIE);
  if (!sessionToken) {
    return null;
  }

  const cookieToken = readCookieFromHeader(cookieHeader, NEPSIS_CSRF_COOKIE);
  const headerToken = request.headers.get(CSRF_HEADER);
  if (!cookieToken || !headerToken) {
    return forbidden("CSRF token required");
  }
  if (cookieToken !== headerToken || !verifyCsrfToken(sessionToken, headerToken)) {
    return forbidden("Invalid CSRF token");
  }

  return null;
}
