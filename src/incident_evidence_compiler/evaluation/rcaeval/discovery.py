"""Bounded local RCAEval case discovery."""

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import LoadErrorCode, RcaevalLoadError
from .ids import RcaevalSplit
from .limits import LoaderLimits


@dataclass(frozen=True, slots=True, repr=False)
class DiscoveredCase:
    directory: Path
    metric_file: Path
    injection_file: Path
    source_locator: str
    root_cause_service: str
    injected_fault_type: str
    repetition: str

    def __repr__(self) -> str:
        return "DiscoveredCase(redacted=True)"


def validate_root(root: Path, split: RcaevalSplit) -> None:
    try:
        if root.name != f"RE2-{split.value}" or root.is_symlink() or not root.is_dir():
            raise RcaevalLoadError(LoadErrorCode.INVALID_ROOT)
    except OSError:
        raise RcaevalLoadError(LoadErrorCode.INVALID_ROOT) from None


def _layout(case_directory: Path) -> tuple[str, str, str]:
    label = case_directory.parent.name
    parts = label.split("_")
    if len(parts) != 2 or not all(parts) or not case_directory.name:
        raise RcaevalLoadError(LoadErrorCode.UNSUPPORTED_CASE_LAYOUT)
    return parts[0], parts[1], case_directory.name


def discover_cases(root: Path, limits: LoaderLimits) -> tuple[DiscoveredCase, ...]:
    discovered: list[DiscoveredCase] = []
    pending = [root]
    scanned = 0
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
            scanned += len(entries)
            if scanned > limits.max_scanned_entries:
                raise RcaevalLoadError(LoadErrorCode.SCAN_LIMIT_EXCEEDED)
            regular_names = {
                entry.name for entry in entries if entry.is_file(follow_symlinks=False)
            }
            selected = (
                "data.csv"
                if "data.csv" in regular_names
                else "simple_metrics.csv"
                if "simple_metrics.csv" in regular_names
                else None
            )
            if selected is not None:
                if "inject_time.txt" not in regular_names:
                    raise RcaevalLoadError(LoadErrorCode.MISSING_INJECTION_TIME)
                service, fault, repetition = _layout(directory)
                discovered.append(
                    DiscoveredCase(
                        directory=directory,
                        metric_file=directory / selected,
                        injection_file=directory / "inject_time.txt",
                        source_locator=directory.relative_to(root).as_posix(),
                        root_cause_service=service,
                        injected_fault_type=fault,
                        repetition=repetition,
                    )
                )
                if len(discovered) > limits.max_discovered_cases:
                    raise RcaevalLoadError(LoadErrorCode.CASE_LIMIT_EXCEEDED)
                continue
            children = [
                Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)
            ]
            pending.extend(reversed(children))
    except RcaevalLoadError:
        raise
    except OSError:
        raise RcaevalLoadError(LoadErrorCode.INVALID_ROOT) from None
    return tuple(discovered)
