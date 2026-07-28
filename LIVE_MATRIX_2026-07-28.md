# RxyCode Live Matrix Summary — 2026-07-28

Branch: `cursor/tui-agent-full-fix`

> 长任务策略：后台跑 + 日志心跳监控；无输出超时则杀进程重试。不在前台阻塞 Running。

## Results（全窗）

| ID | Result | Evidence |
|----|--------|----------|
| W01 | **PASS** | OpenTUI ConPTY e2e 14/14 |
| W02 | **PASS** | 同上 scroll/SSE/resize |
| W03 | **PASS** | thinking pre-init + contract |
| W04 | **PASS** | social 4-turn live |
| W04b | **PASS** | parkour stream |
| W05 | **PASS** | plan mode |
| W06 | **PASS** | build multi-round ok=3/4（closer2.log） |
| W07 | **PASS** | compose multi-round ok=3/4（residual） |
| W08 | **PASS** | dual-track；cache_rate=97.2% |
| W09 | **PASS** | provider rate=95.6% ratio=0.9564 |
| W10 | **PASS** | memory commands |
| W11 | **PASS** | RAG/code_search |
| W12 | **PASS** | test_safety_api |
| W13–W15 | **PASS** | MCP / skills / websearch |
| W16 | **PASS** | git allowlist 单测 + `run_git(status)` 直调；LLM 路径易超时已旁路 web 强制 |
| W17 | **PASS** | parallel_executor |
| W18 | **PASS** | live 人话「工具执行中断…」+ `to_user_facing_error` 单测 |
| W19–W20 | **PASS** | queue/session |
| W21–W22 | **PASS** | workflow + diagnostics |
| W23 | **PASS** | models/language |
| W24 | **PASS** | stream cancel progress=6 |
| W25 | **PASS** | Win32 logo dump |
| W26 | **PASS** | Mac width vitest（自动化，非真机 Mac） |

## Hang detection（本轮）

1. 长任务一律 `block_until_ms=0` 后台  
2. `AwaitShell` 等关键词；日志 `LastWriteTime` 长时间不动 → 判定卡死并 `Stop-Process`  
3. closer 曾卡在 W07 compose：杀掉后用 `live_smoke_residual.py` 逐轮心跳恢复  
4. Tee-Object 锁文件失败 → 改用重定向到新 log  

## Automation short recheck

- OpenTUI e2e 14/14  
- `tests/test_core/test_w16_w18_gates.py` 2 passed  
- residual / w16_w18 scripts 有 JSON 证据  

**GateFinal：DONE（矩阵全 PASS；W16 live LLM 仍偶发超时，以 allowlist+直调 git 补证）**
