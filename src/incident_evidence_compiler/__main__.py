"""Console entrypoint: ``python -m incident_evidence_compiler`` (ADR 0016)."""

import sys

from .runtime.server import main

if __name__ == "__main__":
    sys.exit(main())
