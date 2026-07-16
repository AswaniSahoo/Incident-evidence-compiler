"""Bounded, label-safe RCAEval RE2 evaluation adapter."""

from .adapter import EvaluationBatch, InvestigationCase, RcaevalAdapter
from .errors import LoadErrorCode, RcaevalLoadError
from .ids import RcaevalSplit, SealedSplitPermit, authorize_sealed_split, random_case_id
from .limits import LoaderLimits
from .manifest import ArchiveRecord, LicenseNotice, RcaevalManifest, load_manifest
from .sidecar import EvaluationSidecar, SidecarEntry, persist_sidecar, sidecar_json

__all__ = [
    "ArchiveRecord",
    "EvaluationBatch",
    "EvaluationSidecar",
    "InvestigationCase",
    "LicenseNotice",
    "LoadErrorCode",
    "LoaderLimits",
    "RcaevalAdapter",
    "RcaevalLoadError",
    "RcaevalManifest",
    "RcaevalSplit",
    "SealedSplitPermit",
    "SidecarEntry",
    "authorize_sealed_split",
    "load_manifest",
    "persist_sidecar",
    "random_case_id",
    "sidecar_json",
]
