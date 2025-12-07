from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .governor import GovernorConfig
from .interpretant import (
    InterpretantHypothesis,
    PhoneticVariantManifold,
    StrictSetManifold,
)


@dataclass(frozen=True)
class InterpretantSpec:
    id: str
    description: str
    manifold_id: str
    prior: float = 1.0
    likelihood_keyword: Optional[str] = None  # legacy single keyword support
    likelihood_keywords: Optional[List[str]] = None
    likelihood_boost: float = 1.0


@dataclass(frozen=True)
class ManifoldEntry:
    id: str
    family: str
    description: Optional[str] = None
    governor_overrides: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestSpec:
    interpretants: List[InterpretantSpec]
    manifolds: Dict[str, ManifoldEntry]


def _import_yaml():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PyYAML is required to load manifest definitions. Install with `pip install pyyaml`."
        ) from exc
    return yaml


def load_manifest_spec(path: str) -> ManifestSpec:
    yaml = _import_yaml()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    interpretants: List[InterpretantSpec] = []
    for item in data.get("interpretants", []):
        interpretants.append(
            InterpretantSpec(
                id=str(item["id"]),
                description=str(item.get("description", "")),
                manifold_id=str(item["manifold_id"]),
                prior=float(item.get("prior", 1.0)),
                likelihood_keyword=(
                    str(item["likelihood"].get("keyword"))
                    if item.get("likelihood")
                    else None
                ),
                likelihood_keywords=(
                    list(item["likelihood"].get("keywords"))
                    if item.get("likelihood") and item["likelihood"].get("keywords")
                    else None
                ),
                likelihood_boost=float(item.get("likelihood", {}).get("boost", 1.0)),
            )
        )

    manifolds: Dict[str, ManifoldEntry] = {}
    for family, payload in (data.get("families") or {}).items():
        for entry in payload.get("manifolds", []):
            mid = str(entry["id"])
            manifolds[mid] = ManifoldEntry(
                id=mid,
                family=str(family),
                description=entry.get("description"),
                governor_overrides=dict(entry.get("governor", {})),
            )

    return ManifestSpec(interpretants=interpretants, manifolds=manifolds)


def _keyword_likelihood(keywords: Sequence[str], boost: float) -> Callable[[Any], float]:
    lowered = [k.lower() for k in keywords]

    def _fn(sign: Any) -> float:
        # Attribute-aware keyword check (flags or text).
        attrs: Dict[str, Any] = {}
        if hasattr(sign, "__dict__"):
            attrs = dict(vars(sign))
        for key, val in attrs.items():
            key_l = key.lower()
            for kw in lowered:
                if kw in key_l and bool(val):
                    return boost

        # Coarse text surface for matching keyword hints.
        if hasattr(sign, "text"):
            text = str(getattr(sign, "text"))
        elif hasattr(sign, "letters"):
            text = str(getattr(sign, "letters"))
        elif attrs:
            text = ""
        else:
            text = str(sign)
        haystack = text.lower()
        return boost if any(k in haystack for k in lowered) else 1.0

    return _fn


def _lazy_radicular(_: Any) -> Any:
    from ..manifolds.clinical import RadicularSpasmManifold  # local import to avoid cycles

    return RadicularSpasmManifold()


def _lazy_cauda(_: Any) -> Any:
    from ..manifolds.clinical import CaudaEquinaManifold  # local import to avoid cycles

    return CaudaEquinaManifold()


def _lazy_blue(_: Any) -> Any:
    from ..manifolds.red_blue import BlueChannelManifold  # local import to avoid cycles

    return BlueChannelManifold()


def _lazy_red(_: Any) -> Any:
    from ..manifolds.red_blue import RedChannelManifold  # local import to avoid cycles

    return RedChannelManifold()


DEFAULT_MANIFOLD_REGISTRY: Dict[str, Callable[[Any], Any]] = {
    "strict_set": lambda _: StrictSetManifold(),
    "phonetic_variant": lambda _: PhoneticVariantManifold(),
    "radicular_spasm": _lazy_radicular,
    "cauda_equina": _lazy_cauda,
    "blue_channel": _lazy_blue,
    "red_channel": _lazy_red,
}


def build_interpretants_from_spec(
    spec: ManifestSpec,
    *,
    registry: Optional[Dict[str, Callable[[Any], Any]]] = None,
    strict: bool = False,
    families: Optional[List[str]] = None,
) -> List[InterpretantHypothesis[Any, Any]]:
    reg = dict(DEFAULT_MANIFOLD_REGISTRY)
    if registry:
        reg.update(registry)

    hypotheses: List[InterpretantHypothesis[Any, Any]] = []
    for interpretant in spec.interpretants:
        manifold_entry = spec.manifolds.get(interpretant.manifold_id)
        if families and manifold_entry and manifold_entry.family not in families:
            continue

        factory = reg.get(interpretant.manifold_id)
        if factory is None:
            if strict:
                raise ValueError(f"No manifold factory registered for '{interpretant.manifold_id}'.")
            continue
        likelihood_fn = None
        keywords: List[str] = []
        if interpretant.likelihood_keyword:
            keywords.append(interpretant.likelihood_keyword)
        if interpretant.likelihood_keywords:
            keywords.extend(interpretant.likelihood_keywords)
        if keywords:
            likelihood_fn = _keyword_likelihood(
                keywords,
                interpretant.likelihood_boost,
            )
        hypotheses.append(
            InterpretantHypothesis(
                id=interpretant.id,
                description=interpretant.description,
                manifold_factory=factory,
                prior=interpretant.prior,
                likelihood_fn=likelihood_fn,
            )
        )
    return hypotheses


def build_governor_configs(
    spec: ManifestSpec,
    defaults: Optional[GovernorConfig] = None,
    families: Optional[List[str]] = None,
) -> Dict[str, GovernorConfig]:
    base = defaults or GovernorConfig()
    configs: Dict[str, GovernorConfig] = {}
    for mid, entry in spec.manifolds.items():
        if families and entry.family not in families:
            continue
        if not entry.governor_overrides:
            continue
        cfg_dict = {
            **base.__dict__,
            **entry.governor_overrides,
        }
        configs[mid] = GovernorConfig(**cfg_dict)
    return configs


__all__ = [
    "DEFAULT_MANIFOLD_REGISTRY",
    "InterpretantSpec",
    "ManifestSpec",
    "ManifoldEntry",
    "build_governor_configs",
    "build_interpretants_from_spec",
    "load_manifest_spec",
]
