from __future__ import annotations

from nepsis.scoring import heuristic_red_score


def test_red_score_matches_risk_words_on_word_boundaries() -> None:
    assert heuristic_red_score("please drop the table") == 0.2
    assert heuristic_red_score("format the disk") == 0.2


def test_red_score_does_not_match_risk_words_as_substrings() -> None:
    assert heuristic_red_score("share information about dropdown menus") == 0.05
