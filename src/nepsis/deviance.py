from collections import deque
from typing import Deque, Dict


class DevianceMonitor:
    """
    Tracks SAFE / NEAR_MISS / CRASH per manifold and adjusts tau_R recommendations.
    """

    def __init__(self, sensitivity: float = 0.5, window: int = 50, min_samples: int = 10, near_miss_threshold: float = 0.5):
        self.sensitivity = sensitivity
        self.window = window
        self.min_samples = min_samples
        self.near_miss_threshold = near_miss_threshold
        self.history: Dict[str, Deque[str]] = {}

    def record(self, manifold_name: str, outcome: str, blue_score: float, drift: bool) -> None:
        """
        outcome: "SUCCESS" or "REJECTED"
        status buckets:
          SAFE       -> clean success, no drift, blue above threshold
          NEAR_MISS  -> success but low blue or drift
          CRASH      -> rejected/ruin
        """
        status = "SAFE"
        if outcome != "SUCCESS":
            status = "CRASH"
        elif drift or blue_score < self.near_miss_threshold:
            status = "NEAR_MISS"

        if manifold_name not in self.history:
            self.history[manifold_name] = deque(maxlen=self.window)
        self.history[manifold_name].append(status)

    def adjust_tau(self, manifold_name: str, base_tau: float) -> float:
        """
        If (NEAR_MISS + CRASH)/total exceeds sensitivity, lower tau_R slightly.
        """
        hist = self.history.get(manifold_name)
        if not hist or len(hist) < self.min_samples:
            return base_tau

        unsafe = sum(1 for s in hist if s in {"NEAR_MISS", "CRASH"})
        frac = unsafe / len(hist)
        if frac > self.sensitivity:
            return max(0.05, base_tau - 0.05)
        return base_tau
