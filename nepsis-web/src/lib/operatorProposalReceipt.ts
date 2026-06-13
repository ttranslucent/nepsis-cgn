import { createHash, createHmac, randomUUID } from "node:crypto";

export type OperatorProposalReceiptPayload = {
  schema_id: "nepsis.operator_model_proposal_receipt";
  schema_version: "1.0.0";
  receipt_id: string;
  issued_at: string;
  route: "/api/operator/model";
  mode: "suggest_field" | "review_completion";
  target: string;
  model: string;
  loop_id: string;
  proposed_value_hash: string;
};

export type OperatorProposalReceipt = OperatorProposalReceiptPayload & {
  signature: {
    algorithm: "hmac-sha256";
    key_id: string;
    signature: string;
    signed_at: string;
  };
};

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

export function sha256Hex(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export function proposalReceiptSecret(): string {
  const secret = process.env.NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET?.trim();
  if (!secret) {
    throw new Error("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET is required for operator model proposal receipts.");
  }
  return secret;
}

export function hasConfiguredProposalReceiptSecret(): boolean {
  return Boolean(process.env.NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET?.trim());
}

export function signOperatorProposalReceipt(args: {
  mode: "suggest_field" | "review_completion";
  target: string;
  model: string;
  loopId: string;
  proposedValueHash: string;
  now?: string;
}): OperatorProposalReceipt {
  const issuedAt = args.now ?? new Date().toISOString();
  const body: OperatorProposalReceiptPayload = {
    schema_id: "nepsis.operator_model_proposal_receipt",
    schema_version: "1.0.0",
    receipt_id: randomUUID(),
    issued_at: issuedAt,
    route: "/api/operator/model",
    mode: args.mode,
    target: args.target,
    model: args.model,
    loop_id: args.loopId,
    proposed_value_hash: args.proposedValueHash,
  };
  const keyId = process.env.NEPSIS_OPERATOR_PROPOSAL_RECEIPT_KEY_ID?.trim() || "default";
  return {
    ...body,
    signature: {
      algorithm: "hmac-sha256",
      key_id: keyId,
      signature: createHmac("sha256", proposalReceiptSecret()).update(canonicalJson(body), "utf8").digest("hex"),
      signed_at: issuedAt,
    },
  };
}
