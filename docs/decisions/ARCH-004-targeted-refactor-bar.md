# ARCH-004: 拆 agent_v2 的证据门槛（要拆，本目标不执行）

## Status
Accepted

## Date
2026-09-01

## Context
`core/agent_v2.py` ≈ 6850 行，测试直绑。上一版「本目标不拆」被误读成「永远不拆」。  
调研 [`2026-09-01-top-coding-agents-core-architecture.md`](../plans/opus5-plan/rxycode/architecture/research/2026-09-01-top-coding-agents-core-architecture.md)：Codex 用 crate 子目录消化 15 万行；Cline Task ~3756 行是债；无人以 6000+ 行单文件为美德。

## Decision
**必须按缝拆。** 方法：已有 `Session` 假面软连接 + DEV-ORDER SP0–SP3。  
**本目标 diff 不含** `core/agent_v2.py` 循环改写。  
拆之前：把直绑测试迁到 Session/协议（SP0）。每步 ADR + 测试。禁止顺手大扫除。

`Verdict: Adopt — openai/codex session/tools/sandboxing 目录边界 — 大体量靠模块不是上帝文件。`

## Alternatives Considered

### 永远不拆，继续往里写
- Rejected：与高星对照和用户「暴雷」判断冲突。

### 本目标一次性重写循环
- Rejected：无产品循环 diff 范围；无假面测试会炸。

## Consequences
允许改（未来 SP 卡）：抽出的新模块、`session.py` 接线、测试。  
禁止顺手改：frontend、plugin IA、CU 产品、无关 PHASE 卡。
