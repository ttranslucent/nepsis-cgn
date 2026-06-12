import type { EngineAssistDisposition } from "@/lib/engineClient";
import type { OperatorAssistTarget, OperatorModelSuggestion } from "@/lib/operatorModelClient";

export type AssistReviewStatus = "draft" | "accepted" | "edited" | "rejected";

export type AssistReview = OperatorModelSuggestion & {
  uiStatus: AssistReviewStatus;
  createdAt: string;
  editedValue?: string;
  model: string;
};

export const FRAME_ASSIST_TARGETS = new Set<OperatorAssistTarget>([
  "frame.text",
  "frame.key_uncertainty",
  "frame.constraints_hard",
  "frame.constraints_soft",
  "frame.red_definition",
  "frame.blue_goals",
]);

export function canonicalFieldText(value: string | string[]): string {
  return Array.isArray(value) ? value.join("\n") : value;
}

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function boundedAssistText(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) : value;
}

export function targetLabel(target: OperatorAssistTarget): string {
  const labels: Record<OperatorAssistTarget, string> = {
    "frame.text": "Frame question",
    "frame.key_uncertainty": "Key uncertainty",
    "frame.constraints_hard": "Hard constraints",
    "frame.constraints_soft": "Soft constraints",
    "frame.red_definition": "RED channel definition",
    "frame.blue_goals": "BLUE channel goals",
    "threshold.hold_reason": "Hold rationale",
    "next_frame.text": "Next frame text",
  };
  return labels[target];
}

export function readRationaleSegment(rationale: unknown, label: string): string {
  if (typeof rationale !== "string") return "";
  const match = rationale.match(new RegExp(`(?:^|\\|\\s*)${label}:\\s*([^|]*)`));
  return match ? match[1].trim() : "";
}

export function assistTargetTextFromFramePayload(
  target: OperatorAssistTarget,
  frame: Record<string, unknown>,
): string | null {
  if (target === "frame.text") return typeof frame.text === "string" ? frame.text : null;
  if (target === "frame.constraints_hard") {
    return Array.isArray(frame.constraints_hard) ? frame.constraints_hard.join("\n") : null;
  }
  if (target === "frame.constraints_soft") {
    return Array.isArray(frame.constraints_soft) ? frame.constraints_soft.join("\n") : null;
  }
  if (target === "frame.key_uncertainty") return readRationaleSegment(frame.rationale_for_change, "Uncertainty");
  if (target === "frame.red_definition") return readRationaleSegment(frame.rationale_for_change, "Red channel");
  if (target === "frame.blue_goals") return readRationaleSegment(frame.rationale_for_change, "Blue channel");
  return null;
}

export async function buildAssistDispositions(
  reviews: AssistReview[],
  currentFieldText: (target: OperatorAssistTarget) => string | null,
): Promise<EngineAssistDisposition[]> {
  const out: EngineAssistDisposition[] = [];
  for (const review of reviews) {
    if (review.uiStatus === "draft") continue;
    const proposedHash = await sha256Hex(canonicalFieldText(review.proposedValue));
    const model = boundedAssistText(review.model, 120);
    const summary = boundedAssistText(review.rationale || review.title, 1000);
    if (review.uiStatus === "rejected") {
      out.push({
        target: review.target,
        source: "model_suggestion",
        model,
        disposition: "rejected",
        proposed_value_hash: proposedHash,
        summary,
      });
      continue;
    }
    const current = currentFieldText(review.target);
    if (current === null) continue;
    const finalHash = await sha256Hex(current);
    out.push({
      target: review.target,
      source: "model_suggestion",
      model,
      disposition: finalHash === proposedHash ? "accepted" : "edited",
      proposed_value_hash: proposedHash,
      final_value_hash: finalHash,
      summary,
    });
  }
  if (out.length > 16) {
    throw new Error("Resolve at most 16 model suggestions before this packet transition.");
  }
  return out;
}
