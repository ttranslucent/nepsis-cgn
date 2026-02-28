"use client";

import { useEffect, useState } from "react";

import {
  type EngineCreateSessionPayload,
  type EngineFrame,
  type EngineFamily,
  type EngineReframePayload,
  type EngineStepPayload,
} from "@/lib/engineClient";
import { useEngineSession } from "@/lib/useEngineSession";

type SafetySignForm = {
  critical_signal: boolean;
  policy_violation: boolean;
  notes: string;
};

type ClinicalSignForm = {
  radicular_pain: boolean;
  spasm_present: boolean;
  saddle_anesthesia: boolean;
  bladder_dysfunction: boolean;
  bilateral_weakness: boolean;
  progression: boolean;
  fever: boolean;
  notes: string;
  followup: string;
};

type PuzzleSignForm = {
  letters: string;
  candidate: string;
};

type ReframeForm = {
  text: string;
  objective_type: string;
  domain: string;
  time_horizon: string;
  rationale_for_change: string;
  constraints_hard_csv: string;
  constraints_soft_csv: string;
};

const DEFAULT_SAFETY_SIGN: SafetySignForm = {
  critical_signal: false,
  policy_violation: false,
  notes: "",
};

const DEFAULT_CLINICAL_SIGN: ClinicalSignForm = {
  radicular_pain: true,
  spasm_present: true,
  saddle_anesthesia: false,
  bladder_dysfunction: false,
  bilateral_weakness: false,
  progression: false,
  fever: false,
  notes: "",
  followup: "",
};

const DEFAULT_PUZZLE_SIGN: PuzzleSignForm = {
  letters: "JAIILUNG",
  candidate: "JAILING",
};

const DEFAULT_REFRAME_FORM: ReframeForm = {
  text: "",
  objective_type: "",
  domain: "",
  time_horizon: "",
  rationale_for_change: "",
  constraints_hard_csv: "",
  constraints_soft_csv: "",
};

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function optionalText(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function parseCsvList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function buildSignPayload(
  family: EngineFamily,
  forms: {
    safety: SafetySignForm;
    clinical: ClinicalSignForm;
    puzzle: PuzzleSignForm;
  },
): Record<string, unknown> {
  if (family === "safety") {
    const payload: Record<string, unknown> = {
      critical_signal: forms.safety.critical_signal,
      policy_violation: forms.safety.policy_violation,
    };
    const notes = optionalText(forms.safety.notes);
    if (notes) {
      payload.notes = notes;
    }
    return payload;
  }

  if (family === "clinical") {
    const payload: Record<string, unknown> = {
      radicular_pain: forms.clinical.radicular_pain,
      spasm_present: forms.clinical.spasm_present,
      saddle_anesthesia: forms.clinical.saddle_anesthesia,
      bladder_dysfunction: forms.clinical.bladder_dysfunction,
      bilateral_weakness: forms.clinical.bilateral_weakness,
      progression: forms.clinical.progression,
      fever: forms.clinical.fever,
    };
    const notes = optionalText(forms.clinical.notes);
    const followup = optionalText(forms.clinical.followup);
    if (notes) {
      payload.notes = notes;
    }
    if (followup) {
      payload.followup = followup;
    }
    return payload;
  }

  return {
    letters: forms.puzzle.letters,
    candidate: forms.puzzle.candidate,
  };
}

export default function EnginePage() {
  const {
    loading,
    error,
    clearError,
    healthy,
    routes,
    sessions,
    activeSession,
    packets,
    lastStep,
    refreshHealth,
    refreshRoutes,
    refreshSessions,
    createSession,
    loadSession,
    step,
    reframe,
    refreshPackets,
    deleteSession,
  } = useEngineSession();

  const [family, setFamily] = useState<EngineFamily>("safety");
  const [enableGovernance, setEnableGovernance] = useState(true);
  const [cFp, setCFp] = useState("1");
  const [cFn, setCFn] = useState("9");
  const [createFrameText, setCreateFrameText] = useState("");

  const [safetySign, setSafetySign] = useState<SafetySignForm>(DEFAULT_SAFETY_SIGN);
  const [clinicalSign, setClinicalSign] = useState<ClinicalSignForm>(DEFAULT_CLINICAL_SIGN);
  const [puzzleSign, setPuzzleSign] = useState<PuzzleSignForm>(DEFAULT_PUZZLE_SIGN);

  const [commit, setCommit] = useState(false);
  const [userDecision, setUserDecision] = useState<"" | "stop" | "continue_override">("");
  const [overrideReason, setOverrideReason] = useState("");

  const [reframeForm, setReframeForm] = useState<ReframeForm>(DEFAULT_REFRAME_FORM);

  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      await Promise.all([refreshHealth(), refreshRoutes(), refreshSessions()]);
    })();
  }, [refreshHealth, refreshRoutes, refreshSessions]);

  function clearAllErrors() {
    setLocalError(null);
    clearError();
  }

  function hydrateReframeForm(frame: EngineFrame | null | undefined) {
    if (!frame) {
      return;
    }
    setReframeForm((prev) => ({
      ...prev,
      text: frame.text ?? "",
      objective_type: frame.objective_type ?? "",
      domain: frame.domain ?? "",
      time_horizon: frame.time_horizon ?? "",
      rationale_for_change: frame.rationale_for_change ?? prev.rationale_for_change,
      constraints_hard_csv: frame.constraints_hard.join(", "),
      constraints_soft_csv: frame.constraints_soft.join(", "),
    }));
  }

  async function handleCreateSession() {
    clearAllErrors();
    const payload: EngineCreateSessionPayload = {
      family,
      emit_packet: true,
    };
    if (enableGovernance) {
      const parsedCFp = Number(cFp);
      const parsedCFn = Number(cFn);
      if (!Number.isFinite(parsedCFp) || !Number.isFinite(parsedCFn) || parsedCFp < 0 || parsedCFn < 0) {
        setLocalError("Governance costs must be non-negative numbers.");
        return;
      }
      payload.governance = { c_fp: parsedCFp, c_fn: parsedCFn };
    }
    if (createFrameText.trim()) {
      payload.frame = { text: createFrameText.trim() };
    }
    const created = await createSession(payload);
    if (created) {
      hydrateReframeForm(created.frame);
      await refreshPackets(created.session_id);
    }
  }

  async function handleOpenSession(sessionId: string) {
    clearAllErrors();
    const opened = await loadSession(sessionId);
    if (opened) {
      hydrateReframeForm(opened.frame);
    }
  }

  async function handleStep() {
    clearAllErrors();
    if (!activeSession) {
      setLocalError("Create or select a session before stepping.");
      return;
    }

    if (activeSession.family === "puzzle") {
      if (!puzzleSign.letters.trim() || !puzzleSign.candidate.trim()) {
        setLocalError("Puzzle sessions require both letters and candidate.");
        return;
      }
    }

    const payload: EngineStepPayload = {
      sign: buildSignPayload(activeSession.family, {
        safety: safetySign,
        clinical: clinicalSign,
        puzzle: puzzleSign,
      }),
      commit,
    };
    if (userDecision) {
      payload.user_decision = userDecision;
    }
    if (overrideReason.trim()) {
      payload.override_reason = overrideReason.trim();
    }

    const result = await step(payload);
    if (result) {
      await refreshPackets(result.session.session_id);
    }
  }

  async function handleReframe() {
    clearAllErrors();
    if (!activeSession) {
      setLocalError("Create or select a session before reframing.");
      return;
    }

    const framePayload: EngineReframePayload["frame"] = {};
    const text = optionalText(reframeForm.text);
    const objectiveType = optionalText(reframeForm.objective_type);
    const domain = optionalText(reframeForm.domain);
    const timeHorizon = optionalText(reframeForm.time_horizon);
    const rationale = optionalText(reframeForm.rationale_for_change);
    const hardConstraints = parseCsvList(reframeForm.constraints_hard_csv);
    const softConstraints = parseCsvList(reframeForm.constraints_soft_csv);

    if (text !== undefined) {
      framePayload.text = text;
    }
    if (objectiveType !== undefined) {
      framePayload.objective_type = objectiveType;
    }
    if (domain !== undefined) {
      framePayload.domain = domain;
    }
    if (timeHorizon !== undefined) {
      framePayload.time_horizon = timeHorizon;
    }
    if (rationale !== undefined) {
      framePayload.rationale_for_change = rationale;
    }
    if (hardConstraints.length > 0) {
      framePayload.constraints_hard = hardConstraints;
    }
    if (softConstraints.length > 0) {
      framePayload.constraints_soft = softConstraints;
    }

    if (Object.keys(framePayload).length === 0) {
      setLocalError("Reframe requires at least one non-empty field.");
      return;
    }

    const updated = await reframe({ frame: framePayload });
    if (updated) {
      setReframeForm((prev) => ({
        ...prev,
        text: updated.text ?? prev.text,
        objective_type: updated.objective_type ?? prev.objective_type,
        domain: updated.domain ?? prev.domain,
        time_horizon: updated.time_horizon ?? prev.time_horizon,
        constraints_hard_csv: updated.constraints_hard.join(", "),
        constraints_soft_csv: updated.constraints_soft.join(", "),
      }));
    }
  }

  async function handleDeleteSession(sessionId?: string) {
    clearAllErrors();
    const deleted = await deleteSession(sessionId);
    if (deleted) {
      await refreshSessions();
    }
  }

  const stepFamily: EngineFamily = activeSession?.family ?? family;
  const signPreview = buildSignPayload(stepFamily, {
    safety: safetySign,
    clinical: clinicalSign,
    puzzle: puzzleSign,
  });

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6">
      <div className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Engine Console</h1>
            <p className="text-sm text-nepsis-muted">
              Create sessions and drive step/reframe/delete actions against `/api/engine/*`.
            </p>
          </div>
          <div className="text-xs text-nepsis-muted">
            Backend:{" "}
            <span className={healthy ? "text-green-400" : healthy === false ? "text-red-400" : "text-yellow-300"}>
              {healthy === null ? "unknown" : healthy ? "healthy" : "unreachable"}
            </span>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => void refreshHealth()}
            className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
          >
            Refresh Health
          </button>
          <button
            onClick={() => void refreshRoutes()}
            className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
          >
            Refresh Routes
          </button>
          <button
            onClick={() => void refreshSessions()}
            className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
          >
            Refresh Sessions
          </button>
        </div>
        {routes.length > 0 && (
          <div className="mt-3 max-h-36 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 font-mono text-[11px] text-nepsis-muted">
            {routes.map((route) => (
              <div key={`${route.method}-${route.path}`}>
                {route.method.padEnd(6, " ")} {route.path}
              </div>
            ))}
          </div>
        )}
      </div>

      {(localError || error) && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {localError ?? error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Create Session</h2>
          <div className="mt-3 space-y-3 text-sm">
            <label className="block">
              <div className="mb-1 text-xs text-nepsis-muted">Family</div>
              <select
                value={family}
                onChange={(event) => setFamily(event.target.value as EngineFamily)}
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              >
                <option value="safety">safety</option>
                <option value="clinical">clinical</option>
                <option value="puzzle">puzzle</option>
              </select>
            </label>

            <label className="flex items-center gap-2 text-xs text-nepsis-muted">
              <input
                type="checkbox"
                checked={enableGovernance}
                onChange={(event) => setEnableGovernance(event.target.checked)}
              />
              Enable Governance (c_fp/c_fn)
            </label>

            {enableGovernance && (
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <div className="mb-1 text-xs text-nepsis-muted">c_fp</div>
                  <input
                    value={cFp}
                    onChange={(event) => setCFp(event.target.value)}
                    className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                  />
                </label>
                <label className="block">
                  <div className="mb-1 text-xs text-nepsis-muted">c_fn</div>
                  <input
                    value={cFn}
                    onChange={(event) => setCFn(event.target.value)}
                    className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                  />
                </label>
              </div>
            )}

            <label className="block">
              <div className="mb-1 text-xs text-nepsis-muted">Seed Frame Text (optional)</div>
              <textarea
                value={createFrameText}
                onChange={(event) => setCreateFrameText(event.target.value)}
                rows={3}
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>

            <button
              onClick={() => void handleCreateSession()}
              disabled={loading}
              className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
            >
              Create Session
            </button>
          </div>
        </section>

        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Sessions</h2>
          <div className="mt-3 max-h-80 space-y-2 overflow-auto">
            {sessions.length === 0 && <div className="text-xs text-nepsis-muted">No sessions yet.</div>}
            {sessions.map((session) => {
              const isActive = activeSession?.session_id === session.session_id;
              return (
                <div
                  key={session.session_id}
                  className={`rounded-lg border px-2 py-2 text-xs ${
                    isActive
                      ? "border-nepsis-accent bg-nepsis-accent/10"
                      : "border-nepsis-border bg-black/10"
                  }`}
                >
                  <div className="font-mono">{session.session_id.slice(0, 8)}...</div>
                  <div className="mt-1 text-nepsis-muted">
                    {session.family} · {session.stage} · steps={session.steps} · packets={session.packet_count}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => void handleOpenSession(session.session_id)}
                      className="rounded-full border border-nepsis-border px-2 py-1 hover:border-nepsis-accent"
                    >
                      Open
                    </button>
                    <button
                      onClick={() => void handleDeleteSession(session.session_id)}
                      className="rounded-full border border-red-500/60 px-2 py-1 text-red-300 hover:bg-red-500/10"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Active Session</h2>
          {!activeSession && <div className="mt-3 text-xs text-nepsis-muted">No active session selected.</div>}
          {activeSession && (
            <div className="mt-3 space-y-2 text-xs">
              <div className="font-mono">{activeSession.session_id}</div>
              <div className="text-nepsis-muted">
                {activeSession.family} · {activeSession.stage}
              </div>
              <div className="text-nepsis-muted">
                steps={activeSession.steps} · packets={packets.length}
              </div>
              {activeSession.frame?.text && (
                <div className="rounded-lg border border-nepsis-border bg-black/10 p-2 text-nepsis-muted">
                  {activeSession.frame.text}
                </div>
              )}
              <div className="flex gap-2">
                <button
                  onClick={() => void refreshPackets(activeSession.session_id)}
                  className="rounded-full border border-nepsis-border px-2 py-1 hover:border-nepsis-accent"
                >
                  Refresh Packets
                </button>
                <button
                  onClick={() => void handleDeleteSession(activeSession.session_id)}
                  className="rounded-full border border-red-500/60 px-2 py-1 text-red-300 hover:bg-red-500/10"
                >
                  Delete Active
                </button>
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Step Session</h2>
          <div className="mt-2 text-xs text-nepsis-muted">
            Sign form for family: <span className="font-mono">{stepFamily}</span>
          </div>

          {stepFamily === "safety" && (
            <div className="mt-3 space-y-2 text-xs">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={safetySign.critical_signal}
                  onChange={(event) =>
                    setSafetySign((prev) => ({ ...prev, critical_signal: event.target.checked }))
                  }
                />
                critical_signal
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={safetySign.policy_violation}
                  onChange={(event) =>
                    setSafetySign((prev) => ({ ...prev, policy_violation: event.target.checked }))
                  }
                />
                policy_violation
              </label>
              <label className="block">
                <div className="mb-1 text-nepsis-muted">notes (optional)</div>
                <input
                  value={safetySign.notes}
                  onChange={(event) => setSafetySign((prev) => ({ ...prev, notes: event.target.value }))}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>
            </div>
          )}

          {stepFamily === "clinical" && (
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.radicular_pain}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, radicular_pain: event.target.checked }))
                  }
                />
                radicular_pain
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.spasm_present}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, spasm_present: event.target.checked }))
                  }
                />
                spasm_present
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.saddle_anesthesia}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, saddle_anesthesia: event.target.checked }))
                  }
                />
                saddle_anesthesia
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.bladder_dysfunction}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, bladder_dysfunction: event.target.checked }))
                  }
                />
                bladder_dysfunction
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.bilateral_weakness}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, bilateral_weakness: event.target.checked }))
                  }
                />
                bilateral_weakness
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.progression}
                  onChange={(event) =>
                    setClinicalSign((prev) => ({ ...prev, progression: event.target.checked }))
                  }
                />
                progression
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clinicalSign.fever}
                  onChange={(event) => setClinicalSign((prev) => ({ ...prev, fever: event.target.checked }))}
                />
                fever
              </label>
              <div />
              <label className="col-span-2 block">
                <div className="mb-1 text-nepsis-muted">notes (optional)</div>
                <input
                  value={clinicalSign.notes}
                  onChange={(event) => setClinicalSign((prev) => ({ ...prev, notes: event.target.value }))}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>
              <label className="col-span-2 block">
                <div className="mb-1 text-nepsis-muted">followup (optional)</div>
                <input
                  value={clinicalSign.followup}
                  onChange={(event) => setClinicalSign((prev) => ({ ...prev, followup: event.target.value }))}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>
            </div>
          )}

          {stepFamily === "puzzle" && (
            <div className="mt-3 space-y-2 text-xs">
              <label className="block">
                <div className="mb-1 text-nepsis-muted">letters</div>
                <input
                  value={puzzleSign.letters}
                  onChange={(event) => setPuzzleSign((prev) => ({ ...prev, letters: event.target.value }))}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="block">
                <div className="mb-1 text-nepsis-muted">candidate</div>
                <input
                  value={puzzleSign.candidate}
                  onChange={(event) => setPuzzleSign((prev) => ({ ...prev, candidate: event.target.value }))}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 font-mono"
                />
              </label>
            </div>
          )}

          <div className="mt-3 rounded-lg border border-nepsis-border bg-black/20 p-2">
            <div className="mb-1 text-[11px] text-nepsis-muted">sign preview</div>
            <pre className="max-h-32 overflow-auto text-[11px] text-nepsis-muted">{pretty(signPreview)}</pre>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="flex items-center gap-2 text-xs text-nepsis-muted">
              <input type="checkbox" checked={commit} onChange={(event) => setCommit(event.target.checked)} />
              Commit
            </label>
            <label className="block text-xs text-nepsis-muted">
              User Decision
              <select
                value={userDecision}
                onChange={(event) => setUserDecision(event.target.value as "" | "stop" | "continue_override")}
                className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              >
                <option value="">none</option>
                <option value="stop">stop</option>
                <option value="continue_override">continue_override</option>
              </select>
            </label>
          </div>
          <label className="mt-3 block text-xs text-nepsis-muted">Override Reason (optional)</label>
          <input
            value={overrideReason}
            onChange={(event) => setOverrideReason(event.target.value)}
            className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
          />
          <button
            onClick={() => void handleStep()}
            disabled={loading}
            className="mt-3 rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
          >
            Step
          </button>
        </section>

        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Reframe Session</h2>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <label className="col-span-2 block">
              <div className="mb-1 text-nepsis-muted">text</div>
              <textarea
                value={reframeForm.text}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    text: event.target.value,
                  }))
                }
                rows={3}
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>

            <label className="block">
              <div className="mb-1 text-nepsis-muted">objective_type</div>
              <select
                value={reframeForm.objective_type}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    objective_type: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              >
                <option value="">(no change)</option>
                <option value="explain">explain</option>
                <option value="decide">decide</option>
                <option value="predict">predict</option>
                <option value="debug">debug</option>
                <option value="design">design</option>
                <option value="sensemake">sensemake</option>
              </select>
            </label>

            <label className="block">
              <div className="mb-1 text-nepsis-muted">time_horizon</div>
              <select
                value={reframeForm.time_horizon}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    time_horizon: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              >
                <option value="">(no change)</option>
                <option value="immediate">immediate</option>
                <option value="short">short</option>
                <option value="medium">medium</option>
                <option value="long">long</option>
                <option value="indefinite">indefinite</option>
              </select>
            </label>

            <label className="col-span-2 block">
              <div className="mb-1 text-nepsis-muted">domain</div>
              <input
                value={reframeForm.domain}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    domain: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>

            <label className="col-span-2 block">
              <div className="mb-1 text-nepsis-muted">rationale_for_change</div>
              <input
                value={reframeForm.rationale_for_change}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    rationale_for_change: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>

            <label className="col-span-2 block">
              <div className="mb-1 text-nepsis-muted">constraints_hard (comma-separated)</div>
              <input
                value={reframeForm.constraints_hard_csv}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    constraints_hard_csv: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>

            <label className="col-span-2 block">
              <div className="mb-1 text-nepsis-muted">constraints_soft (comma-separated)</div>
              <input
                value={reframeForm.constraints_soft_csv}
                onChange={(event) =>
                  setReframeForm((prev) => ({
                    ...prev,
                    constraints_soft_csv: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
              />
            </label>
          </div>

          <div className="mt-3 rounded-lg border border-nepsis-border bg-black/20 p-2">
            <div className="mb-1 text-[11px] text-nepsis-muted">reframe payload preview</div>
            <pre className="max-h-32 overflow-auto text-[11px] text-nepsis-muted">
              {pretty({
                frame: {
                  text: optionalText(reframeForm.text),
                  objective_type: optionalText(reframeForm.objective_type),
                  domain: optionalText(reframeForm.domain),
                  time_horizon: optionalText(reframeForm.time_horizon),
                  rationale_for_change: optionalText(reframeForm.rationale_for_change),
                  constraints_hard: parseCsvList(reframeForm.constraints_hard_csv),
                  constraints_soft: parseCsvList(reframeForm.constraints_soft_csv),
                },
              })}
            </pre>
          </div>
          <button
            onClick={() => void handleReframe()}
            disabled={loading}
            className="mt-3 rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
          >
            Reframe
          </button>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Last Step</h2>
          <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-3 text-[11px] text-nepsis-muted">
            {lastStep ? pretty(lastStep) : "No step executed yet."}
          </pre>
        </section>

        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <h2 className="text-sm font-semibold">Packets</h2>
          <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-3 text-[11px] text-nepsis-muted">
            {packets.length > 0 ? pretty(packets.slice(-5)) : "No packets yet."}
          </pre>
        </section>
      </div>
    </div>
  );
}
