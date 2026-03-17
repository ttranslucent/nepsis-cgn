import { NextResponse } from "next/server";

import { readNepsisUserFromRequest } from "@/lib/nepsisAuth";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const user = readNepsisUserFromRequest(req);
  const allowAnonymous = process.env.NEPSIS_ENGINE_ALLOW_ANON === "true";
  return NextResponse.json({
    authenticated: Boolean(user),
    engineControlAllowed: allowAnonymous || Boolean(user),
    user,
  });
}
