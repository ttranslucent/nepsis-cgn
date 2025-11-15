import crypto from "crypto";
import { NextResponse } from "next/server";
import { codes } from "../request-code/route";

export async function POST(req: Request) {
  const { email, code } = await req.json();

  if (!email || !code) {
    return NextResponse.json({ error: "Email and code required" }, { status: 400 });
  }

  const normalizedEmail = email.toLowerCase().trim();
  const entry = codes.get(normalizedEmail);
  if (!entry || Date.now() > entry.expiresAt) {
    return NextResponse.json({ error: "Code expired or not found" }, { status: 400 });
  }

  const hash = crypto.createHash("sha256").update(code).digest("hex");
  if (hash !== entry.hash) {
    return NextResponse.json({ error: "Invalid code" }, { status: 400 });
  }

  codes.delete(normalizedEmail);

  const res = NextResponse.json({ ok: true });
  res.cookies.set("nepsis_user", normalizedEmail, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });

  return res;
}
