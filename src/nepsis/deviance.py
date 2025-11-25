from collections import deque
from typing import Deque, Dict, Optional


class DevianceMonitor:
    """
    Tracks near-misses per manifold and adjusts tau_R recommendations.
    """

    def __init__(self, sensitivity: float = 0.5, window: int = 50, min_samples: int = 10):
        self.sensitivity = sensitivity
        self.window = window
        self.min_samples = min_samples
        self.history: Dict[str, Deque[str]] = {}

    def record(self, manifold_name: str, outcome: str, blue_score: float, drift: bool) -> None:
        """
        outcome: "SUCCESS" or "REJECTED"
        near-miss if success with low blue or any drift, or rejection.
        """
        status = "HIT"
        if outcome != "SUCCESS" or blue_score < 1.0 or drift:
            status = "NEAR_MISS"

        if manifold_name not in self.history:
            self.history[manifold_name] = deque(maxlen=self.window)
        self.history[manifold_name].append(status)

    def adjust_tau(self, manifold_name: str, base_tau: float) -> float:
        """
        If near-miss fraction exceeds sensitivity, lower tau_R slightly.
        """
        hist = self.history.get(manifold_name)
        if not hist or len(hist) < self.min_samples:
            return base_tau

        near = sum(1 for s in hist if s == "NEAR_MISS")
        frac = near / len(hist)
        if frac > self.sensitivity:
            return max(0.05, base_tau - 0.05)
        return base_tau
