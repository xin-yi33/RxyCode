# ARCH-003: Computer Use 口述覆盖 08-12 冻结

## Status
Accepted

## Date
2026-09-01

## Context
`research/2026-08-12-agent-native-computer-use-research.md` 冻结「像素点击 Computer Use」，改走 CLI-Anything。  
备忘口述：要 Codex 式 **直接控制 + 事实观察**。`cli_list`/`cli_run` 可并存、不得替代。  
PC0：能抄不造。

## Decision
1. 08-12 冻结的是 **像素点击作为默认/唯一软件控制**。
2. 产品要：授权内点/键/滚/切窗口 + **事实观察**（屏幕/窗口/标签的真实数据）。
3. **优先 Extend** [iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use)（MCP+CLI，无障碍树，非自研 CUA）。
4. `cli_list`/`cli_run` **并存不得替代**。
5. 默认关；打开走 PHASE-K 能力层级 L1 会话边界；工具面固定，禁止 N 个截图工具进 S1。
6. 访问档不足拒绝；首次启用审批；失败关闭。

`Verdict: Extend — iFurySt/open-codex-computer-use — 跨平台 MCP，事实观察走 AX/AT-SPI/UIA。`

## Alternatives Considered

### 只用 CLI-Anything 替代 Computer Use
- Rejected：备忘明确禁止。

### 自研截图点击循环写进 agent_v2
- Rejected：token 账、脆弱性（08-12 仍成立）；且违反 PC0。

## Consequences
回写 CAPABILITY-MAP：不再写「截图点击不进入产品」为绝对禁令。  
实现落 PHASE-P PP40–PP42（P2），不在本目标写产品代码。
