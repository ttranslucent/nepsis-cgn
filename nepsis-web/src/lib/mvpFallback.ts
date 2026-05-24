import { randomUUID } from "crypto";

import fallbackPackets from "@/data/mvpPackets.json";

type MvpCaseId = "jailing" | "clinical";
type FallbackPacket = Record<string, unknown>;
type TokenPair = { sourceToken: string; candidateToken: string };

const PACKETS = fallbackPackets as Record<MvpCaseId, FallbackPacket>;
const TOKEN_PATTERN = "([A-Za-z][A-Za-z0-9_-]{1,})";
const JAILING_TOKEN_PATTERNS = [
  new RegExp(
    `\\bsource[_\\s-]*token\\s*[:=]\\s*${TOKEN_PATTERN}.*?\\bcandidate[_\\s-]*token\\s*[:=]\\s*${TOKEN_PATTERN}`,
    "is",
  ),
  new RegExp(
    `\\bsource\\s+(?:token\\s+)?(?:says|is)\\s+${TOKEN_PATTERN}.*?\\b(?:model|answer|candidate|output)\\s+(?:answered|says|used|is)\\s+${TOKEN_PATTERN}`,
    "is",
  ),
  new RegExp(
    `\\brequired\\s+name\\s+is\\s+${TOKEN_PATTERN}.*?\\bcandidate\\s+answer\\s+collapses\\s+to\\s+(?:the\\s+\\w+\\s+word\\s+)?${TOKEN_PATTERN}`,
    "is",
  ),
  new RegExp(
    `\\bsource(?:[_\\s-]*token)?\\s*(?::|=|says|is)?\\s*${TOKEN_PATTERN}.*?\\b(?:candidate|answer|model|output)(?:[_\\s-]*token)?\\s*(?::|=|answered|says|used|is)?\\s*${TOKEN_PATTERN}`,
    "is",
  ),
];

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

function normalizeDemoToken(value: string): string {
  return value.replace(/^[\s"'`.,;:()[\]{}]+|[\s"'`.,;:()[\]{}]+$/g, "").toUpperCase();
}

function extractJailingTokenPair(inputText: string): TokenPair | null {
  for (const pattern of JAILING_TOKEN_PATTERNS) {
    const match = inputText.match(pattern);
    if (match?.[1] && match[2]) {
      return {
        sourceToken: normalizeDemoToken(match[1]),
        candidateToken: normalizeDemoToken(match[2]),
      };
    }
  }
  return null;
}

function replaceTokenCopy(value: unknown, tokens: TokenPair): unknown {
  if (typeof value === "string") {
    return value
      .replaceAll("JINGALL", "\u0000SOURCE_TOKEN\u0000")
      .replaceAll("JAILING", "\u0000CANDIDATE_TOKEN\u0000")
      .replaceAll("\u0000SOURCE_TOKEN\u0000", tokens.sourceToken)
      .replaceAll("\u0000CANDIDATE_TOKEN\u0000", tokens.candidateToken);
  }
  if (Array.isArray(value)) {
    return value.map((item) => replaceTokenCopy(item, tokens));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, replaceTokenCopy(entry, tokens)]),
    );
  }
  return value;
}

function applyVisitorQuery(packet: FallbackPacket, caseId: MvpCaseId, inputText: string | null): FallbackPacket {
  if (caseId !== "jailing" || !inputText) {
    return packet;
  }
  const tokens = extractJailingTokenPair(inputText);
  if (!tokens || tokens.sourceToken === tokens.candidateToken) {
    return packet;
  }
  return replaceTokenCopy(packet, tokens) as FallbackPacket;
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

  let inputText: string | null;
  try {
    inputText = readInputText(parsed);
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }

  let packet = JSON.parse(JSON.stringify(PACKETS[caseId])) as FallbackPacket;
  packet = applyVisitorQuery(packet, caseId, inputText);
  packet.packet_id = randomUUID();
  packet.created_at = new Date().toISOString();
  packet.fallback_source = "nepsis-web bundled frozen v0.3 packet";
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
