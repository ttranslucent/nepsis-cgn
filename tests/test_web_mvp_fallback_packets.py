import json
from pathlib import Path

from nepsis_cgn.core.mvp import build_nepsis_mvp_packet


def _stable_packet(packet: dict) -> dict:
    cleaned = dict(packet)
    cleaned.pop("packet_id", None)
    cleaned.pop("created_at", None)
    cleaned.pop("fallback_source", None)
    return cleaned


def test_web_mvp_fallback_packets_match_canonical_builder() -> None:
    fallback_path = Path("nepsis-web/src/data/mvpPackets.json")
    fallback_packets = json.loads(fallback_path.read_text(encoding="utf-8"))

    assert set(fallback_packets) == {"jailing", "clinical"}
    for case_id in ("jailing", "clinical"):
        fallback = dict(fallback_packets[case_id])
        canonical = build_nepsis_mvp_packet(case_id=case_id)
        assert _stable_packet(fallback) == _stable_packet(canonical)
