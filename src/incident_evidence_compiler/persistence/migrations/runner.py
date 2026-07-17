"""Async, forward-only SQL migration runner.

Applies the ordered ``*.sql`` files in this package exactly once each, recording every
applied version in a ``schema_migrations`` table it owns. Re-running is a no-op. This
module imports ``psycopg`` and is only used on the PostgreSQL path; it never runs in the
hermetic test gate.
"""

from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

_MIGRATIONS_DIR = Path(__file__).resolve().parent

_ENSURE_TABLE = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version text PRIMARY KEY, "
    "applied_at timestamptz NOT NULL DEFAULT now())"
)


def _migration_files() -> list[Path]:
    return sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)


async def applied_versions(connection: AsyncConnection[Any]) -> frozenset[str]:
    """Return the set of already-applied migration versions."""
    async with connection.cursor() as cursor:
        await cursor.execute(_ENSURE_TABLE)
        await cursor.execute("SELECT version FROM schema_migrations")
        rows = await cursor.fetchall()
    await connection.commit()
    return frozenset(str(row[0]) for row in rows)


async def apply_migrations(connection: AsyncConnection[Any]) -> tuple[str, ...]:
    """Apply any unapplied migrations in order; return the versions newly applied."""
    already = await applied_versions(connection)
    newly: list[str] = []
    for path in _migration_files():
        version = path.stem
        if version in already:
            continue
        statements = path.read_text(encoding="utf-8")
        async with connection.cursor() as cursor:
            await cursor.execute(statements)
            await cursor.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (version,),
            )
        await connection.commit()
        newly.append(version)
    return tuple(newly)
