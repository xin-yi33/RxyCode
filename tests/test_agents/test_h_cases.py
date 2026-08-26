"""H1–H6 prompts are coding tasks for the builtin software_dev team."""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team

H_CASES = {
    "H1": "/team 实现 POST /login。必须落地 auth/passwords.py（hash+verify，禁止明文）、auth/routes.py（login 失败 401 成功返回 token）、tests/test_login.py（至少失败登录+成功登录两条）。pytest tests/test_login.py 必须全绿。先澄清需求再方案再实现再测试再审计。禁止 Java/Spring/Maven。纯后端：前端角色必须 SKIP。",
    "H2": "把前后端拆成两个独立改造再多人审计：backend/app.py 提供 GET /health 与 POST /echo，frontend/index.html 调 /echo，tests/test_app.py 覆盖两个接口。pytest 必须绿。",
    "H3": "/team 实现带 TTL 的 LRU：lru_cache.py 提供 get/set/delete、maxsize、ttl_seconds；tests/test_lru_cache.py 覆盖淘汰、过期、更新。禁止改测试里的断言来过门。pytest 必须绿。",
    "H4": "/team 先在 calc/parser.py 写 tokenize，calc/eval.py 写四则运算（优先级、括号、除零返回错误对象），tests/test_calc.py 至少 6 条。禁止把测试改成 assert True。pytest 必须绿。",
    "H5": "/team 实现 CLI：cli.py 用 argparse 提供 add/list/done；store.py 用 JSON 文件持久化；tests/test_cli.py 测三条命令。工作目录内数据文件不得写到用户 home。pytest 必须绿。",
    "H6": "/team 修复并拆分：仓库里已有 broken_stat.py。拆成 stats/core.py + stats/csv_load.py + tests/test_stats.py。空列表返回 0.0；非数字跳过并计数。pytest 必须绿。禁止删测试。",
}


def test_h_cases_file_exists_and_is_coding_only() -> None:
    text = "\n".join(H_CASES.values())
    assert "/team 实现 POST /login" in text
    assert "lru_cache.py" in text
    assert "backend/app.py" in text
    assert "broken_stat.py" in text
    lowered = text.lower()
    assert "nasdaq" not in lowered
    assert "黄金" not in text
    assert "pytest" in lowered
    assert len(H_CASES) == 6


def test_builtin_team_has_pm_frontend_backend_tester() -> None:
    team = load_builtin_team()
    roles = {m.role for m in team.members}
    assert {"pm", "frontend_coder", "backend_coder", "tester"} <= roles
    assert team.stages[0].name == "clarify"
