import { withCsrfHeader } from "@/lib/csrfClient";
import type { OperatorAssistTarget, OperatorModelSuggestion } from "@/lib/operatorModelClient";

export type OperatorGuideDomainAdapter = "general" | "clinical" | "finance" | "legal" | "research";

export type OperatorGuideDiscriminator = {
  rank: number;
  label: string;
  question: string;
  why_it_moves_decision: string;
  basis?: string;
  target_field?: OperatorAssistTarget | "report.input" | "report.contradictions_status" | "report.contradictions_note";
};

export type OperatorGuideVisibleScaffold = {
  current_frame?: string;
  open_constraint?: string;
  next_question?: string;
  red_concern?: string;
  ready_to_lock?: string[];
};

export type OperatorGuideResponse = {
  model: string;
  next_question: string;
  visible_scaffold: OperatorGuideVisibleScaffold;
  packet_delta_preview: Record<string, unknown>;
  proposed_updates: OperatorModelSuggestion[];
  fields_ready_to_lock: string[];
  blocking_uncertainties: string[];
  ranked_discriminators: OperatorGuideDiscriminator[];
};

export async function requestOperatorGuide(payload: {
  user_message: string;
  domain_adapter: OperatorGuideDomainAdapter;
  operator_loop_id: string;
  context?: Record<string, unknown>;
  model?: string;
}): Promise<OperatorGuideResponse> {
  const response = await fetch("/api/operator/guide", {
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
          : "Operator guide request failed.";
    throw new Error(message);
  }
  return data as OperatorGuideResponse;
}
