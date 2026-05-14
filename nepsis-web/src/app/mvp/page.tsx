"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import {
  EngineClientError,
  engineClient,
  type NepsisMvpCaseId,
  type NepsisMvpPacket,
} from "@/lib/engineClient";

const CASES: Array<{ id: NepsisMvpCaseId; label: string; description: string }> = [
  {
    id: "jailing",
    label: "Jailing",
    description: "Constraint preservation, contradiction, retessellation, and audit packet.",
  },
  {
    id: "clinical",
    label: "Clinical",
    description: "RED hazard gating before BLUE optimization under uncertainty.",
  },
];

export default function MvpDemoPage() {
  const [caseId, setCaseId] = useState<NepsisMvpCaseId>("jailing");
  const [packet, setPacket] = useState<NepsisMvpPacket | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runDemo() {
    setIsRunning(true);
    setError(null);
    try {
      const result = await engineClient.runMvp({ case_id: caseId });
      setPacket(result);
    } catch (err) {
      if (err instanceof EngineClientError) {
        setError(err.message);
      } else {
        setError((err as Error)?.message ?? "MVP demo request failed.");
      }
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1380px] px-4 py-6 md:px-6 md:py-8">
      <section className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-nepsis-muted">
              NepsisCGN MVP Demo
            </div>
            <h1 className="mt-2 text-2xl font-semibold md:text-4xl">
              RED -&gt; STILL -&gt; BLUE -&gt; STILL -&gt; audit packet
            </h1>
            <p className="mt-3 text-sm text-nepsis-muted md:text-base">
              Run a deterministic canonical case through the backend packet builder and inspect the structured result.
            </p>
          </div>

          <div className="w-full max-w-xl rounded-2xl border border-nepsis-border bg-black/20 p-4">
            <fieldset>
              <legend className="text-xs font-semibold uppercase tracking-[0.14em] text-nepsis-muted">
                Demo case
              </legend>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {CASES.map((item) => {
                  const selected = item.id === caseId;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setCaseId(item.id)}
                      className={`rounded-xl border px-4 py-3 text-left transition ${
                        selected
                          ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                          : "border-nepsis-border bg-black/10 text-nepsis-muted hover:border-nepsis-accent"
                      }`}
                    >
                      <span className="block text-sm font-semibold">{item.label}</span>
                      <span className="mt-1 block text-xs leading-relaxed">{item.description}</span>
                    </button>
                  );
                })}
              </div>
            </fieldset>
            <button
              type="button"
              onClick={runDemo}
              disabled={isRunning}
              className="mt-4 w-full rounded-full bg-nepsis-accent px-5 py-2.5 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isRunning ? "Running..." : "Run Demo"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-5 rounded-2xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-100">
            {error}
          </div>
        )}
      </section>

      {packet ? <PacketView packet={packet} /> : <EmptyState />}
    </div>
  );
}

function EmptyState() {
  return (
    <section className="mt-5 rounded-3xl border border-nepsis-border bg-nepsis-panel p-6 text-sm text-nepsis-muted">
      Select a case and run the demo to view the structured Nepsis packet.
    </section>
  );
}

function PacketView({ packet }: { packet: NepsisMvpPacket }) {
  const contradictionTriggered = packet.contradiction_monitor.contradictions.length > 0;
  const retessellationTriggered = packet.denominator_collapse.retessellation_required;
  const zeroBackTriggered = packet.zeroback.triggered;
  const nonQuiescenceTriggered = packet.non_quiescence.wrong_manifold_possible;
  const stillCheckpoint1 = packet.still.checkpoints.find((item) => item.position === "after_red_before_blue");
  const stillCheckpoint2 = packet.still.checkpoints.find((item) => item.position === "after_blue_before_commitment");

  return (
    <div className="mt-5 space-y-5">
      <section className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6">
        <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-start">
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-nepsis-muted">Audit packet</div>
            <div className="mt-2 font-mono text-sm text-nepsis-accent">{packet.schema_id}</div>
            <h2 className="mt-2 text-xl font-semibold">{packet.case_id}</h2>
            <p className="mt-2 max-w-4xl text-sm text-nepsis-muted">{packet.input_text}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:min-w-[420px]">
            <Signal label="Contradiction" active={contradictionTriggered} />
            <Signal label="Retessellation" active={retessellationTriggered} />
            <Signal label="ZeroBack" active={zeroBackTriggered} />
            <Signal label="Non-quiescence" active={nonQuiescenceTriggered} />
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <ListBlock title="Observations" items={packet.observations} />
          <ListBlock title="Constraints" items={packet.constraints} />
        </div>
      </section>

      <Panel title="RED Channel" tone="red">
        <KeyValue label="Escalation required" value={String(packet.red_channel.escalation_required)} />
        <KeyValue label="Rationale" value={packet.red_channel.rationale} />
        <JsonList title="Active hazards" items={packet.red_channel.active_hazards} />
        <ListBlock title="Missing discriminators" items={packet.red_channel.missing_discriminators} compact />
      </Panel>

      {stillCheckpoint1 && (
        <StillCheckpointPanel
          checkpoint={stillCheckpoint1}
          readiness={packet.still.commitment_readiness}
          auditEvents={packet.still.audit_events}
        />
      )}

      <Panel title="BLUE Channel" tone="blue">
        <KeyValue label="Weights" value={formatWeights(packet.blue_channel.weights)} />
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          {packet.blue_channel.hypotheses.map((hypothesis) => (
            <div key={hypothesis.id} className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
              <div className="font-mono text-xs text-nepsis-accent">{hypothesis.id}</div>
              <div className="mt-1 text-sm font-semibold">{hypothesis.label}</div>
              <div className="mt-2 text-xs text-nepsis-muted">Likelihood: {hypothesis.likelihood}</div>
              <ListBlock title="Supporting features" items={hypothesis.supporting_features} compact />
              <ListBlock title="Contradicting features" items={hypothesis.contradicting_features} compact />
              <ListBlock title="Needed discriminators" items={hypothesis.needed_discriminators} compact />
            </div>
          ))}
        </div>
      </Panel>

      <section className="grid gap-5 xl:grid-cols-2">
        <Panel title="Contradiction Monitor">
          <KeyValue label="Density" value={String(packet.contradiction_monitor.contradiction_density)} />
          <KeyValue label="Stability" value={packet.contradiction_monitor.stability_status} />
          <JsonList title="Contradictions" items={packet.contradiction_monitor.contradictions} />
        </Panel>

        <Panel title="Denominator Collapse">
          <KeyValue label="Detected" value={String(packet.denominator_collapse.detected)} />
          <KeyValue label="Retessellation required" value={String(packet.denominator_collapse.retessellation_required)} />
          <ListBlock
            title="Missing hypothesis classes"
            items={packet.denominator_collapse.missing_hypothesis_classes}
            compact
          />
        </Panel>

        <Panel title="Non-Quiescence">
          <KeyValue label="Wrong manifold possible" value={String(packet.non_quiescence.wrong_manifold_possible)} />
          <KeyValue label="Reason" value={packet.non_quiescence.reason} />
          <KeyValue label="Next required move" value={packet.non_quiescence.next_required_move} />
        </Panel>
      </section>

      {stillCheckpoint2 && (
        <StillCheckpointPanel
          checkpoint={stillCheckpoint2}
          readiness={packet.still.commitment_readiness}
          auditEvents={packet.still.audit_events}
          learningNotes={packet.still.learning_notes}
        />
      )}

      <section className="grid gap-5 xl:grid-cols-2">
        <Panel title="Voronoi Commitment">
          <KeyValue label="Recommended action" value={packet.voronoi_commitment.recommended_action} />
          <KeyValue label="Threshold basis" value={packet.voronoi_commitment.threshold_basis} />
          <KeyValue label="Consequence weighting" value={packet.voronoi_commitment.consequence_weighting} />
        </Panel>

        <Panel title="ZeroBack">
          <KeyValue label="Triggered" value={String(packet.zeroback.triggered)} />
          <KeyValue label="Reason" value={packet.zeroback.reason} />
          <KeyValue label="Reset scope" value={packet.zeroback.reset_scope} />
        </Panel>
      </section>

      <StateFeedbackPanel feedback={packet.state_feedback} />

      <section className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6">
        <h2 className="text-lg font-semibold">Audit Trace</h2>
        <ol className="mt-4 space-y-3">
          {packet.audit_trace.map((event) => (
            <li key={`${event.order}-${event.stage}`} className="grid gap-3 rounded-2xl border border-nepsis-border bg-black/20 p-4 sm:grid-cols-[4rem_12rem_1fr]">
              <div className="font-mono text-xs text-nepsis-muted">#{event.order}</div>
              <div className="font-mono text-xs text-nepsis-accent">{event.stage}</div>
              <div className="text-sm text-nepsis-text">{event.summary}</div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6">
        <h2 className="text-lg font-semibold">Final Output</h2>
        <p className="mt-3 text-sm text-nepsis-text">{packet.final_output.concise_recommendation}</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <ListBlock title="Caveats" items={packet.final_output.caveats} compact />
          <ListBlock title="Required next discriminators" items={packet.final_output.required_next_discriminators} compact />
        </div>
      </section>

      <details className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6">
        <summary className="cursor-pointer text-sm font-semibold text-nepsis-accent">Raw JSON</summary>
        <pre className="mt-4 max-h-[520px] overflow-auto rounded-2xl border border-nepsis-border bg-black/40 p-4 text-xs leading-relaxed text-nepsis-muted">
          {JSON.stringify(packet, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Signal({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="rounded-2xl border border-nepsis-border bg-black/20 p-3">
      <div className="text-xs text-nepsis-muted">{label}</div>
      <div className={`mt-1 font-mono text-sm ${active ? "text-nepsis-accent" : "text-nepsis-muted"}`}>
        {active ? "TRIGGERED" : "CLEAR"}
      </div>
    </div>
  );
}

function Panel({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "red" | "blue";
  children: ReactNode;
}) {
  const toneClass =
    tone === "red"
      ? "border-red-400/40"
      : tone === "blue"
        ? "border-sky-400/40"
        : "border-nepsis-border";
  return (
    <section className={`rounded-3xl border ${toneClass} bg-nepsis-panel p-5 md:p-6`}>
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function StillCheckpointPanel({
  checkpoint,
  readiness,
  auditEvents,
  learningNotes = [],
}: {
  checkpoint: NonNullable<NepsisMvpPacket["still"]>["checkpoints"][number];
  readiness?: NonNullable<NepsisMvpPacket["still"]>["commitment_readiness"];
  auditEvents: NonNullable<NepsisMvpPacket["still"]>["audit_events"];
  learningNotes?: string[];
}) {
  const eventStage =
    checkpoint.position === "after_red_before_blue" ? "still_checkpoint_1" : "still_checkpoint_2";
  const auditEvent = auditEvents.find((event) => event.stage === eventStage);
  return (
    <section className="rounded-3xl border border-nepsis-accent/50 bg-nepsis-panel p-5 md:p-6">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-nepsis-muted">
        Strategic Time-in-Loop for Learning
      </div>
      <h2 className="mt-2 text-lg font-semibold">{checkpoint.name}</h2>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <KeyValue label="Position" value={checkpoint.position} />
          <KeyValue label="Trigger status" value={checkpoint.trigger_status} />
          <KeyValue label="Reason" value={checkpoint.reason} />
          <ListBlock
            title="Required before commitment"
            items={checkpoint.required_before_commitment}
            compact
          />
        </div>
        <div className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
          {readiness ? (
            <>
              <KeyValue label="Commitment readiness" value={readiness.status} />
              <KeyValue label="Readiness rationale" value={readiness.rationale} />
            </>
          ) : (
            <KeyValue label="Commitment readiness" value="n/a" />
          )}
          {auditEvent && <KeyValue label="STILL audit event" value={auditEvent.summary} />}
          {learningNotes.length > 0 && <ListBlock title="Learning notes" items={learningNotes} compact />}
        </div>
      </div>
    </section>
  );
}

function StateFeedbackPanel({ feedback }: { feedback: NepsisMvpPacket["state_feedback"] }) {
  return (
    <Panel title="State Feedback / Predicted Next State">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
          <KeyValue label="Phase" value={feedback.current_state.timestamp_or_phase} />
          <KeyValue label="Active frame" value={feedback.current_state.active_frame} />
          <KeyValue label="Current commitment" value={feedback.current_state.current_commitment} />
          <KeyValue label="Uncertainty level" value={feedback.current_state.uncertainty_level} />
          <ListBlock title="Active constraints" items={feedback.current_state.active_constraints} compact />
          <ListBlock title="Active hazards" items={feedback.current_state.active_hazards} compact />
        </div>

        <div className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
          <KeyValue label="Expected time window" value={feedback.predicted_next_state.expected_time_window} />
          <ListBlock title="Expected changes" items={feedback.predicted_next_state.expected_changes} compact />
          <ListBlock
            title="Expected discriminators"
            items={feedback.predicted_next_state.expected_discriminators}
            compact
          />
          <ListBlock
            title="Expected resolution signs"
            items={feedback.predicted_next_state.expected_resolution_signs}
            compact
          />
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
          <ListBlock title="Failure conditions" items={feedback.predicted_next_state.failure_conditions} />
        </div>

        <div className="rounded-2xl border border-nepsis-border bg-black/20 p-4">
          <KeyValue label="Loop decision" value={feedback.loop_decision.status} />
          <KeyValue label="Rationale" value={feedback.loop_decision.rationale} />
          <KeyValue label="Next observation required" value={feedback.loop_decision.next_observation_required} />
          <KeyValue label="Observed next state" value={feedback.observed_next_state.status} />
          <KeyValue label="Delta analysis" value={feedback.delta_analysis.reason} />
          <ListBlock title="State feedback audit events" items={feedback.audit_events} compact />
        </div>
      </div>
    </Panel>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3 first:mt-0">
      <div className="text-xs uppercase tracking-[0.12em] text-nepsis-muted">{label}</div>
      <div className="mt-1 break-words text-sm text-nepsis-text">{value}</div>
    </div>
  );
}

function ListBlock({ title, items, compact = false }: { title: string; items: string[]; compact?: boolean }) {
  return (
    <div className={compact ? "mt-3" : ""}>
      <div className="text-xs uppercase tracking-[0.12em] text-nepsis-muted">{title}</div>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1.5 text-sm text-nepsis-text">
          {items.map((item) => (
            <li key={item} className="break-words">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-sm text-nepsis-muted">None</div>
      )}
    </div>
  );
}

function JsonList({ title, items }: { title: string; items: Record<string, unknown>[] }) {
  return (
    <div className="mt-4">
      <div className="text-xs uppercase tracking-[0.12em] text-nepsis-muted">{title}</div>
      {items.length > 0 ? (
        <div className="mt-2 space-y-2">
          {items.map((item, index) => (
            <pre
              key={`${title}-${index}`}
              className="overflow-auto rounded-2xl border border-nepsis-border bg-black/30 p-3 text-xs leading-relaxed text-nepsis-muted"
            >
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
        </div>
      ) : (
        <div className="mt-2 text-sm text-nepsis-muted">None</div>
      )}
    </div>
  );
}

function formatWeights(weights: Record<string, string>): string {
  const entries = Object.entries(weights);
  if (entries.length === 0) {
    return "None";
  }
  return entries.map(([key, value]) => `${key}: ${value}`).join("; ");
}
