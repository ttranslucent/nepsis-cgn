import { type ProtoState } from "@/lib/protoPuzzle";

const TILE_BAG = "jingall";

function letterCounts(value: string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const char of value.toLowerCase()) {
    if (!/[a-z]/.test(char)) continue;
    counts[char] = (counts[char] || 0) + 1;
  }
  return counts;
}

const bagCounts = letterCounts(TILE_BAG);

function matchesTileBagExactly(candidate: string): boolean {
  const candidateCounts = letterCounts(candidate);
  const keys = new Set([...Object.keys(candidateCounts), ...Object.keys(bagCounts)]);
  for (const key of keys) {
    if ((candidateCounts[key] || 0) !== (bagCounts[key] || 0)) {
      return false;
    }
  }
  return true;
}

export function letterDelta(candidate: string): { extra: string[]; missing: string[] } {
  const candidateCounts = letterCounts(candidate);
  const keys = new Set([...Object.keys(candidateCounts), ...Object.keys(bagCounts)]);
  const extra: string[] = [];
  const missing: string[] = [];

  for (const key of keys) {
    const want = bagCounts[key] || 0;
    const got = candidateCounts[key] || 0;
    if (got > want) {
      extra.push(`${key.toUpperCase()}×${got - want}`);
    } else if (got < want) {
      missing.push(`${key.toUpperCase()}×${want - got}`);
    }
  }

  return { extra, missing };
}

export function extractJingallCandidate(output: string): string | null {
  const lower = output.toLowerCase();
  if (lower.includes("jingall")) return "jingall";
  if (lower.includes("jailing")) return "jailing";
  return null;
}

export function buildJingallPuzzleStateFromOutput(output: string): ProtoState {
  const candidate = extractJingallCandidate(output);

  const name_correct =
    candidate !== null && matchesTileBagExactly(candidate) && candidate.toLowerCase() === "jingall";
  const story_consistent = candidate !== null;
  const words = output.split(/\s+/).filter(Boolean).length;
  const explanation_quality = Math.min(1, words / 80);

  return {
    name_correct,
    story_consistent,
    explanation_quality,
  };
}

export function buildUtf8StateFromOutput(output: string): ProtoState {
  const controlChars = /[\u0000-\u0008\u000B-\u000C\u000E-\u001F\u007F]/;
  const zeroWidth = /[\u200B-\u200F\uFEFF]/;

  const has_invisible_chars = controlChars.test(output) || zeroWidth.test(output);
  const format_ok = !has_invisible_chars;

  return {
    valid_utf8: true,
    has_invisible_chars,
    format_ok,
  };
}

export function buildProtoStateFromOutput(packId: string, output: string): ProtoState {
  switch (packId) {
    case "jailing_jingall":
      return buildJingallPuzzleStateFromOutput(output);
    case "utf8_clean":
      return buildUtf8StateFromOutput(output);
    default:
      throw new Error(`Pack ${packId} is not supported in Playground`);
  }
}
