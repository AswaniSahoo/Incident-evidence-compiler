"""Strict reader for the committed RCAEval provenance manifest."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

_HEX40 = re.compile(r"[0-9a-f]{40}")
_MD5 = re.compile(r"[0-9a-f]{32}")
_EXPECTED_ARCHIVES = {
    "OB": (
        "RE2-OB.zip",
        "development_calibration",
        1_191_025_569,
        "b9e23f8842c404b396ffd2becff15de4",
    ),
    "SS": (
        "RE2-SS.zip",
        "reserved",
        245_629_018,
        "bd747a8fc7c5be00c613e13fbf9dd74b",
    ),
    "TT": (
        "RE2-TT.zip",
        "sealed_evaluation",
        2_801_345_134,
        "a7fbcd1ada406067dcc50771ae398408",
    ),
}
_TOP_KEYS = {
    "schema_version",
    "dataset",
    "repository_url",
    "release",
    "annotated_tag_object",
    "release_commit",
    "archive_record_url",
    "archive_api_url",
    "record_doi",
    "metadata_publication_date",
    "record_created_at",
    "metadata_retrieved_on",
    "raw_redistribution",
    "archives",
    "license_notices",
}


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    split: str
    filename: str
    role: str
    bytes: int
    checksum_algorithm: str
    checksum_value: str


@dataclass(frozen=True, slots=True)
class LicenseNotice:
    source: str
    identifier: str
    note: str


@dataclass(frozen=True, slots=True)
class RcaevalManifest:
    schema_version: int
    dataset: str
    repository_url: str
    release: str
    annotated_tag_object: str
    release_commit: str
    archive_record_url: str
    archive_api_url: str
    record_doi: str
    metadata_publication_date: date
    record_created_at: datetime
    metadata_retrieved_on: date
    raw_redistribution: bool
    archives: tuple[ArchiveRecord, ...]
    license_notices: tuple[LicenseNotice, ...]


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not all(isinstance(key, str) for key in value)
    ):
        raise ValueError("invalid_manifest")
    return value


def _text(mapping: dict[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_manifest")
    return value


def _https(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("invalid_manifest")
    return value


def _load_manifest(path: Path) -> RcaevalManifest:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        value = _mapping(raw, _TOP_KEYS)
        if value["schema_version"] != 1 or value["raw_redistribution"] is not False:
            raise ValueError("invalid_manifest")
        expected_scalars = {
            "dataset": "RCAEval RE2",
            "repository_url": "https://github.com/phamquiluan/RCAEval",
            "release": "1.2.0",
            "annotated_tag_object": "5f22afb1cd9e383f52c41c2e8e99c8ef930db5d8",
            "release_commit": "bc49dbd85bd14032101fb9a69a5a37e9d6d55178",
            "archive_record_url": "https://zenodo.org/records/14590730",
            "archive_api_url": "https://zenodo.org/api/records/14590730",
            "record_doi": "10.5281/zenodo.14590730",
            "metadata_publication_date": "2024-01-03",
            "record_created_at": "2025-01-03T12:06:03.078444+00:00",
            "metadata_retrieved_on": "2026-07-16",
        }
        if any(value[key] != expected for key, expected in expected_scalars.items()):
            raise ValueError("invalid_manifest")
        tag = _text(value, "annotated_tag_object")
        commit = _text(value, "release_commit")
        if _HEX40.fullmatch(tag) is None or _HEX40.fullmatch(commit) is None:
            raise ValueError("invalid_manifest")
        archives_raw = value["archives"]
        if not isinstance(archives_raw, list):
            raise ValueError("invalid_manifest")
        archives: list[ArchiveRecord] = []
        for raw_archive in archives_raw:
            archive = _mapping(raw_archive, {"split", "filename", "role", "bytes", "checksum"})
            split = _text(archive, "split")
            role = _text(archive, "role")
            size = archive["bytes"]
            checksum = _mapping(archive["checksum"], {"algorithm", "value"})
            checksum_value = _text(checksum, "value")
            if split not in _EXPECTED_ARCHIVES:
                raise ValueError("invalid_manifest")
            expected_filename, expected_role, expected_size, expected_checksum = _EXPECTED_ARCHIVES[
                split
            ]
            if (
                _text(archive, "filename") != expected_filename
                or role != expected_role
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size != expected_size
                or _text(checksum, "algorithm") != "md5"
                or checksum_value != expected_checksum
                or _MD5.fullmatch(checksum_value) is None
            ):
                raise ValueError("invalid_manifest")
            archives.append(
                ArchiveRecord(
                    split,
                    _text(archive, "filename"),
                    role,
                    size,
                    "md5",
                    checksum_value,
                )
            )
        if {archive.split for archive in archives} != set(_EXPECTED_ARCHIVES) or len(archives) != 3:
            raise ValueError("invalid_manifest")
        notices_raw = value["license_notices"]
        if not isinstance(notices_raw, list):
            raise ValueError("invalid_manifest")
        notices = tuple(
            LicenseNotice(
                _text(notice, "source"),
                _text(notice, "identifier"),
                _text(notice, "note"),
            )
            for item in notices_raw
            if (notice := _mapping(item, {"source", "identifier", "note"}))
        )
        if {(notice.source, notice.identifier) for notice in notices} != {
            ("pinned_repository", "MIT"),
            ("zenodo_record_14590730", "CC-BY-4.0"),
        }:
            raise ValueError("invalid_manifest")
        publication = date.fromisoformat(_text(value, "metadata_publication_date"))
        retrieved = date.fromisoformat(_text(value, "metadata_retrieved_on"))
        created = datetime.fromisoformat(_text(value, "record_created_at"))
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("invalid_manifest")
        return RcaevalManifest(
            schema_version=1,
            dataset=_text(value, "dataset"),
            repository_url=_https(_text(value, "repository_url")),
            release=_text(value, "release"),
            annotated_tag_object=tag,
            release_commit=commit,
            archive_record_url=_https(_text(value, "archive_record_url")),
            archive_api_url=_https(_text(value, "archive_api_url")),
            record_doi=_text(value, "record_doi"),
            metadata_publication_date=publication,
            record_created_at=created,
            metadata_retrieved_on=retrieved,
            raw_redistribution=False,
            archives=tuple(archives),
            license_notices=notices,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_manifest") from exc


def load_manifest(path: Path) -> RcaevalManifest:
    """Load pinned provenance without exposing filesystem or malformed-input details."""
    try:
        return _load_manifest(path)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    raise ValueError("invalid_manifest") from None
