"""Formatters shared by the two demo drivers, so both print a report the same way.

``scripts`` is a plain directory, not a package: Python puts a script's own directory first on
``sys.path``, so ``from _demo_common import ...`` resolves for anything run as
``python scripts/<driver>.py``. Tests load this file by path instead.

The report these functions read is served by ``GET /investigations/{id}/report``. Every float in
it is serialized as ``float.hex()`` (ADR 0019, exact round-trip, no decimal drift), so display
means decoding with ``float.fromhex`` first. The payload is our own API's output, but a demo that
crashes in front of a reader is worse than one that says a field was unreadable, so neither
formatter raises: a shape it does not recognise degrades to a single honest line.

Standard library only.
"""

from typing import Any

_NOT_PRESENT = "baseline ranking: not present (report predates migration 0002)"
_UNAVAILABLE = "baseline ranking: unavailable"
_KINDS = ("ranking", "abstention")
_MAX_KEY_LENGTH = 80


def _display(value: object) -> str:
    """Render one telemetry-derived string safely on a terminal.

    A signal key comes from a CSV header or a Prometheus label, so it is untrusted text. Only
    printable characters reach the console, and the length is bounded.
    """
    if not isinstance(value, str):
        raise TypeError("expected a string")
    printable = "".join(character if character.isprintable() else "?" for character in value)
    return printable[:_MAX_KEY_LENGTH]


def _number(value: object) -> float:
    """Decode one serialized float."""
    if not isinstance(value, str):
        raise TypeError("expected a hex-encoded float")
    return float.fromhex(value)


def _direction(signed_score: float) -> str:
    if signed_score > 0.0:
        return "increase"
    if signed_score < 0.0:
        return "decrease"
    return "flat"


def _candidate_row(candidate: object) -> tuple[str, str, str]:
    if not isinstance(candidate, dict):
        raise TypeError("expected a candidate object")
    key = _display(candidate["signal_key"])
    suspicion = _number(candidate["suspicion_score"])
    direction = _direction(_number(candidate["signed_score"]))
    return key, f"suspicion={suspicion:.2f}", direction


def _render_ranking(ranking: object, limit: int) -> str:
    if not isinstance(ranking, dict):
        raise TypeError("expected a baseline ranking object")
    kind = ranking["kind"]
    if kind not in _KINDS:
        raise ValueError("unrecognised baseline ranking kind")
    policy = ranking["policy"]
    if not isinstance(policy, dict):
        raise TypeError("expected a policy object")
    minimum_score = _number(policy["minimum_score"])
    candidates = ranking["candidates"]
    if not isinstance(candidates, list):
        raise TypeError("expected a candidate list")
    if kind == "ranking" and not candidates:
        raise ValueError("a ranking carries at least one candidate")

    lines = [
        f"baseline ranking (deterministic, no model): kind={kind} minimum_score={minimum_score:.2f}"
    ]
    if kind == "abstention":
        reason = ranking.get("abstention_reason")
        lines.append(f"  abstained: {_display(reason) if reason else 'unspecified'}")

    shown = [_candidate_row(candidate) for candidate in candidates[:limit]]
    key_width = max((len(key) for key, _, _ in shown), default=0)
    score_width = max((len(score) for _, score, _ in shown), default=0)
    for position, (key, score, direction) in enumerate(shown, start=1):
        lines.append(
            f"  {position}. {key.ljust(key_width)}   {score.ljust(score_width)}"
            f"  direction={direction}"
        )
    hidden = len(candidates) - len(shown)
    if hidden > 0:
        lines.append(f"  ... and {hidden} more candidates")
    return "\n".join(lines)


def format_baseline_ranking(report: dict[str, Any], *, limit: int = 5) -> str:
    """Render the deterministic baseline ranking carried beside a verified report.

    ``report`` is the whole ``GET /investigations/{id}/report`` body. Reports written before
    migration 0002 have no ranking at all, which is stated rather than hidden.
    """
    try:
        ranking = report.get("baseline_ranking")
        if ranking is None:
            return _NOT_PRESENT
        return _render_ranking(ranking, limit)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return _UNAVAILABLE


def format_predicates(report: dict[str, Any]) -> str:
    """Render one line per verified predicate, or empty text when there are none."""
    try:
        payload = report.get("report") or {}
        predicates = payload.get("predicate_results") or []
        lines = []
        for predicate in predicates:
            supporting = predicate.get("supporting_evidence_ids") or []
            contradicting = predicate.get("contradicting_evidence_ids") or []
            lines.append(
                f"  {_display(predicate.get('predicate_id', '?'))}:"
                f" {_display(predicate.get('verdict', '?'))}"
                f" observed={predicate.get('observed_direction')}"
                f" supporting={len(supporting)}"
                f" contradicting={len(contradicting)}"
            )
        return "\n".join(lines)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return "  predicates: unavailable"
