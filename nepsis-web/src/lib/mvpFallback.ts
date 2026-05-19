import { randomUUID } from "crypto";

import fallbackPackets from "@/data/mvpPackets.json";

type MvpCaseId = "jailing" | "clinical";
type FallbackPacket = Record<string, unknown>;

const PACKETS = fallbackPackets as Record<MvpCaseId, FallbackPacket>;

function parseBody(body: string): Record<string, unknown> {
  if (!body.trim()) {
    return {};
  }
  const parsed = JSON.parse(body) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON body must be an object");
  }
  return parsed as Record<string, unknown>;
}

function readCaseId(body: Record<string, unknown>): MvpCaseId {
  const raw = body.case_id ?? body.case ?? "jailing";
  if (raw === "jailing" || raw === "clinical") {
    return raw;
  }
  throw new Error("case_id must be one of: jailing, clinical");
}

function hasCustomInput(body: Record<string, unknown>): boolean {
  return typeof (body.input_text ?? body.inputText) === "string";
}

export function buildBundledMvpFallbackResponse(body: string): Response {
  let parsed: Record<string, unknown>;
  try {
    parsed = parseBody(body);
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  let caseId: MvpCaseId;
  try {
    caseId = readCaseId(parsed);
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }

  if (hasCustomInput(parsed)) {
    return Response.json(
      {
        error: "FastAPI backend required for custom MVP input_text",
        detail: "The public fallback only serves frozen canonical v0.3 demo cases.",
      },
      { status: 503 },
    );
  }

  const packet = JSON.parse(JSON.stringify(PACKETS[caseId])) as FallbackPacket;
  packet.packet_id = randomUUID();
  packet.created_at = new Date().toISOString();
  packet.fallback_source = "nepsis-web bundled frozen v0.3 packet";
  return Response.json(packet);
}
