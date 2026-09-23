"""Human-readable scorecards. Agent-only; peers are other published agents."""

from __future__ import annotations

from typing import Any

# Published numbers, not same-day same-model. Stars fetched 2026-09-08 via GitHub API
# where noted; SWE-bench / GAIA from papers and project eval pages.

OSS_AGENT_PEERS = [
    {
        "name": "OpenHands",
        "repo": "OpenHands/OpenHands",
        "stars": "87k",
        "bfcl": "未公布 agent BFCL",
        "gaia": "Versa 51.2% test / 64.2% val（Claude 3.7，arXiv:2506.03011）；v0.28.1 37.2% test",
        "chateval": "未公布 ChatEval/MT-Bench agent 分",
        "other": "SWE-bench 是主榜",
    },
    {
        "name": "Magentic-One (AutoGen)",
        "repo": "microsoft/autogen",
        "stars": "61k",
        "bfcl": "未公布",
        "gaia": "38% official test（GPT-4o+o1，arXiv:2411.04468）；GPT-4o 32.3%",
        "chateval": "未公布",
        "other": "WebArena 32.8%；论文系统，不是桌面 coding agent",
    },
    {
        "name": "Aider",
        "repo": "Aider-AI/aider",
        "stars": "49k",
        "bfcl": "未公布",
        "gaia": "未公布",
        "chateval": "未公布",
        "other": "公开主榜是 polyglot / SWE-bench 变体，不是 GAIA/BFCL",
    },
    {
        "name": "Cline",
        "repo": "cline/cline",
        "stars": "68k",
        "bfcl": "未公布",
        "gaia": "未公布",
        "chateval": "未公布",
        "other": "产品评测页不以 BFCL/GAIA/ChatEval 出分",
    },
    {
        "name": "Continue",
        "repo": "continuedev/continue",
        "stars": "36k",
        "bfcl": "未公布",
        "gaia": "未公布",
        "chateval": "未公布",
        "other": "IDE 插件，无这三套公开 agent 榜",
    },
    {
        "name": "SWE-agent",
        "repo": "SWE-agent/SWE-agent",
        "stars": "20k",
        "bfcl": "未公布",
        "gaia": "未公布",
        "chateval": "未公布",
        "other": "SWE-bench 专用 agent",
    },
    {
        "name": "AutoGPT",
        "repo": "Significant-Gravitas/AutoGPT",
        "stars": "187k",
        "bfcl": "未公布",
        "gaia": "早期 GAIA 很低（OpenHands 文中 GPTSwarm/AutoGPT L1 val ~13%）",
        "chateval": "未公布",
        "other": "通用 agent，不是 coding-agent 主榜玩家",
    },
]

GAIA_AGENT_PEERS = [
    ("Human", "GAIA paper", "official test", "92%"),
    ("Magentic-One (GPT-4o + o1)", "arXiv:2411.04468", "official test", "38%"),
    ("Magentic-One (GPT-4o)", "arXiv:2411.04468", "official test", "32.3%"),
    ("OpenHands v0.28.1 (Claude 3.7)", "arXiv:2506.03011", "official test", "37.2%"),
    ("OpenHands-Versa (Claude 3.7 / Sonnet 4)", "arXiv:2506.03011", "official test", "51.2%"),
    ("OpenHands-Versa (Claude 3.7)", "arXiv:2506.03011", "official validation", "64.2%"),
    ("OWL-roleplaying", "arXiv:2506.03011 转引", "official validation", "58.2%"),
    ("OpenDeepResearch", "arXiv:2506.03011 转引", "official validation", "55.2%"),
]


def _pct(block: dict[str, Any] | None) -> str:
    block = block or {}
    total = int(block.get("total") or 0)
    passed = int(block.get("passed") or 0)
    if total <= 0:
        return "—"
    return f"{passed}/{total} ({passed / total:.1%})"


def _suite(report: dict[str, Any], name: str) -> dict[str, Any]:
    return ((report.get("suites") or {}).get(name) or {}).get("agent") or {}


def _progress(block: dict[str, Any], expected: int) -> str:
    total = int(block.get("total") or 0)
    text = _pct(block)
    if 0 < total < expected:
        return f"{text}（进行中 {total}/{expected}）"
    return text


def _case_lines(report: dict[str, Any], suite: str, *, limit: int | None = None) -> list[str]:
    rows = [row for row in (report.get("cases") or []) if row.get("suite") == suite]
    fails = [row for row in rows if not row.get("passed")]
    lines = [
        f"- 已完成 {len(rows)} 题，失败 {len(fails)} 题。",
        "",
        "失败题（最多列出 40 条）：" if fails else "本套全部通过。",
        "",
    ]
    shown = fails if limit is None else fails[:limit]
    for row in shown:
        reason = ""
        score = row.get("score") or {}
        if isinstance(score, dict):
            reason = str(score.get("reason") or "")
        extra = row.get("error") or reason
        lines.append(
            f"- `{row.get('id')}` FAIL ({row.get('duration_s')}s) {extra}".rstrip()
        )
    if limit is not None and len(fails) > limit:
        lines.append(f"- … 另有 {len(fails) - limit} 条失败，见 JSON")
    return lines


def _peer_table() -> list[str]:
    lines = [
        "## 横向：开源高星 agent（发表数字，不是同日同模型）",
        "",
        "星数是量级，不是排位依据。空单元格表示该项目**没有**公开发表对应官方题的 agent 分数。",
        "",
        "| 项目 | 仓库星数量级 | BFCL | GAIA | ChatEval / MT-Bench | 他们实际打的榜 |",
        "|---|---|---|---|---|---|",
    ]
    for row in OSS_AGENT_PEERS:
        lines.append(
            f"| {row['name']} | {row['stars']} | {row['bfcl']} | {row['gaia']} | "
            f"{row['chateval']} | {row['other']} |"
        )
    lines.extend(
        [
            "",
            "读法：OpenHands / Magentic-One 能在 **GAIA** 上横比；BFCL 官方榜是模型 FC，coding agent 几乎都不报；",
            "ChatEval 是评委方法，高星 coding agent 都不报 MT-Bench agent 分。所以三套题里，**只有 GAIA 有真正的 agent 横向**。",
            "",
        ]
    )
    return lines


def render_final(report: dict[str, Any]) -> str:
    model = report.get("model") or ""
    tag = str(report.get("tag") or "latest")
    lines = [
        "# 最终成绩",
        "",
        f"模型（套在 RxyCode AgentV2 里跑）：`{model}`",
        "",
        "只评 **Agent**。题目全部来自官方集，不是自制切片。",
        "横向是其他开源高星 agent 的**已发表**成绩，模型和日期不同，不能当排位赛。",
        "HTTP 429 / 智谱 1305 会在同一题上死磕，**不算失败、不进分母**。",
        "",
        "## 总表",
        "",
        "| 套件 | 官方题 | RxyCode Agent |",
        "|---|---|---|",
        f"| BFCL v4 Python AST | Gorilla JSONL **1240** | **{_progress(_suite(report, 'bfcl'), 1240)}** |",
        f"| GAIA 2023 validation | 官方 **165**（L1=53 / L2=86 / L3=26） | **{_progress(_suite(report, 'gaia'), 165)}** |",
        f"| ChatEval 评委 × MT-Bench 题 | LMSYS **80** | **{_progress(_suite(report, 'chateval'), 80)}** |",
        f"| 内部编码（附） | 本仓库 4 题 | **{_pct(_suite(report, 'internal'))}** |",
        "",
    ]
    lines.extend(_peer_table())
    lines.extend(
        [
            "## 分模式",
            "",
            f"- [BFCL](./{tag}-bfcl.md)",
            f"- [GAIA](./{tag}-gaia.md)",
            f"- [ChatEval](./{tag}-chateval.md)",
            "",
            str(report.get("note") or ""),
            "",
        ]
    )
    return "\n".join(lines)


def render_bfcl(report: dict[str, Any]) -> str:
    agent = _suite(report, "bfcl")
    by_cat = (report.get("suites") or {}).get("bfcl", {}).get("by_category") or {}
    lines = [
        "# BFCL · 工具调用",
        "",
        "官方题：Gorilla BFCL v4 Python AST JSONL。",
        "simple 400 + multiple 200 + parallel 200 + parallel_multiple 200 + irrelevance 240 = **1240**。",
        "评分对齐 `possible_answer`。跑的是 RxyCode AgentV2，每题只挂该题官方 functions。",
        "",
        f"## 本题成绩：{_progress(agent, 1240)}",
        "",
        "| 子类 | Agent |",
        "|---|---|",
    ]
    for name in ("simple", "multiple", "parallel", "parallel_multiple", "irrelevance"):
        lines.append(f"| {name} | {_pct(by_cat.get(name))} |")
    lines.extend(["", * _peer_table()])
    lines.extend(
        [
            "BFCL 官方排行榜评的是 **模型原生 function calling**。OpenHands / Aider / Cline / Continue / SWE-agent **都没有**公开发表 agent BFCL。",
            "因此横向只能写「未公布」，不能编一个假排位。",
            "",
            "## 失败明细",
            "",
        ]
    )
    lines.extend(_case_lines(report, "bfcl", limit=40))
    return "\n".join(lines) + "\n"


def render_gaia(report: dict[str, Any]) -> str:
    agent = _suite(report, "gaia")
    by_level = (report.get("suites") or {}).get("gaia", {}).get("by_level") or {}
    lines = [
        "# GAIA · 通用能力",
        "",
        "官方 2023 validation **165** 题（答案公开）。test 301 题答案未公开，不能本地打分。",
        "题与附件来自 ModelScope 镜像的 `gaia-benchmark/GAIA` parquet（与 HuggingFace 官方集同一份）。",
        "",
        f"## 本题成绩：{_progress(agent, 165)}",
        "",
        "| Level | Agent |",
        "|---|---|",
        f"| 1 | {_pct(by_level.get('1'))} |",
        f"| 2 | {_pct(by_level.get('2'))} |",
        f"| 3 | {_pct(by_level.get('3'))} |",
        "",
        "## 横向（其他 agent，官方 GAIA）",
        "",
        "| Agent | 来源 | 切分 | 成绩 |",
        "|---|---|---|---|",
        f"| **RxyCode AgentV2 + glm-5.3-flash** | 本次 | official validation 165 | **{_progress(agent, 165)}** |",
    ]
    for name, src, split, score in GAIA_AGENT_PEERS:
        lines.append(f"| {name} | {src} | {split} | {score} |")
    lines.extend(
        [
            "",
            "OpenHands-Versa / Magentic-One 用的是 Claude 3.7 / GPT-4o 和浏览器。本次是 glm-5.3-flash + RxyCode 工具。",
            "validation vs test 不能直接加减。",
            "",
            * _peer_table(),
            "## 失败明细",
            "",
        ]
    )
    lines.extend(_case_lines(report, "gaia", limit=40))
    return "\n".join(lines) + "\n"


def render_chateval(report: dict[str, Any]) -> str:
    agent = _suite(report, "chateval")
    by_cat = (report.get("suites") or {}).get("chateval", {}).get("by_category") or {}
    lines = [
        "# ChatEval · 官方题 + 官方评委协议",
        "",
        "ChatEval（Chan et al., ACL 2024）是 **三角色辩论评委**。",
        "论文用的 FairEval（Vicuna 80）原始文件不在 ChatEval 仓库里（只有 1 条 stub）。",
        "本题集改用同一实验室 LMSYS 的公开 **MT-Bench 80 题**，再用 ChatEval 多数决给 RxyCode Agent 的回答打分。",
        "",
        f"## 本题成绩：{_progress(agent, 80)}",
        "",
        "| 类别 | Agent |",
        "|---|---|",
    ]
    for name in sorted(by_cat):
        lines.append(f"| {name} | {_pct(by_cat.get(name))} |")
    lines.extend(
        [
            "",
            "## 横向",
            "",
            "OpenHands / Aider / Cline / Continue / Magentic-One / SWE-agent **都没有**公开发表 ChatEval 或 MT-Bench 的 agent 分数。",
            "ChatEval 论文报的是评委与人类偏好的相关，不是 coding agent 解题率。",
            "",
            * _peer_table(),
            "## 失败明细",
            "",
        ]
    )
    lines.extend(_case_lines(report, "chateval", limit=40))
    return "\n".join(lines) + "\n"


def render_index(report: dict[str, Any]) -> str:
    tag = str(report.get("tag") or "latest")
    return "\n".join(
        [
            f"# 索引 · {tag}",
            "",
            "最终成绩看这一份，不要看 JSON：",
            "",
            f"**[最终成绩单](./{tag}-FINAL.md)**",
            "",
            "分模式：",
            "",
            f"- [BFCL 工具调用](./{tag}-bfcl.md)",
            f"- [GAIA 通用能力](./{tag}-gaia.md)",
            f"- [ChatEval 多值协同](./{tag}-chateval.md)",
            "",
            f"`{tag}.json` 是机器原始记录。429 重试中的题不会被写成 FAIL。",
            "",
        ]
    )


def render_matrix(report: dict[str, Any]) -> str:
    """Public-bench scorecard. Tests and the report CLI both call this."""
    return render_final(report)
