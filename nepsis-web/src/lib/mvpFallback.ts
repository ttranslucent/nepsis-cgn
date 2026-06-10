import { randomUUID } from "crypto";

import fallbackPackets from "@/data/mvpPackets.json";

type MvpCaseId = "jailing" | "clinical";
type FallbackPacket = Record<string, unknown>;
export type MvpFallbackReason = "backend_unconfigured" | "upstream_non_ok" | "public_fallback_after_proxy_error";

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

function readInputText(body: Record<string, unknown>): string | null {
  const raw = body.input_text ?? body.inputText;
  if (raw === undefined || raw === null) {
    return null;
  }
  if (typeof raw !== "string") {
    throw new Error("input_text must be a string when provided");
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.length > 1200) {
    throw new Error("input_text must be 1200 characters or fewer");
  }
  return trimmed;
}

export function buildBundledMvpFallbackResponse(
  body: string,
  fallbackReason: MvpFallbackReason = "backend_unconfigured",
): Response {
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

  let inputText: string | null;
  try {
    inputText = readInputText(parsed);
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }

  const packet = JSON.parse(JSON.stringify(PACKETS[caseId])) as FallbackPacket;
  packet.packet_id = randomUUID();
  packet.created_at = new Date().toISOString();
  packet.fallback_source = "nepsis-web bundled frozen v0.3 packet";
  packet.fallback_reason = fallbackReason;
  if (inputText) {
    packet.input_text = inputText;
    const finalOutput = packet.final_output as { caveats?: unknown } | undefined;
    if (finalOutput && Array.isArray(finalOutput.caveats)) {
      finalOutput.caveats = [
        ...finalOutput.caveats,
        "Public query mode uses the selected deterministic MVP scaffold; it is not a live model response.",
      ];
    }
  }
  return Response.json(packet);
}
