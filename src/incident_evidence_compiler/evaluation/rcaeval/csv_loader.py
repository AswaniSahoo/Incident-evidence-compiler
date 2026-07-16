"""Bounded parser for locally extracted RCAEval metric cases."""

import csv
import io
import math
import os
import stat
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from incident_evidence_compiler.domain import (
    CaseId,
    IncidentWindow,
    MetricPoint,
    MetricSignal,
    SignalKey,
)

from .discovery import DiscoveredCase
from .errors import LoadErrorCode, RcaevalLoadError
from .limits import LoaderLimits

_CSV_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True, repr=False)
class ParsedCase:
    window: IncidentWindow
    signals: tuple[MetricSignal, ...]
    row_count: int
    column_count: int

    def __repr__(self) -> str:
        return (
            f"ParsedCase(signal_count={len(self.signals)}, "
            f"row_count={self.row_count}, column_count={self.column_count})"
        )


def _bounded_text(
    path: Path,
    maximum: int,
    too_large: LoadErrorCode,
    case_id: CaseId,
) -> str:
    try:
        with path.open("rb") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > maximum:
                raise RcaevalLoadError(too_large, case_id)
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise RcaevalLoadError(too_large, case_id)
        if b"\x00" in payload:
            raise RcaevalLoadError(LoadErrorCode.INVALID_ENCODING, case_id)
        return payload.decode("utf-8-sig", errors="strict")
    except RcaevalLoadError:
        raise
    except (OSError, UnicodeError):
        raise RcaevalLoadError(LoadErrorCode.INVALID_ENCODING, case_id) from None


def parse_timestamp(raw: str, case_id: CaseId) -> datetime:
    if not raw or raw != raw.strip():
        raise RcaevalLoadError(LoadErrorCode.INVALID_TIMESTAMP, case_id) from None
    try:
        numeric = float(raw)
        if math.isfinite(numeric):
            return datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, ValueError):
        pass
    try:
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        raise RcaevalLoadError(LoadErrorCode.INVALID_TIMESTAMP, case_id) from None


def _number(raw: str, case_id: CaseId) -> float:
    if not raw:
        raise RcaevalLoadError(LoadErrorCode.INVALID_NUMBER, case_id) from None
    try:
        value = float(raw)
    except (OverflowError, ValueError):
        raise RcaevalLoadError(LoadErrorCode.INVALID_NUMBER, case_id) from None
    if not math.isfinite(value):
        raise RcaevalLoadError(LoadErrorCode.NON_FINITE_NUMBER, case_id) from None
    return value


def _validate_logical_record_width(text: str, limits: LoaderLimits, case_id: CaseId) -> None:
    """Reject over-wide logical records before csv.reader materializes their fields."""

    in_quotes = False
    column_count = 1
    index = 0
    while index < len(text):
        character = text[index]
        if character == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif character == "," and not in_quotes:
            column_count += 1
            if column_count > limits.max_columns:
                raise RcaevalLoadError(LoadErrorCode.COLUMN_LIMIT_EXCEEDED, case_id)
        elif character in "\r\n" and not in_quotes:
            column_count = 1
            if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
        index += 1


def _parse_metric_csv(
    text: str,
    limits: LoaderLimits,
    case_id: CaseId,
) -> tuple[list[str], list[datetime], list[list[MetricPoint]], int]:
    _validate_logical_record_width(text, limits, case_id)
    with _CSV_LOCK:
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(limits.max_field_characters)
            reader = csv.reader(io.StringIO(text), strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise RcaevalLoadError(LoadErrorCode.UNSUPPORTED_CSV_SCHEMA, case_id) from None
            if len(header) > limits.max_columns:
                raise RcaevalLoadError(LoadErrorCode.COLUMN_LIMIT_EXCEEDED, case_id)
            if (
                len(header) < 2
                or header[0] != "time"
                or any(not field for field in header)
                or len(set(header)) != len(header)
            ):
                raise RcaevalLoadError(LoadErrorCode.UNSUPPORTED_CSV_SCHEMA, case_id)

            timestamps: list[datetime] = []
            columns: list[list[MetricPoint]] = [[] for _ in header[1:]]
            row_count = 0
            for row in reader:
                if len(row) > limits.max_columns:
                    raise RcaevalLoadError(LoadErrorCode.COLUMN_LIMIT_EXCEEDED, case_id)
                row_count += 1
                if row_count > limits.max_data_rows:
                    raise RcaevalLoadError(LoadErrorCode.ROW_LIMIT_EXCEEDED, case_id)
                if len(row) != len(header):
                    raise RcaevalLoadError(LoadErrorCode.ROW_WIDTH_MISMATCH, case_id)
                observed_at = parse_timestamp(row[0], case_id)
                if timestamps and timestamps[-1] >= observed_at:
                    raise RcaevalLoadError(LoadErrorCode.TIMESTAMPS_NOT_ORDERED, case_id)
                timestamps.append(observed_at)
                for column_index, raw in enumerate(row[1:]):
                    columns[column_index].append(MetricPoint(observed_at, _number(raw, case_id)))
            if row_count == 0:
                raise RcaevalLoadError(LoadErrorCode.UNSUPPORTED_CSV_SCHEMA, case_id)
            return header, timestamps, columns, row_count
        except RcaevalLoadError:
            raise
        except csv.Error as exc:
            code = (
                LoadErrorCode.FIELD_TOO_LONG
                if "field larger" in str(exc)
                else LoadErrorCode.UNSUPPORTED_CSV_SCHEMA
            )
            raise RcaevalLoadError(code, case_id) from None
        finally:
            csv.field_size_limit(previous)


def parse_case(
    discovered: DiscoveredCase,
    case_id: CaseId,
    limits: LoaderLimits,
) -> ParsedCase:
    text = _bounded_text(
        discovered.metric_file,
        limits.max_metric_file_bytes,
        LoadErrorCode.METRIC_FILE_TOO_LARGE,
        case_id,
    )
    header, timestamps, columns, row_count = _parse_metric_csv(text, limits, case_id)
    injection_text = _bounded_text(
        discovered.injection_file,
        limits.max_inject_time_file_bytes,
        LoadErrorCode.INJECTION_FILE_TOO_LARGE,
        case_id,
    ).strip()
    injection = parse_timestamp(injection_text, case_id)
    try:
        end = timestamps[-1] + timedelta(microseconds=1)
        window = IncidentWindow(timestamps[0], injection, end)
        signals = tuple(
            MetricSignal(SignalKey(name), points)
            for name, points in zip(header[1:], columns, strict=True)
        )
    except (OverflowError, ValueError):
        raise RcaevalLoadError(LoadErrorCode.INVALID_TIMESTAMP, case_id) from None
    return ParsedCase(window, signals, row_count, len(header))
