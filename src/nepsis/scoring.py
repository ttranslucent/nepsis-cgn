"""Lightweight scoring utilities for estimating red/blue channel values."""

import re
from typing import Dict


RISK_WORDS = ("delete", "drop", "format", "shutdown")


def heuristic_red_score(raw_query: str) -> float:
    """
    Estimate ruin risk. Penalize destructive verbs; clamp to [0, 1].
    """
    tokens = raw_query.lower()
    base = 0.05
    risk = base + 0.15 * sum(bool(re.search(rf"\b{re.escape(word)}\b", tokens)) for word in RISK_WORDS)
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
