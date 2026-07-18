"""HTTP control-plane adapter (FastAPI).

A thin edge over the application use-cases. Importing this package pulls FastAPI but opens
no network; the ASGI app is created explicitly via ``create_app``.
"""

from .app import create_app
from .auth import TokenRegistry

__all__ = ["TokenRegistry", "create_app"]
