# ARCH-002: 七条演化缝与变更预算

## Status
Accepted

## Date
2026-09-01

## Context
用户优化 harness（学 Codex）时会碰到「所有沾边文件」。as-is 审计显示上帝文件与循环 import。需要可独立演化的缝。

## Decision
钉死七缝：harness / isolation / tools.edit / hooks / plugin-host / Computer Use / 表面。  
每条缝有允许改与禁止顺手改。加号、skill、MCP 三层信息架构，禁止混成一个宿主大框。

完整表：[MODULE-BOUNDARIES.md](../plans/opus5-plan/rxycode/architecture/MODULE-BOUNDARIES.md)。

## Alternatives Considered

### 继续往 agent_v2.py 加分支
- Rejected：6850 行已暴雷；高星项目不这样维护。

### 为每个缝复制一套 loop
- Rejected：ARCH-001。

## Consequences
「抄 Codex 优化 harness」= 只开工 harness 缝 + 其测试/evals。  
本目标不执行拆代码；拆核卡在 DEV-ORDER SP*。
