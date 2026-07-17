"""Async PostgreSQL driver for the persistence boundary.

Imports ``psycopg`` and satisfies the same repository / unit-of-work protocols as the
in-memory fakes. Only this subpackage touches a database; nothing here runs in the
hermetic test gate, and no connection is opened at import time.
"""

from .unit_of_work import PostgresUnitOfWork, PostgresUnitOfWorkFactory

__all__ = ["PostgresUnitOfWork", "PostgresUnitOfWorkFactory"]
