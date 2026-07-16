"""Evaluation-only source/label mapping and explicit persistence."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from incident_evidence_compiler.domain import CaseId

from .errors import LoadErrorCode, RcaevalLoadError
from .ids import RcaevalSplit


@dataclass(frozen=True, slots=True, repr=False)
class SidecarEntry:
    case_id: CaseId
    split: RcaevalSplit
    source_locator: str
    root_cause_service: str
    injected_fault_type: str
    repetition: str
    answer_labels: tuple[str, ...]

    def __repr__(self) -> str:
        return f"SidecarEntry(case_id={self.case_id!r}, redacted=True)"


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationSidecar:
    manifest_release: str
    manifest_commit: str
    entries: tuple[SidecarEntry, ...]
    schema_version: int = 1

    def __repr__(self) -> str:
        return f"EvaluationSidecar(entry_count={len(self.entries)})"


def sidecar_json(sidecar: EvaluationSidecar) -> str:
    payload = {
        "schema_version": sidecar.schema_version,
        "manifest_release": sidecar.manifest_release,
        "manifest_commit": sidecar.manifest_commit,
        "entries": {
            str(entry.case_id): {
                "split": entry.split.value,
                "source_locator": entry.source_locator,
                "root_cause_service": entry.root_cause_service,
                "injected_fault_type": entry.injected_fault_type,
                "repetition": entry.repetition,
                "answer_labels": list(entry.answer_labels),
            }
            for entry in sidecar.entries
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def persist_sidecar(
    sidecar: EvaluationSidecar,
    destination: Path,
    *,
    sidecar_root: Path,
) -> None:
    temporary: Path | None = None
    failed = False
    try:
        resolved_root = sidecar_root.resolve()
        resolved_destination = destination.resolve()
        resolved_destination.relative_to(resolved_root)
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved_destination.parent,
            delete=False,
            prefix=".sidecar-",
            suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            stream.write(sidecar_json(sidecar))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, resolved_destination)
    except (OSError, TypeError, ValueError):
        failed = True
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                failed = True
    if failed:
        raise RcaevalLoadError(LoadErrorCode.SIDECAR_WRITE_FAILED) from None
