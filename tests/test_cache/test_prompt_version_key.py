"""layer=unit/module F4-8 prompt_version 接线 precise cache key。"""
from __future__ import annotations

import inspect


def test_u_f4_8_01_version_changes_key(tmp_path):
    """layer=unit U-F4-8-01
    同输入、不同 prompt_version → precise key 不同（库层守卫，length-prefixed hash）。
    """
    from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

    cache = PreciseCache(cache_dir=tmp_path)
    key_v1 = cache._make_key("sys", "q", prompt_version="v1")
    key_v2 = cache._make_key("sys", "q", prompt_version="v2")
    assert key_v1 != key_v2
    parts_v1 = key_v1.split(":")
    parts_v2 = key_v2.split(":")
    assert parts_v1[0] == parts_v2[0]      # system_hash 段不变
    assert parts_v1[1] == parts_v2[1]      # query_hash 段不变
    assert parts_v1[3] != parts_v2[3]      # version_hash 段不同


def test_u_f4_8_02_bumped_version_old_entry_misses(tmp_path):
    """layer=unit U-F4-8-02
    bump 后旧条目不命中；同版本仍命中（from_cache=True，值逐字节）。
    """
    from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

    cache = PreciseCache(cache_dir=tmp_path)
    cache.put("sys", "q", "answer-42", prompt_version="v1", namespace="unit-f48")
    hit = cache.get("sys", "q", prompt_version="v1", namespace="unit-f48")
    assert hit is not None
    assert hit["response"] == "answer-42"
    assert hit["from_cache"] is True
    assert hit["cache_type"] == "precise"
    miss = cache.get("sys", "q", prompt_version="v2", namespace="unit-f48")
    assert miss is None


def test_u_f4_8_04_system_content_change_invalidates_old_key(tmp_path):
    """layer=unit U-F4-8-04（2026-10-01 GPT 审计：内容层天然失效）
    S1 内容改（版本忘 bump）→ system_hash 段不同 → 旧 key 不命中；同内容同版本仍命中。
    """
    from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

    cache = PreciseCache(cache_dir=tmp_path)
    cache.put("S1-v1-content", "q", "answer-42", prompt_version="v1", namespace="unit-f48b")
    key_before = cache._make_key("S1-v1-content", "q", prompt_version="v1")
    key_after = cache._make_key("S1-v2-content-edited", "q", prompt_version="v1")
    assert key_before.split(":")[0] != key_after.split(":")[0]   # system_hash 段天然变
    assert key_before.split(":")[3] == key_after.split(":")[3]   # version 段未变（控制变量）
    hit_tampered = cache.get("S1-v2-content-edited", "q", prompt_version="v1", namespace="unit-f48b")
    assert hit_tampered is None                                  # 旧条目不命中（天然失效）
    hit_same = cache.get("S1-v1-content", "q", prompt_version="v1", namespace="unit-f48b")
    assert hit_same is not None
    assert hit_same["response"] == "answer-42"


def test_u_f4_8_03_system_prompt_registered_with_version():
    """layer=unit U-F4-8-03
    "system" 键注册后可取版本；重注册 bump 后版本变更 → 下游 key 必然漂移。
    """
    from RxyCode.RxyCode1_1_0.core.prompts.registry import (
        _registry,
        get_prompt_version,
        get_spec,
    )

    version = get_prompt_version("system")
    assert isinstance(version, str)
    assert version != ""
    original = get_spec("system")
    try:
        _registry.register("system", original.template + "\n# bump", version="f48-test-bump")
        assert get_prompt_version("system") == "f48-test-bump"
    finally:
        _registry.register("system", original.template, version=original.version)
    assert get_prompt_version("system") == version


def test_mo_f4_8_01_fast_reply_callsites_pass_prompt_version():
    """layer=module MO-F4-8-01
    接线门（源码门，与 V13 双 parse_slash 门同一手法）：_fast_reply 里 get/put
    两个调用点都传 prompt_version=，且不是空字面量，值来自 registry 版本。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    src = inspect.getsource(AgentV2._fast_reply)
    get_idx = src.index("precise_cache.get(")
    put_idx = src.index("precise_cache.put(")
    get_call = src[get_idx : src.index("\n\n", get_idx)]
    put_call = src[put_idx : src.index("\n\n", put_idx)]
    assert "prompt_version=" in get_call
    assert "prompt_version=" in put_call
    assert 'prompt_version=""' not in src
    assert "get_prompt_version" in src
