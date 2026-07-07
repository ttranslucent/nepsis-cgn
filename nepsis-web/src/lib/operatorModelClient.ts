import { withCsrfHeader } from "@/lib/csrfClient";
import type { OperatorProposalReceipt } from "@/lib/operatorProposalReceipt";

export type OperatorAssistTarget =
  | "frame.text"
  | "frame.key_uncertainty"
  | "frame.constraints_hard"
  | "frame.constraints_soft"
  | "frame.red_definition"
  | "frame.blue_goals"
  | "threshold.hold_reason"
  | "next_frame.text";

export type OperatorModelMode = "suggest_field" | "review_completion";

export type OperatorModelSuggestion = {
  id: string;
  patch_id?: string;
  target: OperatorAssistTarget;
  title: string;
  proposedValue: string | string[];
  proposedValueHash: string;
  proposalReceipt: OperatorProposalReceipt;
  rationale: string;
  riskNote: string;
  consequenceLevel?: "low" | "high";
  confirmationPrompt?: string;
  requiresEchoConfirmation?: boolean;
};

export type OperatorModelResponse = {
  mode: OperatorModelMode;
  model: string;
  outputText: string;
  suggestions: OperatorModelSuggestion[];
};

export async function requestOperatorModel(payload: {
  mode: OperatorModelMode;
  target?: OperatorAssistTarget;
  input: string;
  operator_loop_id: string;
  context?: Record<string, unknown>;
  model?: string;
}): Promise<OperatorModelResponse> {
  const response = await fetch("/api/operator/model", {
    method: "POST",
    headers: withCsrfHeader({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const message =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : "Operator model request failed.";
    throw new Error(message);
  }
  return data as OperatorModelResponse;
}
