# RxyCode Live Matrix Summary — 2026-07-28

Branch: `cursor/tui-agent-full-fix` · Full report: `C:\Users\Administrator\Desktop\RxyCode-live-matrix-2026-07-28.md`

## Results

| ID | Result | Note |
|----|--------|------|
| W01 | **PASS** | OpenTUI ConPTY e2e: textarea Enter submit, multi-line input, long line, `?25h` cursor restore |
| W02 | **PASS** | OpenTUI ConPTY e2e: 80-line SSE flood, resize, PageUp scroll path, no duplicate headers |
| W03 | **PASS** | `/thinking` before+after agent init; toggle expands/collapses |
| W04 | **PASS** | `/chat` social multi-round 4 turns, no synthesizer jargon |
| W04b | **PASS** | `/chat/stream` parkour build completed ~57s with answer |
| W05 | **PASS** | `/plan` mode_changed + plan-mode chat ok |
| W06 | PARTIAL | `/build` mode_changed; W04b PASS but full edit+test gate not separately audited |
| W07 | PARTIAL | `/compose` mode_changed; compose replan loop not fully exercised |
| W08 | PARTIAL | `/status` + `/cache` dual-track OK; same-question hit retest not run |
| W09 | SKIP | Provider `cache_rate=0.0%` N/A for ≥85% gate |
| W10 | **PASS** | `/memory` add/list/search via `/command` |
| W11 | **PASS** | `code_search` local + 4-turn RAG chat |
| W12 | PARTIAL | write/bash tools seen; `approval_request` not observed (0 approvals) |
| W13 | **PASS** | MCP list/add/list/remove multi-round (4) |
| W14 | **PASS** | skills list×2 + remove-missing + find-missing (4) |
| W15 | **PASS** | `websearch` tool_call + 4 followups |
| W16 | PARTIAL | chat used websearch/webfetch instead of git tool; local `run_git(status)` ok |
| W17 | PARTIAL | parallel intent unit + multi-round reads; legacy SubAgent disabled |
| W18 | PARTIAL | `classify_error` TRANSIENT + fail-then-recover bash probe |
| W19 | **PASS** | `/queue` add/list/remove + `/schedule list` |
| W20 | **PASS** | `/save-chat` + `/list-chats` + `/load-chat` |
| W21–W22 | SKIP | Workflow / LSP not exercised |
| W23 | **PASS** | `/models` + `/language` en/zh |
| W24 | PARTIAL | OpenTUI PTY Esc→POST `/cancel` PASS; Ink Ctrl+C PASS (prior); live API mid-stream Esc not separately driven |
| W25 | PARTIAL | logo matrix automated; no Win32 screenshot |
| W26 | SKIP | No macOS runner |

## Automation green

- OpenTUI `bun run e2e` (`frontend/opentui-app/e2e/run-pty.mjs`): **14/14 PASS** on Windows ConPTY → W01/W02 **PASS**
- OpenTUI `bun test src/scrollbox.gate.test.tsx` + unit tests: **10/10 PASS** (headless supplement)
- Live smoke: `scripts/live_smoke_output.json` · 30 recorded turns · window index: `scripts/live_smoke_windows.json`
- Ink `frontend/e2e` unchanged (Ink path only)

## Newly covered (this expansion)

W01/W02 PARTIAL→**PASS** (ConPTY), W04b PARTIAL→PASS, W10 PARTIAL→PASS, W11–W15 SKIP→PASS (W12 PARTIAL), W16–W18 SKIP/PARTIAL→PARTIAL with evidence, W13/W14 PASS, OpenTUI Esc `/cancel` parity

## DONE_WITH_CONCERNS — remaining SKIP

W09, W21, W22, W26
