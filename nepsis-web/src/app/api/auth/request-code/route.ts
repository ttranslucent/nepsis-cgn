import crypto from "crypto";
import { NextResponse } from "next/server";

const codes = new Map<string, { hash: string; expiresAt: number }>();

export async function POST(req: Request) {
  const { email } = await req.json();
  if (!email || typeof email !== "string") {
    return NextResponse.json({ error: "Email required" }, { status: 400 });
  }

  const normalizedEmail = email.toLowerCase().trim();
  const code = Math.floor(100000 + Math.random() * 900000).toString();
  const hash = crypto.createHash("sha256").update(code).digest("hex");
  const expiresAt = Date.now() + 10 * 60 * 1000;

  codes.set(normalizedEmail, { hash, expiresAt });
  console.log(`Nepsis login code for ${normalizedEmail}: ${code}`);

  return NextResponse.json({ ok: true });
}

export { codes };
