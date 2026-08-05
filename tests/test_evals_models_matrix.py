"""A10: --models parsing, comparison matrix formatting, report generation."""

import json

from evals.runner import (
    SuiteReport,
    TaskResult,
    _model_slug,
    _parse_models_list,
    format_model_comparison,
    load_model_baselines,
)


def _make_report(pairs):
    r = SuiteReport(backend="agent")
    for tid, ok in pairs:
        r.results.append(TaskResult(task_id=tid, category="bugfix", passed=ok))
    r.compute_summary()
    return r


def test_parse_models_list():
    assert _parse_models_list("zen/gpt-5.6-luna, zen/kimi-k2.7-code ,") == [
        "zen/gpt-5.6-luna",
        "zen/kimi-k2.7-code",
    ]
    assert _parse_models_list("  , a ,") == ["a"]
    assert _parse_models_list("") == []


def test_model_slug():
    assert _model_slug("zen/gpt-5.6-luna") == "zen-gpt-5.6-luna"
    assert _model_slug("deepseek/deepseek-v4-pro") == "deepseek-deepseek-v4-pro"


def test_format_model_comparison_matrix():
    a = _make_report([("t1", True), ("t2", False)])
    b = _make_report([("t1", False), ("t2", True)])
    md = format_model_comparison([("model-a", a), ("model-b", b)])
    assert "`model-a`" in md and "`model-b`" in md
    assert "| t1 | PASS | FAIL |" in md
    assert "| t2 | FAIL | PASS |" in md
    assert "| Pass rate | 50% (1/2) | 50% (1/2) |" in md
    assert "| Avg tokens |" in md
    assert "| Avg duration |" in md


def _write_baseline(path, results):
    r = _make_report(results)
    data = r.to_dict()
    data["backend"] = "agent"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_model_baselines_and_report(tmp_path):
    _write_baseline(tmp_path / "2026-08-05-agent-zen-gpt-5.6-luna.json", [("t1", True)])
    _write_baseline(tmp_path / "2026-08-05-agent-zen-kimi-k2.7-code.json", [("t1", False)])
    reports = load_model_baselines("2026-08-05", base=tmp_path)
    labels = [l for l, _ in reports]
    assert labels == ["zen-gpt-5.6-luna", "zen-kimi-k2.7-code"]
    md = format_model_comparison(reports)
    assert "zen-gpt-5.6-luna" in md and "zen-kimi-k2.7-code" in md
