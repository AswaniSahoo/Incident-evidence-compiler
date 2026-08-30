# Provenance and Attribution

## Reference prototype

- Repository: https://github.com/yashprogrammer/EnterpriseRAG_live
- Audited commit: `96cbbd3a7e4f012240c48c1fead9c838e9bb1b6b`
- Audit date: 2026-07-16
- Upstream author recorded by Git: `yashprogrammer`

The reference repository was publicly visible but contained no `LICENSE`, `NOTICE`, or `COPYING` file when audited. Its README displayed an MIT badge, which was not treated as a substitute for explicit license text.

## Boundary for this repository

This repository is an independent rewrite:

- No source files are copied from the reference repository.
- No Git history is imported.
- Product requirements come from an implementation audit and are independently expressed.
- New contracts, schemas, tests, migrations, runtime code, documentation, and evaluation artifacts are authored here.
- The reference clone remains read-only and is not a dependency.

## Why the prototype is cited

The audit exposed useful failure cases: model-generated SQL crossing approval boundaries, weak database isolation, blocking work in async endpoints, unverified documentation claims, missing tests, and cache behavior that did not match its API. Those observations motivated the new constraints; they do not transfer ownership of upstream code.

## Publication status

This repository is public and licensed Apache-2.0, decided in ADR 0008 on 2026-07-17. See [`LICENSE`](../LICENSE) and [ADR 0008](decisions/0008-apache-2.0-license.md). RCAEval dataset licensing is separate and documented in [`docs/datasets/rcaeval-re2.md`](datasets/rcaeval-re2.md); the raw benchmark data is never committed.
