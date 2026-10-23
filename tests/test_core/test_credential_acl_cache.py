"""Per-path ACL cache guarding the icacls subprocess storm fix."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from config import credential_store


def _record_icacls(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append([str(part) for part in cmd])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(credential_store.subprocess, "run", fake_run)
    monkeypatch.setattr(
        credential_store, "_windows_current_sid", lambda: "S-1-5-21-1000"
    )
    return calls


@pytest.fixture
def fresh_acl_cache(monkeypatch) -> dict:
    cache: dict[str, tuple[int, int, bool]] = {}
    monkeypatch.setattr(credential_store, "_ACL_CACHE", cache)
    return cache


windows_only = pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")


@windows_only
def test_repeat_restrict_with_same_content_skips_icacls(
    tmp_path: Path, monkeypatch, fresh_acl_cache
):
    calls = _record_icacls(monkeypatch)
    target = tmp_path / "credentials.yaml"
    target.write_text("{}\n", encoding="utf-8")

    credential_store.restrict_file_permissions(target)
    credential_store.restrict_file_permissions(target)
    assert len(calls) == 1
    assert calls[0][0] == "icacls"

    # mtime-only change re-runs icacls even when the size is unchanged.
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    credential_store.restrict_file_permissions(target)
    assert len(calls) == 2

    # Content (size) change re-runs icacls as well.
    target.write_text('{"version": 1}\n', encoding="utf-8")
    credential_store.restrict_file_permissions(target)
    assert len(calls) == 3


@windows_only
def test_acl_cache_disabled_env_runs_icacls_every_time(
    tmp_path: Path, monkeypatch, fresh_acl_cache
):
    monkeypatch.setenv("RXYCODE_DISABLE_ACL_CACHE", "1")
    calls = _record_icacls(monkeypatch)
    target = tmp_path / "credentials.yaml"
    target.write_text("{}\n", encoding="utf-8")

    credential_store.restrict_file_permissions(target)
    credential_store.restrict_file_permissions(target)
    assert len(calls) == 2
    assert fresh_acl_cache == {}


@windows_only
def test_atomic_write_invalidates_cached_acl_entries(
    tmp_path: Path, monkeypatch, fresh_acl_cache
):
    calls = _record_icacls(monkeypatch)
    target = tmp_path / "config.yaml"
    target.write_text("one\n", encoding="utf-8")

    credential_store.restrict_file_permissions(target)
    credential_store.atomic_write_text(target, "two\n")

    # The target entry is refreshed during the write, so a restrict against
    # the unchanged file hits the cache instead of spawning icacls again.
    before = len(calls)
    credential_store.restrict_file_permissions(target)
    assert len(calls) == before
    # One-shot temporary file names must not linger in the cache.
    leftover = [
        key
        for key in fresh_acl_cache
        if key != os.path.normcase(str(target))
    ]
    assert leftover == []


@windows_only
def test_failed_restrict_is_not_cached(tmp_path: Path, monkeypatch, fresh_acl_cache):
    calls: list[list[str]] = []

    def failing_run(cmd, *args, **kwargs):
        calls.append([str(part) for part in cmd])
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(credential_store.subprocess, "run", failing_run)
    monkeypatch.setattr(
        credential_store, "_windows_current_sid", lambda: "S-1-5-21-1000"
    )
    target = tmp_path / "credentials.yaml"
    target.write_text("{}\n", encoding="utf-8")

    with pytest.raises(OSError):
        credential_store.restrict_file_permissions(target)
    with pytest.raises(OSError):
        credential_store.restrict_file_permissions(target)
    assert len(calls) == 2
    assert fresh_acl_cache == {}
