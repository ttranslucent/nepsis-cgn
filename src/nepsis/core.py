import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .deviance import DevianceMonitor
from .llm import BaseLLMProvider, SimulatedWordGameLLM
from .manifolds import BaseManifold, ProjectionSpec, TriageResult, ValidationResult, WordGameManifold
from .scoring import assess_channel


# --- 1. THE PHYSICS (State) ---


@dataclass
class ChannelState:
    """
    Represents the physiological state of the system.
    red:  Probability of ruin (0.0 - 1.0). If > tau_R, system locks.
    blue: Potential utility (0.0 - 1.0).
    """

    red: float
    blue: float
    tau_R: float  # Ruin threshold

    @property
    def ruin_gate(self) -> str:
        """Hard veto: closes if red exceeds threshold."""
        return "CLOSED" if self.red > self.tau_R else "OPEN"

    def calculate_score(self, lethal_weight: float, utility_weight: float) -> float:
        """
        Composite scoring. Returns -inf if the ruin gate is closed.
        """
        if self.ruin_gate == "CLOSED":
            return float("-inf")

        red_penalty = -(self.red * lethal_weight)
        blue_reward = self.blue * utility_weight
        return red_penalty + blue_reward

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["ruin_gate"] = self.ruin_gate
        return data


# --- 2. THE SUPERVISOR (The Spine) ---


class NepsisSupervisor:
    """
    Orchestrates the three-step protocol: triage → projection → validation.
    """

    def __init__(
        self,
        system_id: str = "nepsis-v1",
        default_manifold: Optional[BaseManifold] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        max_retries: int = 3,
    ):
        self.system_id = system_id
        self.default_manifold = default_manifold or WordGameManifold()
        self.llm: BaseLLMProvider = llm_provider or SimulatedWordGameLLM()
        self.max_retries = max_retries
        self.trace_log: List[Dict[str, Any]] = []
        self.deviance_monitor: Optional[DevianceMonitor] = DevianceMonitor()

    def execute(self, raw_query: str, context: str = "cli") -> Dict[str, Any]:
        """
        Master loop for a single query.
        """
        query_id = str(uuid.uuid4())
        print(f"--- [NEPSIS] Processing Query ID: {query_id[:8]} ---")

        # STEP 1: TRIAGE (User -> Nepsis)
        print("1. Running Triage (Manifold Chooser)...")
        triage_report = self._run_triage(query_id, raw_query, context)
        self.trace_log.append(triage_report)

        if triage_report["channel_state"]["ruin_gate"] == "CLOSED":
            print("!!! RUIN GATE CLOSED. HALTING EXECUTION. !!!")
            return self._generate_rejection(triage_report)

        # STEP 2: PROJECTION (Nepsis -> LLM/WM)
        print("2. Running Projection (Constraint Injection)...")
        projection_spec = self._run_projection(triage_report)
        self.trace_log.append(self._projection_dict(projection_spec, triage_report["query_id"]))

        # STEP 3: VALIDATION LOOP (LLM -> Nepsis -> Final)
        print("3. Running Validation Loop (Outcome Audit + Repair)...")
        attempts = 0
        while attempts < self.max_retries:
            attempts += 1
            print(f"\n>> Attempt {attempts}/{self.max_retries}")

            raw_artifact = self.llm.generate(projection_spec)
            print(f"   LLM Candidate: {raw_artifact}")

            validation = self._run_validation(projection_spec, raw_artifact)
            self.trace_log.append(validation)

            # Deviance tracking
            manifold_name = projection_spec.get("manifold_context", {}).get("domain") if isinstance(projection_spec, dict) else projection_spec.manifold_context.get("domain")
            if self.deviance_monitor and manifold_name:
                metrics = validation.get("candidate_metrics", {})
                blue = metrics.get("blue_score", 0.0)
                drift = metrics.get("drift_detected", False)
                self.deviance_monitor.record(manifold_name, validation["outcome"], blue, drift)

            if validation["outcome"] == "SUCCESS":
                print("   [RED CHANNEL] CLEAR. Candidate Accepted.")
                return validation

            print(f"   [RED CHANNEL] BLOCKED. Violations: {validation['candidate_metrics']['red_violations']}")

            # Apply repair delta if available
            repair = validation.get("repair") or {}
            delta = repair.get("next_projection_delta")
            if delta:
                print(f"   [NEPSIS] Applying Delta: {delta}")
                # Append correction to invariants to tighten the jail
                projection_spec.invariants.append(f"CORRECTION: {delta}")
                continue

            # No repair hint -> break
            break

        return {"$schema": "nepsis/validation/v1", "outcome": "FAILURE", "reason": "Max Retries Exceeded"}

    # --- INTERNAL LOGIC STUBS (Brains to be filled later) ---

    def _run_triage(self, query_id: str, raw_query: str, context: str) -> Dict[str, Any]:
        """
        Simulates manifold selection and channel scoring.
        """
        manifold = self.default_manifold
        triage = manifold.triage(raw_query, context)
        if triage.is_well_posed:
            channel = ChannelState(**assess_channel(raw_query))
        else:
            channel = ChannelState(red=1.0, blue=0.0, tau_R=0.2)

        # Adjust tau_R based on deviance history
        manifold_name = triage.detected_manifold
        if self.deviance_monitor and manifold_name:
            channel.tau_R = self.deviance_monitor.adjust_tau(manifold_name, channel.tau_R)

        return {
            "$schema": "nepsis/triage/v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_id": self.system_id,
            "query_id": query_id,
            "request": {"raw_query": raw_query, "source": context},
            "manifold_assessment": {
                "detected_manifold": triage.detected_manifold,
                "confidence": triage.confidence,
                "is_well_posed": triage.is_well_posed,
                "meta": triage.manifold_meta,
            },
            "channel_state": {
                "red_score": channel.red,
                "blue_potential": channel.blue,
                "tau_R": channel.tau_R,
                "ruin_gate": channel.ruin_gate,
            },
            "constraints": {
                "hard_red": triage.hard_red,
                "hard_blue": triage.hard_blue,
                "soft_blue": triage.soft_blue,
            },
            "zeroback_status": "armed",
        }

    def _run_projection(self, triage_report: Dict[str, Any]) -> ProjectionSpec:
        """
        Builds the constraint manifold ("jail") that a worker must respect.
        """
        projection = self.default_manifold.project(
            TriageResult(
                detected_manifold=triage_report["manifold_assessment"]["detected_manifold"],
                confidence=triage_report["manifold_assessment"]["confidence"],
                is_well_posed=triage_report["manifold_assessment"]["is_well_posed"],
                hard_red=triage_report["constraints"]["hard_red"],
                hard_blue=triage_report["constraints"]["hard_blue"],
                soft_blue=triage_report["constraints"]["soft_blue"],
                manifold_meta=triage_report["manifold_assessment"]["meta"],
            )
        )

        # Carry triage id in trace
        projection.trace |= {"triage_id": triage_report["query_id"]}
        return projection

    def _run_validation(self, projection: ProjectionSpec, artifact: Any) -> Dict[str, Any]:
        """
        Audits the result against the projection constraints.
        """
        validation = self.default_manifold.validate(projection, artifact)

        report = {
            "$schema": "nepsis/validation/v1",
            "outcome": validation.outcome,
            "candidate_metrics": validation.metrics,
            "manifold_adherence": validation.manifold_adherence or {},
            "final_artifact": validation.final_artifact,
            "zeroback_event": validation.zeroback_event,
            "repair": validation.repair,
        }
        return report

    @staticmethod
    def _projection_dict(projection: ProjectionSpec, triage_id: str) -> Dict[str, Any]:
        """
        Helper to serialize projection specs for trace logging.
        """
        return {
            "$schema": "nepsis/projection/v1",
            "system_instruction": projection.system_instruction,
            "manifold_context": projection.manifold_context,
            "invariants": projection.invariants,
            "objective_function": projection.objective_function,
            "trace": projection.trace | {"triage_id": triage_id},
        }

    def _generate_rejection(self, triage_report: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "$schema": "nepsis/validation/v1",
            "outcome": "REJECTED",
            "reason": "Ruin Gate Closed",
            "red_score": triage_report["channel_state"]["red_score"],
            "trace": {"triage_id": triage_report["query_id"]},
        }


# --- 4. RUNTIME (Terminal Bench) ---


if __name__ == "__main__":
    supervisor = NepsisSupervisor()
    user_query = "JANIGLL"
    final_report = supervisor.execute(user_query)

    print("\n--- FINAL REPORT ---")
    print(json.dumps(final_report, indent=2))
