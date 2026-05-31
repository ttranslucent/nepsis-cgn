import { withCsrfHeader } from "@/lib/csrfClient";

export type OperatorModelMode = "draft_frame" | "interpret_report" | "threshold_review";

export type OperatorFrameDraft = {
  text: string;
  objective_type: string;
  domain: string;
  time_horizon: string;
  key_uncertainty: string;
  constraints_hard: string[];
  constraints_soft: string[];
  red_definition: string;
  blue_goals: string;
};

export type OperatorModelResponse = {
  mode: OperatorModelMode;
  model: string;
  outputText: string;
  frameDraft?: OperatorFrameDraft;
  reportNotes?: string;
  thresholdNote?: string;
};

export async function requestOperatorModel(payload: {
  mode: OperatorModelMode;
  input: string;
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
