import { NextResponse } from "next/server";

import {
  NEPSIS_CSRF_COOKIE,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  NEPSIS_USER_COOKIE,
  cookieOptions,
  csrfCookieOptions,
} from "@/lib/nepsisAuth";
import { requireSameOriginRequest } from "@/lib/requestSecurity";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const sameOriginFailure = requireSameOriginRequest(req);
  if (sameOriginFailure) {
    return sameOriginFailure;
  }

  const response = NextResponse.redirect(new URL("/login", req.url), 303);
  response.cookies.set(NEPSIS_USER_COOKIE, "", cookieOptions(0));
  response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
  response.cookies.set(NEPSIS_CSRF_COOKIE, "", csrfCookieOptions(0));
  return response;
}
