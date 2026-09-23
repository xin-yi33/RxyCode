# ADR: First-party module inventory and development order

Date: 2026-09-01
Status: accepted
Worktree: `D:\agent-demo\RxyCode-phase-g-integrate` (feat/phase-g-integrate)

## Context

The tree grew Phase G surfaces, a plugin hub, expert teams, and Desktop chrome
without a single enumerable map of modules, public surfaces, or test seams.
Development docs did not say what may run in parallel. Adding a plugin store
looked like it might require editing `core/graph.py`.

## Decision

1. `docs/modules/catalog.yaml` is the machine-readable inventory. Every
   repo-root Python package (`__init__.py`) is listed with purpose, public
   surface, inbound/outbound dependencies, and how-to-test.
2. `docs/development-order.yaml` (+ `docs/DEVELOPMENT-ORDER.md`) is the
   sequence: architecture → adapter contract → (GitHub OAuth ‖ Canva OAuth ‖
   computer-use adapter ‖ secret injection) → quality. Plugin OAuth **must
   wait** for architecture/adapter.
3. New connectors register as `plugins/catalog.json` data plus a package.
   Adapter/connect code must not import the agent graph.
4. Structural moves are recorded here, in `docs/decisions/G-PROTOCOL-031.md`
   for wire changes, and in `CHANGELOG.md` `[Unreleased]`.

## Consequences

- `tests/test_module_inventory.py` fails if a new top-level package is added
  without a catalog entry, or if the order doc loses its parallel/wait marks.
- Implementers add features by following the catalog dependency arrows, not by
  splicing into `AgentV2` / `graph.py`.
