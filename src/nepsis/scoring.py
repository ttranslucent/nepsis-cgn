"""
Lightweight scoring utilities for estimating red/blue channel values.

These are intentionally simple heuristics that can be swapped out later
with learned models or domain-specific evaluators.
"""

from typing import Dict


def heuristic_red_score(raw_query: str) -> float:
    """
    Estimate ruin risk. Penalize destructive verbs; clamp to [0, 1].
    """
    tokens = raw_query.lower()
    risk_words = ("delete", "drop", "format", "shutdown")
    base = 0.05
    risk = base + 0.15 * sum(word in tokens for word in risk_words)
    return max(0.0, min(1.0, risk))


def heuristic_blue_score(raw_query: str) -> float:
    """
    Estimate utility potential. Reward longer, specific asks.
    """
    length_bonus = min(len(raw_query) / 200.0, 0.6)
    specificity = 0.2 if "python" in raw_query.lower() else 0.0
    return max(0.0, min(1.0, 0.3 + length_bonus + specificity))


def assess_channel(raw_query: str, tau_r: float = 0.2) -> Dict[str, float]:
    """
    Produce a simple channel assessment dict for convenience.
    """
    red = heuristic_red_score(raw_query)
    blue = heuristic_blue_score(raw_query)
    return {"red": red, "blue": blue, "tau_R": tau_r}
