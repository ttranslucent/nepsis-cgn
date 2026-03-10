export type GateStatus = "PASS" | "WARN" | "BLOCK";
export type GateCheckStatus = "pass" | "warn" | "block";

export type GateCheck = {
  key: string;
  label: string;
  status: GateCheckStatus;
  detail: string;
};

export type GateResult<TPacket> = {
  status: GateStatus;
  checks: GateCheck[];
  missing: string[];
  warnings: string[];
  packet: TPacket;
};

export type StageCoach = {
  status: GateStatus;
  summary: string;
  prompts: string[];
};

export type FrameGateInput = {
  problemStatement: string;
  catastrophicOutcome: string;
  optimizationGoal: string;
  decisionHorizon: string;
  keyUncertainty: string;
  hardConstraints: string[];
  softConstraints: string[];
};

export type FramePacket = {
  problem_statement: string;
  catastrophic_outcome: string;
  optimization_goal: string;
  decision_horizon: string;
  key_uncertainty: string;
  hard_constraints: string[];
  soft_constraints: string[];
};

export type InterpretationContradictionsStatus = "unreviewed" | "none_identified" | "declared";

export type InterpretationGateInput = {
  reportText: string;
  posteriorHypotheses: string[];
  evidenceCount: number;
  reportSynced: boolean;
  contradictionsStatus: InterpretationContradictionsStatus;
  contradictionsNote: string;
  contradictionDensity: number | null;
};

export type InterpretationPacket = {
  report_text: string;
  hypothesis_count: number;
  evidence_count: number;
  report_synced: boolean;
  contradictions_status: InterpretationContradictionsStatus;
  contradictions_note: string;
  contradiction_density: number | null;
};

export type ThresholdDecision = "undecided" | "recommend" | "hold";

export type ThresholdGateInput = {
  posteriorHypotheses: string[];
  lossTreat: number | null | undefined;
  lossNotTreat: number | null | undefined;
  warningLevel: string | null | undefined;
  gateCrossed: boolean | null;
  recommendation: string | null | undefined;
  decision: ThresholdDecision;
  holdReason: string;
};

export type ThresholdPacket = {
  hypothesis_count: number;
  loss_treat: number | null;
  loss_not_treat: number | null;
  warning_level: string | null;
  gate_crossed: boolean | null;
  recommendation: string | null;
  decision: ThresholdDecision;
  hold_reason: string;
};

function textPresent(value: string): boolean {
  return value.trim().length > 0;
}

function determineGateStatus(checks: GateCheck[]): GateStatus {
  if (checks.some((check) => check.status === "block")) {
    return "BLOCK";
  }
  if (checks.some((check) => check.status === "warn")) {
    return "WARN";
  }
  return "PASS";
}

function buildGateResult<TPacket>(checks: GateCheck[], packet: TPacket): GateResult<TPacket> {
  return {
    status: determineGateStatus(checks),
    checks,
    missing: checks.filter((check) => check.status === "block").map((check) => check.label),
    warnings: checks.filter((check) => check.status === "warn").map((check) => check.label),
    packet,
  };
}

function uniquePrompts(prompts: string[]): string[] {
  return [...new Set(prompts.map((item) => item.trim()).filter((item) => item.length > 0))];
}

function topPendingChecks(checks: GateCheck[]): GateCheck[] {
  return checks
    .filter((check) => check.status !== "pass")
    .sort((a, b) => {
      if (a.status === b.status) {
        return a.label.localeCompare(b.label);
      }
      if (a.status === "block") {
        return -1;
      }
      if (b.status === "block") {
        return 1;
      }
      return 0;
    })
    .slice(0, 3);
}

function composeCoachSummary<TPacket>(gate: GateResult<TPacket>, stageName: string): string {
  if (gate.status === "PASS") {
    return `${stageName} contract satisfied. You can lock and continue.`;
  }
  if (gate.status === "WARN") {
    return `${stageName} contract is passable with warnings. Resolve warnings if you need higher confidence.`;
  }
  return `${stageName} contract blocked. Fill required constraints before progression.`;
}

function finiteNumber(value: number | null | undefined): boolean {
  return value != null && Number.isFinite(value);
}

export function evaluateFrameGate(input: FrameGateInput): GateResult<FramePacket> {
  const packet: FramePacket = {
    problem_statement: input.problemStatement.trim(),
    catastrophic_outcome: input.catastrophicOutcome.trim(),
    optimization_goal: input.optimizationGoal.trim(),
    decision_horizon: input.decisionHorizon.trim(),
    key_uncertainty: input.keyUncertainty.trim(),
    hard_constraints: input.hardConstraints,
    soft_constraints: input.softConstraints,
  };

  const totalConstraints = packet.hard_constraints.length + packet.soft_constraints.length;
  const checks: GateCheck[] = [
    {
      key: "problem_statement",
      label: "Problem statement",
      status: textPresent(packet.problem_statement) ? "pass" : "block",
      detail: textPresent(packet.problem_statement) ? "Defined." : "Required before frame lock.",
    },
    {
      key: "catastrophic_outcome",
      label: "Catastrophic outcome",
      status: textPresent(packet.catastrophic_outcome) ? "pass" : "block",
      detail: textPresent(packet.catastrophic_outcome)
        ? "Red-channel risk defined."
        : "Define what must not happen.",
    },
    {
      key: "optimization_goal",
      label: "Optimization goal",
      status: textPresent(packet.optimization_goal) ? "pass" : "block",
      detail: textPresent(packet.optimization_goal)
        ? "Blue-channel objective defined."
        : "Define what success should optimize for.",
    },
    {
      key: "decision_horizon",
      label: "Decision horizon",
      status: textPresent(packet.decision_horizon) ? "pass" : "block",
      detail: textPresent(packet.decision_horizon)
        ? "Time horizon declared."
        : "Set the operating horizon.",
    },
    {
      key: "key_uncertainty",
      label: "Key uncertainty",
      status: textPresent(packet.key_uncertainty) ? "pass" : "block",
      detail: textPresent(packet.key_uncertainty)
        ? "Uncertainty source declared."
        : "Declare the dominant uncertainty source.",
    },
    {
      key: "constraint_structure",
      label: "Constraint structure",
      status: totalConstraints > 0 ? "pass" : "block",
      detail: totalConstraints > 0 ? `${totalConstraints} constraints captured.` : "Add at least one hard/soft constraint.",
    },
  ];

  return buildGateResult(checks, packet);
}

export function buildFrameCoach(gate: GateResult<FramePacket>): StageCoach {
  const promptByKey: Record<string, string> = {
    problem_statement: "What exact decision or question are we trying to resolve?",
    catastrophic_outcome: "What catastrophic outcome must never be allowed?",
    optimization_goal: "What should we optimize for when red-channel risks are controlled?",
    decision_horizon: "What decision horizon are we operating on right now?",
    key_uncertainty: "What uncertainty could most change the decision?",
    constraint_structure: "List at least one hard constraint and one soft constraint.",
  };
  const prompts = uniquePrompts(
    topPendingChecks(gate.checks).map((check) => promptByKey[check.key] ?? check.detail),
  );
  return {
    status: gate.status,
    summary: composeCoachSummary(gate, "Frame"),
    prompts,
  };
}

export function evaluateInterpretationGate(input: InterpretationGateInput): GateResult<InterpretationPacket> {
  const packet: InterpretationPacket = {
    report_text: input.reportText.trim(),
    hypothesis_count: input.posteriorHypotheses.length,
    evidence_count: input.evidenceCount,
    report_synced: input.reportSynced,
    contradictions_status: input.contradictionsStatus,
    contradictions_note: input.contradictionsNote.trim(),
    contradiction_density: input.contradictionDensity,
  };

  const contradictionDeclared =
    packet.contradictions_status === "none_identified" ||
    (packet.contradictions_status === "declared" && textPresent(packet.contradictions_note));
  const highContradictionDensity =
    packet.contradiction_density != null && Number.isFinite(packet.contradiction_density) && packet.contradiction_density >= 0.35;

  const checks: GateCheck[] = [
    {
      key: "report_text",
      label: "Evidence narrative",
      status: textPresent(packet.report_text) ? "pass" : "block",
      detail: textPresent(packet.report_text) ? "Evidence text captured." : "Add observations before evaluation.",
    },
    {
      key: "hypothesis_count",
      label: "Candidate hypotheses",
      status: packet.hypothesis_count > 0 ? "pass" : "block",
      detail:
        packet.hypothesis_count > 0
          ? `${packet.hypothesis_count} candidate interpretations generated.`
          : "Run evaluation to generate at least one interpretation.",
    },
    {
      key: "evidence_count",
      label: "Evidence linkage",
      status: packet.evidence_count > 0 ? "pass" : "block",
      detail:
        packet.evidence_count > 0
          ? `${packet.evidence_count} evidence lines captured.`
          : "Link at least one evidence item to proceed.",
    },
    {
      key: "evaluation_freshness",
      label: "Evaluation freshness",
      status: packet.report_synced ? "pass" : "block",
      detail: packet.report_synced
        ? "Current evidence has been evaluated."
        : "Evidence changed since last evaluation. Run CALL + REPORT again.",
    },
    {
      key: "contradictions_declared",
      label: "Contradiction declaration",
      status: contradictionDeclared ? "pass" : "block",
      detail: contradictionDeclared
        ? "Contradiction status declared."
        : "Set contradiction status or add contradiction notes.",
    },
    {
      key: "contradiction_density",
      label: "Contradiction density",
      status: highContradictionDensity ? "warn" : "pass",
      detail: highContradictionDensity
        ? "High contradiction density. Consider gathering more evidence."
        : "Contradiction density within expected range.",
    },
  ];

  return buildGateResult(checks, packet);
}

export function buildInterpretationCoach(gate: GateResult<InterpretationPacket>): StageCoach {
  const promptByKey: Record<string, string> = {
    report_text: "What observations, signals, or evidence do we have so far?",
    hypothesis_count: "What competing interpretations are still live?",
    evidence_count: "What evidence supports or contradicts each interpretation?",
    evaluation_freshness: "Evidence changed after the last run. Re-run CALL + REPORT now.",
    contradictions_declared: "Declare contradiction status explicitly, or mark none identified.",
    contradiction_density: "Contradictions are high. Add disambiguating evidence before locking.",
  };
  const prompts = uniquePrompts(
    topPendingChecks(gate.checks).map((check) => promptByKey[check.key] ?? check.detail),
  );
  return {
    status: gate.status,
    summary: composeCoachSummary(gate, "Interpretation"),
    prompts,
  };
}

export function evaluateThresholdGate(input: ThresholdGateInput): GateResult<ThresholdPacket> {
  const packet: ThresholdPacket = {
    hypothesis_count: input.posteriorHypotheses.length,
    loss_treat: finiteNumber(input.lossTreat) ? Number(input.lossTreat) : null,
    loss_not_treat: finiteNumber(input.lossNotTreat) ? Number(input.lossNotTreat) : null,
    warning_level: input.warningLevel ?? null,
    gate_crossed: input.gateCrossed,
    recommendation: input.recommendation ?? null,
    decision: input.decision,
    hold_reason: input.holdReason.trim(),
  };

  const lossAsymmetryDefined = packet.loss_treat != null && packet.loss_not_treat != null;
  const redGateMetadataReady = packet.warning_level != null && packet.gate_crossed != null;
  const decisionDeclared = packet.decision !== "undecided";
  const holdReasonReady = packet.decision !== "hold" || textPresent(packet.hold_reason);
  const redOverrideViolation = packet.gate_crossed === true && packet.decision === "recommend";

  const checks: GateCheck[] = [
    {
      key: "posterior_available",
      label: "Posterior available",
      status: packet.hypothesis_count > 0 ? "pass" : "block",
      detail:
        packet.hypothesis_count > 0
          ? `${packet.hypothesis_count} posterior hypotheses available.`
          : "Posterior missing. Run interpretation first.",
    },
    {
      key: "loss_asymmetry",
      label: "Loss asymmetry defined",
      status: lossAsymmetryDefined ? "pass" : "block",
      detail: lossAsymmetryDefined ? "Threshold costs are defined." : "Loss asymmetry is required for threshold gating.",
    },
    {
      key: "red_override_metadata",
      label: "Red override check",
      status: redGateMetadataReady ? "pass" : "block",
      detail: redGateMetadataReady ? "Gate metadata available." : "Missing red-gate metadata (warning level / p_bad vs theta).",
    },
    {
      key: "decision_declared",
      label: "Decision declaration",
      status: decisionDeclared ? "pass" : "block",
      detail: decisionDeclared ? `Decision marked as ${packet.decision}.` : "Choose recommend or hold.",
    },
    {
      key: "hold_reason",
      label: "Hold rationale",
      status: holdReasonReady ? "pass" : "block",
      detail: holdReasonReady ? "Hold rationale complete." : "Provide hold rationale before continuing.",
    },
    {
      key: "red_override_enforced",
      label: "Red override enforcement",
      status: redOverrideViolation ? "block" : "pass",
      detail: redOverrideViolation
        ? "Red gate crossed. Recommendation is blocked until decision is hold."
        : "Red override discipline satisfied.",
    },
  ];

  return buildGateResult(checks, packet);
}

export function buildThresholdCoach(gate: GateResult<ThresholdPacket>): StageCoach {
  const promptByKey: Record<string, string> = {
    posterior_available: "Posterior is missing. Run interpretation to generate hypotheses first.",
    loss_asymmetry: "Define loss asymmetry (false positive vs false negative cost).",
    red_override_metadata: "Missing red-gate metadata. Re-run interpretation to refresh governance values.",
    decision_declared: "Declare threshold decision: recommend action or hold.",
    hold_reason: "If holding, explain what clarification or evidence is required.",
    red_override_enforced: "Red gate is crossed. Recommendation is blocked; hold and gather more evidence.",
  };
  const prompts = uniquePrompts(
    topPendingChecks(gate.checks).map((check) => promptByKey[check.key] ?? check.detail),
  );
  return {
    status: gate.status,
    summary: composeCoachSummary(gate, "Threshold"),
    prompts,
  };
}
