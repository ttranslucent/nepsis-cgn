import { NextResponse } from "next/server";

import { anonymousEngineControlsAllowed, engineControlOwner } from "@/lib/engineApi";
import {
  NEPSIS_CSRF_COOKIE,
  NEPSIS_USER_COOKIE,
  createCsrfToken,
  csrfCookieOptions,
  readCookieFromHeader,
  verifyCsrfToken,
} from "@/lib/nepsisAuth";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const user = engineControlOwner(req);
  const allowAnonymous = anonymousEngineControlsAllowed();
  const response = NextResponse.json({
    authenticated: Boolean(user),
    engineControlAllowed: allowAnonymous || Boolean(user),
    user,
  });
  if (user) {
    const cookieHeader = req.headers.get("cookie") ?? "";
    const sessionToken = readCookieFromHeader(cookieHeader, NEPSIS_USER_COOKIE);
    const csrfToken = readCookieFromHeader(cookieHeader, NEPSIS_CSRF_COOKIE);
    if (sessionToken && !verifyCsrfToken(sessionToken, csrfToken)) {
      response.cookies.set(NEPSIS_CSRF_COOKIE, createCsrfToken(sessionToken), csrfCookieOptions());
    }
  }
  return response;
}
