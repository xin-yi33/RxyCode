"""credentials.yaml per-signature parse cache (2026-10-11 /model 1.3-2s 修复).

models/list 对每个模型 resolve 一次都要 load_credential → _read_store →
纯 Python yaml.safe_load 重复解析同一文件。缓存按 (size, mtime_ns) 签名命中，
_write_store / 任何外部写入（mtime 变化）都会失效。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from config import credential_store


@pytest.fixture
def fresh_cache(monkeypatch) -> dict:
    cache: dict = {}
    monkeypatch.setattr(credential_store, "_READ_STORE_CACHE", cache)
    return cache


@pytest.fixture
def store_file(tmp_path: Path) -> Path:
    path = tmp_path / "credentials.yaml"
    credential_store._write_store(path, {"a" * 32: "enc-a"})
    return path


def _count_parses(monkeypatch) -> list:
    calls = []
    real = yaml.safe_load

    def counting(document):
        calls.append(1)
        return real(document)

    monkeypatch.setattr(credential_store.yaml, "safe_load", counting)
    return calls


def test_repeat_read_hits_cache(store_file, monkeypatch, fresh_cache):
    calls = _count_parses(monkeypatch)
    first = credential_store._read_store(store_file)
    second = credential_store._read_store(store_file)
    assert len(calls) == 1  # 第二次签名命中，不再解析
    assert first == second


def test_external_rewrite_invalidates(store_file, monkeypatch, fresh_cache):
    calls = _count_parses(monkeypatch)
    credential_store._read_store(store_file)
    # 外部进程改写（mtime_ns 必然变化）
    credential_store._write_store(store_file, {"b" * 32: "enc-b"})
    data = credential_store._read_store(store_file)
    assert data == {"b" * 32: "enc-b"}
    assert len(calls) == 2


def test_returned_dict_is_a_copy(store_file, monkeypatch, fresh_cache):
    data = credential_store._read_store(store_file)
    data["poison"] = "x"
    assert credential_store._read_store(store_file) == {"a" * 32: "enc-a"}


def test_disable_env_reparses(store_file, monkeypatch, fresh_cache):
    monkeypatch.setenv("RXYCODE_DISABLE_ACL_CACHE", "1")
    calls = _count_parses(monkeypatch)
    credential_store._read_store(store_file)
    credential_store._read_store(store_file)
    assert len(calls) == 2
