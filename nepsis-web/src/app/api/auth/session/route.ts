import { NextResponse } from "next/server";

import { anonymousEngineControlsAllowed, engineControlOwner } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const user = engineControlOwner(req);
  const allowAnonymous = anonymousEngineControlsAllowed();
  return NextResponse.json({
    authenticated: Boolean(user),
    engineControlAllowed: allowAnonymous || Boolean(user),
    user,
  });
}
