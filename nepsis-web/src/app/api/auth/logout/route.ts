import { NextResponse } from "next/server";

import {
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  NEPSIS_USER_COOKIE,
  cookieOptions,
} from "@/lib/nepsisAuth";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const response = NextResponse.redirect(new URL("/login", req.url), 303);
  response.cookies.set(NEPSIS_USER_COOKIE, "", cookieOptions(0));
  response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
  return response;
}
