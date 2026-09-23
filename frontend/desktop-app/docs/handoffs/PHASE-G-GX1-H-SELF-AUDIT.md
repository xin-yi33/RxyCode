# GX1-H self-audit

- Branch: `feat/phase-g-frontend` (no `feat/gxN`, no backend merge)
- Protocol: none added; `appserver/` and `protocol/schema.json` untouched
- Projection is a total function over H5 `ThreadStatus` + `TurnStatus` + GX1 examples
- Unknown/failed/cancelled/blocked → Active + Error badge (no silent drop)
- Drag only Drafts↔Active
- Ready cards expose Review entry
- Five states: empty / loading / error / narrow / dark
- Renderer consumes store projection only (DC-J1–J8)
- Tests: `src/features/board/BoardView.test.ts` (node --test; `.tsx` cannot load under node type-stripping)
- Glue: `src/app/views/` + `src/app/router.ts` + minimal App topbar / Cmd+K
