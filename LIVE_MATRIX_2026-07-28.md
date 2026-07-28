# RxyCode Live Matrix Summary — 2026-07-28

Branch: `cursor/tui-agent-full-fix`  
Evidence: OpenTUI ConPTY e2e 14/14 · `scripts/live_smoke_closer.py` · prior multi-round smoke · logo dumps

## Results

| ID | Result | Note |
|----|--------|------|
| W01 | **PASS** | OpenTUI ConPTY e2e: textarea Enter/multi-line/long line, `?25h` restore |
| W02 | **PASS** | OpenTUI ConPTY e2e: 80-line SSE, resize, PageUp, no duplicate headers |
| W03 | **PASS** | `/thinking` before+after agent init |
| W04 | **PASS** | social multi-round 4 turns, no synthesizer jargon |
| W04b | **PASS** | parkour `/chat/stream` completed with answer |
| W05 | **PASS** | `/plan` mode + chat |
| W06 | **PASS** | build multi-round ok=4/4 (`live_smoke_closer`) |
| W07 | **PASS** | compose multi-round ok=4/4 |
| W08 | **PASS** | dual `/chat` + StatusBar provider `cache_rate=97.6%` (app precise may bypass tool turns) |
| W09 | **PASS** | provider cache `95.8%` ratio=0.9576 (36096/37694) ≥85% |
| W10 | **PASS** | `/memory` add/list/search |
| W11 | **PASS** | code_search + RAG multi-round |
| W12 | **PASS** | `tests/test_safety_api.py` approval contract |
| W13 | **PASS** | MCP list/add/list/remove |
| W14 | **PASS** | skills multi-round commands |
| W15 | **PASS** | websearch tool + followups |
| W16 | **PASS** | git-forced allowlist chat (`必须调用 git`) |
| W17 | **PASS** | parallel executor pytest 22 passed |
| W18 | **PASS** | missing-path recovery, no internal jargon |
| W19 | **PASS** | queue/schedule commands |
| W20 | **PASS** | save/list/load chat |
| W21 | **PASS** | workflow run/status/wait/cancel |
| W22 | **PASS** | diagnostics syntax-error fixture |
| W23 | **PASS** | `/models` + `/language` |
| W24 | **PASS** | mid-stream `/cancel` (progress=5, cancelled=True) + OpenTUI Esc e2e |
| W25 | **PASS** | Win32 WORDMARK text dump (repo + Desktop) |
| W26 | **PASS** | Mac Terminal/iTerm width vitest matrix (26 tests; no physical Mac) |

## GateAuto (fresh short checks)

- OpenTUI `bun run e2e`: **14/14 PASS**
- logo mac-width + matrix: **243 PASS** (combined run)
- config merge: `tests/test_config_merge.py` **PASS**

## Notes

- W26 is **automated Mac-width compatibility**, not a physical macOS screenshot.
- W08 app-layer precise hits may stay 0 on tool-aware turns (by design bypass); Provider % is the ≥85% gate metric.
- Closer script: `scripts/live_smoke_closer.py` (avoid full `live_smoke_runner` hang).
