# RxyCode Live Matrix Summary — 2026-07-28

Branch: `cursor/tui-agent-full-fix`

> 收口说明：不再前台跑超长 `live_smoke_runner`（会卡死会话）。下列状态来自**短命令证据**（OpenTUI ConPTY e2e、短 pytest、短 probe）。

## Results

| ID | Result | Evidence |
|----|--------|----------|
| W01 | **PASS** | `frontend/opentui-app` ConPTY e2e 14/14（textarea / paste / cursor `?25h`） |
| W02 | **PASS** | 同上：80 行 SSE、resize、PageUp、无重复 header |
| W03 | **PASS** | `/thinking` pre-init 修复 + contract pytest |
| W04 | **PASS** | 先前 live `/chat` 社交 4 轮无 jargon |
| W04b | **PASS** | 先前 parkour stream ~57s 有答案 |
| W05 | **PASS** | `/plan` mode + chat |
| W06 | PARTIAL | W04b build 落盘有；独立「edit+test」4 轮短复测未跑 |
| W07 | PARTIAL | compose mode_changed 有；完整 replan 环缺短证据重跑（禁超长） |
| W08 | PARTIAL | `/status`+`/cache` 双轨字段 OK；同问 hits 需短 API 复测 |
| W09 | PARTIAL | Provider `cache_rate` 常为 0%；需 provider 真支持才能 ≥85% |
| W10 | **PASS** | memory command 先前 PASS |
| W11 | **PASS** | code_search + RAG 先前 PASS |
| W12 | **PASS** | `tests/test_safety_api.py` approval 契约（短 pytest） |
| W13–W15 | **PASS** | MCP / skills / websearch 先前 PASS |
| W16 | PARTIAL | `GIT_ONLY_TOOL_NAMES` 强制已合入；缺短 live 复测 |
| W17 | **PASS** | `tests/test_core/test_parallel_executor.py` 22 passed |
| W18 | PARTIAL | classify + recover 有单元证据；缺短 live 人话复测 |
| W19–W20 | **PASS** | queue/schedule + save/load chat |
| W21 | **PASS** | `run_workflow_probe` run/status/wait/cancel |
| W22 | **PASS** | diagnostics fixture SyntaxError |
| W23 | **PASS** | models + language |
| W24 | **PASS** | OpenTUI PTY Esc→POST `/cancel` |
| W25 | **PASS** | Win32 WORDMARK dump → `scripts/live_smoke_w25_logo_dump.txt` + Desktop |
| W26 | **PASS** | `frontend/tests/logo.mac-width.test.ts` 26 passed（Mac 宽度自动化，非真机 Mac） |

## Still open (诚实)

- **W07 / W08 / W09 / W16 / W18**：需要短 API 调用才能升 PASS；**禁止**再跑整仓超长 smoke。
- **W09 ≥85%**：若模型/供应商不回 prompt-cache hit，无法在无造假前提下标 PASS。

## Automation (short)

- OpenTUI `bun run e2e` → 14/14
- vitest logo.mac-width → 26/26；logo.matrix 含在 matrix 套件
- pytest config merge + safety_api（本轮短跑）
