# RxyCode Live Matrix Summary — 2026-07-28

Branch: `cursor/tui-agent-full-fix` · Full report: `C:\Users\Administrator\Desktop\RxyCode-live-matrix-2026-07-28.md`

## Results

| ID | Result | Note |
|----|--------|------|
| W01 | SKIP | No interactive OpenTUI cursor evidence (Ink ConPTY e2e ≠ U1) |
| W02 | SKIP | No OpenTUI ScrollBox interactive scroll session |
| W03 | **PASS** | `/thinking` before agent init 0.016s + post-init toggle; regression test ✓ |
| W04 | **PASS** | Live `/chat` social multi-round **4 turns**, no synthesizer jargon |
| W04b | PARTIAL | `/chat/stream` 371s: 63 progress + tool events; ended `APIConnectionError` (not PASS) |
| W05 | **PASS** | `/plan` mode_changed + plan-mode chat ok |
| W06 | PARTIAL | `/build` mode_changed; full edit+test not completed (see W04b) |
| W07 | PARTIAL | `/compose` mode_changed; compose replan loop not fully exercised |
| W08 | PARTIAL | `/status` + `/cache` dual-track OK; same-question hit retest not run |
| W09 | SKIP | Provider `cache_rate=0.0%` N/A for ≥85% gate |
| W10 | PARTIAL | list/search OK; add blocked while still in Plan mode (runner now `/build` first) |
| W11–W15 | SKIP | RAG/Safety/MCP/Skills/Web not exercised |
| W16 | PARTIAL | git asked via `/chat`; model did not run git (web-search refusal) |
| W17–W18 | SKIP | Sub-agent / recovery not exercised |
| W19 | **PASS** | `/queue` add/list/remove + `/schedule list` |
| W20 | **PASS** | `/save-chat` + `/list-chats` + `/load-chat` |
| W21–W22 | SKIP | Workflow / LSP not exercised |
| W23 | **PASS** | `/models` + `/language` en/zh (zh toggle had one client timeout) |
| W24 | PARTIAL | frontend e2e Ctrl+C cancel stream ✓; live Esc mid-stream not driven |
| W25 | PARTIAL | logo matrix automated; no Win32 screenshot |
| W26 | SKIP | No macOS runner |

## Automation green

- Thinking pre-init regression: `test_thinking_toggle_before_agent_init_is_fast` **PASS**
- Frontend PTY e2e: **19/19** + crash **2/2**
- OpenTUI `bun run probe`: started, rendered ScrollBox `probe-line-*` stickyScroll; no interactive scroll proof → not W01/W02 PASS
- Live smoke JSON: `scripts/live_smoke_output.json` · window index: `scripts/live_smoke_windows.json`

## Newly covered (vs prior smoke)

W03 PASS (was PARTIAL), W05/W19/W20/W23 PASS, W04 multi-round 4 turns, W04b stream evidence, W06/W07/W10/W16/W24 PARTIAL

## DONE_WITH_CONCERNS — remaining SKIP

W01, W02, W09, W11, W12, W13, W14, W15, W17, W18, W21, W22, W26
