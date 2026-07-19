"""Run a Phase 7 evaluation arm against an out-of-repo RCAEval RE2 split.

This CLI is not part of the hermetic gate. It loads an already-extracted split
from a path *outside* the repository (raw data is never committed; see ADR 0009),
runs one arm, and prints or writes an aggregate, label-free metrics artifact. The
baseline arm is deterministic and needs no network; the gemini arm requires
``GEMINI_API_KEY`` and makes live provider calls.

Examples:
    python scripts/run_evaluation.py --root /path/to/RE2/RE2-OB --arm baseline \\
        --out docs/evaluation/re2-ob-baseline.json
    python scripts/run_evaluation.py --root /path/to/RE2/RE2-OB --arm gemini \\
        --provider vertex --project my-gcp-project --location us-central1 \\
        --model gemini-2.5-flash --out docs/evaluation/re2-ob-gemini.json
    GEMINI_API_KEY=... python scripts/run_evaluation.py --root /path/to/RE2/RE2-OB \\
        --arm gemini --provider developer --model gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from incident_evidence_compiler.domain import BaselinePolicy
from incident_evidence_compiler.evaluation.harness import (
    DEFAULT_EVALUATION_POLICY,
    Arm,
    ScaleFloorPolicy,
    evaluate_batch,
)
from incident_evidence_compiler.evaluation.harness.scoring import EvaluationSummary, summary_payload
from incident_evidence_compiler.evaluation.rcaeval import (
    EvaluationBatch,
    RcaevalAdapter,
    RcaevalLoadError,
    RcaevalSplit,
    SealedSplitPermit,
    authorize_sealed_split,
)
from incident_evidence_compiler.llm import GeminiLLMClient, LLMClient


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Path to an extracted split directory named RE2-<SPLIT> (outside the repo).",
    )
    parser.add_argument("--split", default="OB", help="RCAEval RE2 split (default: OB).")
    parser.add_argument(
        "--sealed-confirm",
        metavar="REASON",
        default=None,
        help=(
            "Explicitly authorize opening the sealed RE2-TT split, recording a non-empty "
            'reason (required for --split TT), e.g. --sealed-confirm "final held-out eval".'
        ),
    )
    parser.add_argument(
        "--arm",
        default="baseline",
        choices=[arm.value for arm in Arm],
        help="Evaluation arm to run (default: baseline).",
    )
    parser.add_argument(
        "--provider",
        default="vertex",
        choices=["developer", "vertex"],
        help="Gemini backend for the gemini arm: Developer API key or Vertex AI (default: vertex).",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="Vertex AI billing project id (default: $GOOGLE_CLOUD_PROJECT).",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="Vertex AI location (default: $GOOGLE_CLOUD_LOCATION or us-central1).",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model id for the gemini arm (default: gemini-2.5-flash).",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=120.0,
        help="Per-call provider deadline for the gemini arm (default: 120).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Score only the first N cases (for a cheap pre-check); default all.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max in-flight provider calls for the gemini arm (default: 1).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the artifact here; otherwise print to stdout.",
    )
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=DEFAULT_EVALUATION_POLICY.minimum_score,
        help="Baseline suspicion threshold (robust sigmas).",
    )
    parser.add_argument(
        "--relative-floor-fraction",
        type=float,
        default=ScaleFloorPolicy().relative_floor_fraction,
        help="Per-signal scale floor as a fraction of the signal's median magnitude.",
    )
    return parser.parse_args(argv)


def _build_artifact(
    batch: EvaluationBatch,
    summary: EvaluationSummary,
    *,
    arm: Arm,
    split: str,
    policy: BaselinePolicy,
    floor_policy: ScaleFloorPolicy,
    model: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "arm": arm.value,
        "model": model,
        "dataset": {
            "name": "RCAEval RE2",
            "split": split,
            "release": batch.sidecar.manifest_release,
            "release_commit": batch.sidecar.manifest_commit,
            "skipped_case_count": batch.skipped_case_count,
        },
        "config": {
            "minimum_points_per_window": policy.minimum_points_per_window,
            "minimum_score": policy.minimum_score,
            "minimum_margin": policy.minimum_margin,
            "relative_scale_floor": policy.relative_scale_floor,
            "scale_floor_relative_fraction": floor_policy.relative_floor_fraction,
            "scale_floor_absolute_epsilon": floor_policy.absolute_epsilon,
        },
        "metrics": summary_payload(summary),
        "notes": (
            "Aggregate, label-free metrics over the RCAEval RE2 development split. "
            "Per-case ground truth and source locators are never emitted. Raw data is "
            "never committed (ADR 0009)."
        ),
    }


def _build_sealed_permit(args: argparse.Namespace) -> SealedSplitPermit | None:
    """Turn the CLI's sealed-split flags into a permit, or refuse.

    Only the sealed RE2-TT split needs a permit; every other split loads with ``None``.
    Opening TT demands both ``--sealed-confirm`` and a non-empty ``--sealed-reason`` so the
    irreversible held-out run is never a silent default. The reason is recorded on the permit
    but never reaches model context.
    """
    if args.split != RcaevalSplit.TT.value:
        return None
    reason = args.sealed_confirm
    if not (reason and reason.strip()):
        print(
            'split TT is sealed: pass --sealed-confirm "<reason>" with a non-empty reason '
            "to open it.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return authorize_sealed_split(confirmed=True, reason=reason)


def _make_llm_client(args: argparse.Namespace) -> LLMClient:
    deadline = timedelta(seconds=args.deadline_seconds)
    if args.provider == "vertex":
        if not args.project:
            print("vertex provider requires --project or $GOOGLE_CLOUD_PROJECT.", file=sys.stderr)
            raise SystemExit(2)
        return GeminiLLMClient.from_vertex(
            project=args.project, location=args.location, model=args.model, deadline=deadline
        )
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set; the developer provider requires it.", file=sys.stderr)
        raise SystemExit(2)
    return GeminiLLMClient.from_api_key(api_key, model=args.model, deadline=deadline)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    arm = Arm(args.arm)
    policy = BaselinePolicy(
        minimum_points_per_window=DEFAULT_EVALUATION_POLICY.minimum_points_per_window,
        minimum_score=args.minimum_score,
        minimum_margin=DEFAULT_EVALUATION_POLICY.minimum_margin,
        relative_scale_floor=DEFAULT_EVALUATION_POLICY.relative_scale_floor,
    )
    floor_policy = ScaleFloorPolicy(relative_floor_fraction=args.relative_floor_fraction)

    sealed_permit = _build_sealed_permit(args)
    try:
        batch = RcaevalAdapter().load(
            args.root,
            args.split,
            sealed_permit=sealed_permit,
            skip_unparsable_cases=True,
        )
    except RcaevalLoadError as error:
        print(f"failed to load split [{error.code}]", file=sys.stderr)
        return 1

    llm_client = _make_llm_client(args) if arm is Arm.GEMINI else None
    summary = asyncio.run(
        evaluate_batch(
            batch,
            arm=arm,
            policy=policy,
            floor_policy=floor_policy,
            llm_client=llm_client,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    )
    artifact = _build_artifact(
        batch,
        summary,
        arm=arm,
        split=args.split,
        policy=policy,
        floor_policy=floor_policy,
        model=args.model if arm is Arm.GEMINI else None,
    )
    rendered = json.dumps(artifact, indent=2, sort_keys=True) + "\n"

    if args.out is None:
        sys.stdout.write(rendered)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.out} ({summary.case_count} cases)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
