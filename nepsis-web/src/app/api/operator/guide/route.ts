import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";

import { requireEngineControlAuth } from "@/lib/engineApi";
import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
  hasConfiguredOpenAiKey,
} from "@/lib/openaiClient";
import {
  hasConfiguredProposalReceiptSecret,
  sha256Hex,
  signOperatorProposalReceipt,
} from "@/lib/operatorProposalReceipt";
import { modelRoutesEnabled } from "@/lib/publicMode";
import { requireCsrfToken } from "@/lib/requestSecurity";

export const runtime = "nodejs";

const DOMAIN_ADAPTERS = new Set(["general", "clinical", "finance", "legal", "research"]);
const PATCH_TARGETS = new Set([
  "frame.text",
  "frame.key_uncertainty",
  "frame.constraints_hard",
  "frame.constraints_soft",
  "frame.red_definition",
  "frame.blue_goals",
]);
const DISCRIMINATOR_TARGET_FIELDS = new Set([
  ...PATCH_TARGETS,
  "report.input",
  "report.contradictions_status",
  "report.contradictions_note",
  "threshold.hold_reason",
  "next_frame.text",
]);

function consequenceLevel(target: string): "low" | "high" {
  return target === "frame.constraints_soft" ? "low" : "high";
}

function confirmationPrompt(target: string): string {
  const label = target.replace(/^frame\./, "frame ");
  if (consequenceLevel(target) === "low") {
    return `${label} can be batch accepted when it preserves already-stated wording.`;
  }
  return `${label} changes the frame or risk channel. Confirm this patch individually.`;
}

function requiresEchoConfirmation(target: string): boolean {
  return consequenceLevel(target) === "high";
}

function systemPrompt(domainAdapter: string): string {
  return [
    "You are the live operator for NepsisCGN operator-guided packet mode.",
    "Ask only the next highest-value question needed to prevent premature closure.",
    "Convert vague reasoning into reviewable packet deltas; do not lock fields, commit state, or choose threshold decisions.",
    "Preserve RED before BLUE, keep STILL/ZeroBack obligations visible when relevant, and keep domain claims restrained.",
    `Domain adapter: ${domainAdapter}.`,
    `For ranked_discriminators.target_field use only one of: ${Array.from(DISCRIMINATOR_TARGET_FIELDS).join(", ")}.`,
    'Return compact JSON only with shape {"next_question":"","visible_scaffold":{"current_frame":"","open_constraint":"","red_concern":"","ready_to_lock":[]},"packet_delta_preview":{},"proposed_updates":[{"target":"","title":"","proposedValue":"","rationale":"","riskNote":""}],"fields_ready_to_lock":[],"blocking_uncertainties":[],"ranked_discriminators":[{"rank":1,"label":"","question":"","why_it_moves_decision":"","basis":"","target_field":""}]}',
  ].join(" ");
}

function parseObject(text: string): Record<string, unknown> {
  const cleaned = text.trim().replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  const parsed = JSON.parse(cleaned);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Model response was not a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function boundedString(value: unknown, max = 1200): string {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, max);
}

function boundedJson(value: unknown, max = 6000): string {
  try {
    const serialized = JSON.stringify(value ?? {});
    if (serialized.length <= max) {
      return serialized;
    }
    return JSON.stringify({ truncated: true, excerpt: serialized.slice(0, max) });
  } catch {
    return "{}";
  }
}

function stringList(value: unknown, maxItems = 8): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, maxItems);
}

function canonicalProposalText(value: string | string[]): string {
  return Array.isArray(value) ? value.join("\n") : value;
}

function normalizeScaffold(value: unknown, nextQuestion: string) {
  const row = typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  return {
    current_frame: boundedString(row.current_frame, 700),
    open_constraint: boundedString(row.open_constraint, 700),
    next_question: boundedString(row.next_question, 700) || nextQuestion,
    red_concern: boundedString(row.red_concern, 700),
    ready_to_lock: stringList(row.ready_to_lock),
  };
}

function normalizeDiscriminators(value: unknown) {
  const rows = Array.isArray(value) ? value : [];
  return rows
    .filter((row): row is Record<string, unknown> => typeof row === "object" && row !== null && !Array.isArray(row))
    .slice(0, 8)
    .map((row, index) => ({
      rank: typeof row.rank === "number" && row.rank > 0 ? Math.floor(row.rank) : index + 1,
      label: boundedString(row.label, 160),
      question: boundedString(row.question, 700),
      why_it_moves_decision: boundedString(row.why_it_moves_decision, 1000),
      basis: boundedString(row.basis, 400),
      target_field:
        typeof row.target_field === "string" && DISCRIMINATOR_TARGET_FIELDS.has(row.target_field.trim())
          ? row.target_field.trim()
          : "",
    }))
    .filter((row) => row.label || row.question);
}

function normalizeProposedUpdates(value: unknown, args: { model: string; loopId: string }) {
  const rows = Array.isArray(value) ? value : [];
  return rows
    .filter((row): row is Record<string, unknown> => typeof row === "object" && row !== null && !Array.isArray(row))
    .map((row) => {
      const target = typeof row.target === "string" && PATCH_TARGETS.has(row.target) ? row.target : "";
      const rawValue = row.proposedValue ?? row.proposed_value;
      const proposedValue = Array.isArray(rawValue)
        ? rawValue.filter((item): item is string => typeof item === "string")
        : typeof rawValue === "string"
          ? rawValue
          : "";
      const proposedValueHash = sha256Hex(canonicalProposalText(proposedValue));
      const patchId = randomUUID();
      return {
        id: patchId,
        patch_id: patchId,
        target,
        title: boundedString(row.title, 120) || "Guide suggestion",
        proposedValue,
        proposedValueHash,
        proposalReceipt: signOperatorProposalReceipt({
          mode: "suggest_field",
          target,
          model: args.model,
          loopId: args.loopId,
          proposedValueHash,
        }),
        rationale: boundedString(row.rationale, 1000),
        riskNote: boundedString(row.riskNote ?? row.risk_note, 1000),
        consequenceLevel: consequenceLevel(target),
        confirmationPrompt: confirmationPrompt(target),
        requiresEchoConfirmation: requiresEchoConfirmation(target),
      };
    })
    .filter((row) => row.target && canonicalProposalText(row.proposedValue).trim());
}

export async function POST(req: Request) {
  if (!modelRoutesEnabled()) {
    return NextResponse.json(
      {
        error: "Model routes disabled",
        detail: "Live operator guide routes are not enabled for this deployment.",
      },
      { status: 403 },
    );
  }

  const authFailure = requireEngineControlAuth(req);
  if (authFailure) return authFailure;
  const csrfFailure = requireCsrfToken(req);
  if (csrfFailure) return csrfFailure;

  if (!hasConfiguredOpenAiKey()) {
    return NextResponse.json(
      {
        error: "Server model key required",
        detail: "Configure OPENAI_API_KEY or NEPSIS_OPENAI_API_KEY server-side.",
      },
      { status: 428 },
    );
  }
  if (!hasConfiguredProposalReceiptSecret()) {
    return NextResponse.json(
      {
        error: "Server proposal receipt secret required",
        detail: "Configure NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET server-side.",
      },
      { status: 428 },
    );
  }

  const body = await req.json().catch(() => null);
  const userMessage = boundedString(body?.user_message, 2500);
  const domainAdapter = typeof body?.domain_adapter === "string" ? body.domain_adapter.trim() : "general";
  const operatorLoopId = typeof body?.operator_loop_id === "string" ? body.operator_loop_id.trim() : "";
  const model =
    typeof body?.model === "string" && body.model.trim().length > 0
      ? body.model.trim()
      : DEFAULT_OPENAI_MODEL;
  const context = typeof body?.context === "object" && body.context !== null ? body.context : {};

  if (!userMessage) {
    return NextResponse.json({ error: "user_message is required" }, { status: 400 });
  }
  if (!DOMAIN_ADAPTERS.has(domainAdapter)) {
    return NextResponse.json({ error: "Invalid domain_adapter" }, { status: 400 });
  }
  if (!operatorLoopId) {
    return NextResponse.json({ error: "operator_loop_id is required" }, { status: 400 });
  }

  try {
    const prompt = [
      `System:\n${systemPrompt(domainAdapter)}`,
      `User message:\n${userMessage}`,
      `Packet/context excerpt JSON:\n${boundedJson(context)}`,
    ].join("\n\n");
    const completion = await createOpenAiClient().responses.create({
      model,
      input: prompt,
    });
    const raw = extractOpenAiText(completion) || "{}";
    const parsed = parseObject(raw);
    const nextQuestion = boundedString(parsed.next_question, 700);
    if (!nextQuestion) {
      throw new Error("Model response did not include next_question.");
    }

    return NextResponse.json({
      model,
      next_question: nextQuestion,
      visible_scaffold: normalizeScaffold(parsed.visible_scaffold, nextQuestion),
      packet_delta_preview:
        typeof parsed.packet_delta_preview === "object" && parsed.packet_delta_preview !== null
          ? parsed.packet_delta_preview
          : {},
      proposed_updates: normalizeProposedUpdates(parsed.proposed_updates, { model, loopId: operatorLoopId }),
      fields_ready_to_lock: stringList(parsed.fields_ready_to_lock),
      blocking_uncertainties: stringList(parsed.blocking_uncertainties),
      ranked_discriminators: normalizeDiscriminators(parsed.ranked_discriminators),
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "Operator guide request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 502 },
    );
  }
}
