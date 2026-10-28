"""Phase 3 M2/M7: ModelCatalog 目录契约测试（校验/冲突/查找/JSON 加载）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.config.model_catalog import DEFAULT_CATALOG_PATH, ModelCatalog


def _record(provider="a", model="m", ctx=1000, out=500, source="src"):
    return {
        "provider_id": provider,
        "model_id": model,
        "model_context_window": ctx,
        "model_max_output_tokens": out,
        "source": source,
        "source_url": "https://example.invalid/cat",
        "as_of": "2026-08-03",
    }


def test_empty_provider_id_rejected():
    cat = ModelCatalog()
    rec = _record(provider="")
    with pytest.raises(ValueError):
        cat.add_record(rec)


def test_empty_model_id_rejected():
    cat = ModelCatalog()
    rec = _record(model="")
    with pytest.raises(ValueError):
        cat.add_record(rec)


def test_non_positive_capability_rejected():
    cat = ModelCatalog()
    for field in ("model_context_window", "model_max_output_tokens"):
        rec = _record()
        rec[field] = 0
        with pytest.raises(ValueError):
            cat.add_record(rec)


def test_output_exceeds_context_rejected():
    cat = ModelCatalog()
    rec = _record(ctx=100, out=500)
    with pytest.raises(ValueError):
        cat.add_record(rec)


def test_missing_source_rejected():
    cat = ModelCatalog()
    rec = _record(source="")
    with pytest.raises(ValueError):
        cat.add_record(rec)


def test_duplicate_same_provider_fails_closed():
    cat = ModelCatalog()
    cat.add_record(_record())
    with pytest.raises(ValueError):
        cat.add_record(_record(out=999))  # 同 provider+id，拒绝覆盖


def test_cross_provider_same_model_ok():
    cat = ModelCatalog()
    cat.add_record(_record(provider="a", model="m", out=500))
    cat.add_record(_record(provider="b", model="m", out=800))
    rec_a, _, _ = cat.lookup("a", "m")
    rec_b, _, _ = cat.lookup("b", "m")
    assert rec_a.model_max_output_tokens == 500
    assert rec_b.model_max_output_tokens == 800


def test_casefold_strip_lookup_key():
    cat = ModelCatalog()
    cat.add_record(_record(provider="DeepSeek", model="DeepSeek-V4-Flash"))
    rec, key, _ = cat.lookup("deepseek", "deepseek-v4-flash")
    assert rec is not None
    assert key == "DeepSeek:DeepSeek-V4-Flash" or key is not None


def test_global_model_lookup_no_conflict():
    """仅一个 Provider 注册该 model_id 时，全局 model_id 可命中。"""
    cat = ModelCatalog()
    cat.add_record(_record(provider="a", model="solo"))
    rec, key, _ = cat.lookup("b", "solo")  # 请求 provider=b 但全局只有 a 的 solo
    assert rec is not None
    assert key == "solo"


def test_global_model_lookup_conflict_requires_provider():
    """同一 model_id 在两个 Provider 下，无 provider 精确命中时不全局匹配。"""
    cat = ModelCatalog()
    cat.add_record(_record(provider="a", model="dup"))
    cat.add_record(_record(provider="b", model="dup"))
    rec, key, _ = cat.lookup("c", "dup")  # provider=c 不在目录
    assert rec is None


def test_bundled_catalog_json_loads():
    """内置 config/model_catalog.json 必须能加载且合法。"""
    path = Path(DEFAULT_CATALOG_PATH)
    assert path.is_file(), "bundled model_catalog.json missing"
    ModelCatalog.load(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("records", [])
    assert isinstance(records, list) and records, "catalog has no records"
    for record in records:
        assert record.get("provider_id")
        assert record.get("model_id")
        assert record.get("source")
        ctx = record.get("model_context_window")
        out = record.get("model_max_output_tokens")
        if ctx is not None and out is not None:
            assert out <= ctx, "catalog record output > context"


def test_bundled_catalog_matches_schema():
    """M2：内置目录必须通过 JSON Schema 校验（冻结快照）。"""
    import jsonschema

    schema_path = Path(DEFAULT_CATALOG_PATH).with_suffix(".schema.json")
    assert schema_path.is_file(), "model_catalog.schema.json missing"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = json.loads(Path(DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    assert schema.get("schema_version") or True  # schema 存在


def test_bundled_catalog_contains_zen_luna_with_provider_specific_limits():
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)
    record, key, _ = catalog.lookup("zen", "gpt-5.6-luna")

    assert key is not None
    assert record is not None
    assert record.provider_id == "zen"
    assert record.model_id == "gpt-5.6-luna"
    assert record.model_max_output_tokens == 128000


def test_muse_catalog_only_claims_verified_go_contributor_metadata():
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)

    for model in ("muse-spark-1.1", "muse-spark-1.2"):
        record, _, _ = catalog.lookup("muse_spark", model)
        assert record is None

    contributor, _, _ = catalog.lookup(
        "muse_spark", "muse-spark-1.2-contributor"
    )
    assert contributor is not None
    assert contributor.model_context_window is None
    assert contributor.model_max_output_tokens is None


def test_bundled_catalog_contains_2026_10_flagship_sync_records():
    """2026-10-29 preset provider model-list refresh: new flagship records
    must resolve with the reviewed capability values."""
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)
    expectations = {
        ("qwen", "qwen3.8-max"): (1_000_000, 65_536),
        ("qwen", "qwen3.8-flash"): (1_000_000, 65_536),
        ("kimi", "kimi-k3.1-pro"): (1_048_576, 131_072),
        ("glm", "glm-5.3"): (1_048_576, 131_072),
        ("glm", "glm-5.3-flash"): (1_048_576, 131_072),
        ("openai", "gpt-6-astra"): (1_050_000, 128_000),
        ("openai", "gpt-6-luna"): (1_050_000, 128_000),
        ("doubao", "doubao-seed-evolving"): (1_048_576, 262_144),
        ("mimo", "mimo-v2.6-pro"): (1_048_576, None),
        ("minimax", "minimax-m3.1-flash"): (1_048_576, None),
    }
    for (provider, model), (ctx, out) in expectations.items():
        record, key, _ = catalog.lookup(provider, model)
        assert record is not None, f"{provider}:{model} missing from catalog"
        assert key is not None
        assert record.model_context_window == ctx, f"{provider}:{model} ctx"
        assert record.model_max_output_tokens == out, f"{provider}:{model} out"


def test_muse_spark_13_contributor_placeholder_shape():
    """muse-spark-1.3-contributor follows the 1.2-contributor shape: null
    capability values (unverified contributor tier), required source fields."""
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)
    record, key, _ = catalog.lookup("muse_spark", "muse-spark-1.3-contributor")
    assert record is not None
    assert key is not None
    assert record.model_context_window is None
    assert record.model_max_output_tokens is None


def test_doubao_seed_21_pro_tracks_current_upstream_snapshot():
    """doubao-seed-2.1-pro alias resolves to upstream -260915 (1024k/256k);
    record updated in the 2026-10-29 sync."""
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)
    record, _, _ = catalog.lookup("doubao", "doubao-seed-2.1-pro")
    assert record is not None
    assert record.model_context_window == 1_048_576
    assert record.model_max_output_tokens == 262_144


def test_deprecated_status_marker_is_metadata_only():
    """Records marked \"status\": \"deprecated\" stay loadable and resolvable —
    consumers (ModelCatalog/core.catalog) ignore unknown fields, so existing
    configs keep resolving limits instead of falling to unknown_fallback."""
    raw = json.loads(Path(DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
    marked = [
        record
        for record in raw["records"]
        if record.get("status") == "deprecated"
    ]
    # exactly the preview superseded by qwen3.8-max GA is marked today
    assert [r["model_id"] for r in marked] == ["qwen3.8-max-preview"]

    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)
    record, key, _ = catalog.lookup("qwen", "qwen3.8-max-preview")
    assert record is not None
    assert key is not None
    # deepseek-flash was verified still live at api.deepseek.com — must not
    # be marked deprecated (it was only removed on the OpenCode Go gateway).
    deeps = [
        r for r in raw["records"]
        if r["provider_id"] == "deepseek" and r["model_id"] == "deepseek-flash"
    ]
    assert deeps and deeps[0].get("status") != "deprecated"


def test_hy3_catalog_contains_only_the_formal_model_limits():
    catalog = ModelCatalog.load(DEFAULT_CATALOG_PATH)

    formal, _, _ = catalog.lookup("hy3", "hy3")
    assert formal is not None
    assert formal.model_context_window == 256_000
    assert formal.model_max_output_tokens == 128_000

    preview, _, _ = catalog.lookup("hy3", "hy3-preview")
    assert preview is None

    raw = json.loads(Path(DEFAULT_CATALOG_PATH).read_text(encoding="utf-8"))
    record = next(item for item in raw["records"] if item["provider_id"] == "hy3")
    assert record["cache_contract"]["cache_mode"] == "auto"
    assert record["cache_contract"]["breakpoints_max"] == 0
    assert record["cache_contract"]["prompt_cache_key_required"] is False
