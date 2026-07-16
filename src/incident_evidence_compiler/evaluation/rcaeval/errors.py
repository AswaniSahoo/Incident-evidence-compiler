"""Stable, sanitized RCAEval adapter errors."""

from enum import StrEnum

from incident_evidence_compiler.domain import CaseId


class LoadErrorCode(StrEnum):
    INVALID_SPLIT = "invalid_split"
    SPLIT_RESERVED = "split_reserved"
    SEALED_SPLIT_DENIED = "sealed_split_denied"
    INVALID_ROOT = "invalid_root"
    SCAN_LIMIT_EXCEEDED = "scan_limit_exceeded"
    CASE_LIMIT_EXCEEDED = "case_limit_exceeded"
    MISSING_INJECTION_TIME = "missing_injection_time"
    UNSUPPORTED_CASE_LAYOUT = "unsupported_case_layout"
    UNSUPPORTED_CSV_SCHEMA = "unsupported_csv_schema"
    METRIC_FILE_TOO_LARGE = "metric_file_too_large"
    INJECTION_FILE_TOO_LARGE = "injection_file_too_large"
    INVALID_ENCODING = "invalid_encoding"
    FIELD_TOO_LONG = "field_too_long"
    ROW_LIMIT_EXCEEDED = "row_limit_exceeded"
    COLUMN_LIMIT_EXCEEDED = "column_limit_exceeded"
    ROW_WIDTH_MISMATCH = "row_width_mismatch"
    INVALID_TIMESTAMP = "invalid_timestamp"
    TIMESTAMPS_NOT_ORDERED = "timestamps_not_ordered"
    INVALID_NUMBER = "invalid_number"
    NON_FINITE_NUMBER = "non_finite_number"
    INVALID_CASE_ID = "invalid_case_id"
    CASE_ID_COLLISION = "case_id_collision"
    SIDECAR_WRITE_FAILED = "sidecar_write_failed"


class RcaevalLoadError(Exception):
    """An adapter failure that reveals only a stable code and opaque case ID."""

    def __init__(self, code: LoadErrorCode, case_id: CaseId | None = None) -> None:
        self.code = code
        self.case_id = case_id
        super().__init__(str(self))

    def __str__(self) -> str:
        suffix = f" case_id={self.case_id}" if self.case_id is not None else ""
        return f"rcaeval load failed [{self.code}]{suffix}"

    def __repr__(self) -> str:
        return f"RcaevalLoadError(code='{self.code}', case_id={self.case_id!r})"
