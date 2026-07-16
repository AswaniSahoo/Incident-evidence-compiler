"""Bounded loader configuration."""

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class LoaderLimits:
    max_metric_file_bytes: int = 67_108_864
    max_inject_time_file_bytes: int = 4_096
    max_data_rows: int = 250_000
    max_columns: int = 2_048
    max_field_characters: int = 65_536
    max_discovered_cases: int = 512
    max_scanned_entries: int = 100_000

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        ):
            raise ValueError("invalid_loader_limits")
