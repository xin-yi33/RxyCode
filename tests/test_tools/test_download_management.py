"""Skill/MCP management safety and cancellation regressions."""

import asyncio
import io
import stat
import zipfile

import httpx
import pytest


def test_remove_skill_rejects_parent_path(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(skill_manager, "get_skills_dir", lambda: skills_dir)

    ok, message = skill_manager.remove_skill("../outside")

    assert not ok
    assert "Skill name" in message
    assert outside.exists()


def test_zip_install_rejects_parent_member(tmp_path):
    from RxyCode.RxyCode1_1_0.tools.skill_manager import _safe_extract_zip

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../outside.txt", "bad")

    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        _safe_extract_zip(payload.getvalue(), tmp_path / "target")
    assert not (tmp_path / "outside.txt").exists()


def test_zip_install_rejects_high_compression_ratio(tmp_path):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", b"A" * 100_000)

    with pytest.raises(ValueError, match="unsafe compression ratio"):
        skill_manager._safe_extract_zip(payload.getvalue(), tmp_path / "target")


def test_zip_install_rejects_too_many_members(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    monkeypatch.setattr(skill_manager, "_MAX_SKILL_ARCHIVE_MEMBERS", 2)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for index in range(3):
            archive.writestr(f"file-{index}.txt", "ok")

    with pytest.raises(ValueError, match="2 member limit"):
        skill_manager._safe_extract_zip(payload.getvalue(), tmp_path / "target")


def test_zip_install_rejects_declared_member_and_total_sizes(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("one.txt", b"1234")
        archive.writestr("two.txt", b"5678")

    monkeypatch.setattr(skill_manager, "_MAX_SKILL_MEMBER_BYTES", 3)
    with pytest.raises(ValueError, match="member exceeds 3 byte limit"):
        skill_manager._safe_extract_zip(payload.getvalue(), tmp_path / "member")

    monkeypatch.setattr(skill_manager, "_MAX_SKILL_MEMBER_BYTES", 10)
    monkeypatch.setattr(skill_manager, "_MAX_SKILL_UNCOMPRESSED_BYTES", 7)
    with pytest.raises(ValueError, match="7 byte extraction limit"):
        skill_manager._safe_extract_zip(payload.getvalue(), tmp_path / "total")


def test_zip_install_enforces_stream_limit_against_forged_size(
    tmp_path, monkeypatch
):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    member = zipfile.ZipInfo("SKILL.md")
    member.file_size = 1
    member.compress_size = 1

    class ForgedArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return [member]

        def open(self, *_args, **_kwargs):
            return io.BytesIO(b"four")

    monkeypatch.setattr(skill_manager.zipfile, "ZipFile", lambda *_args: ForgedArchive())
    monkeypatch.setattr(skill_manager, "_MAX_SKILL_UNCOMPRESSED_BYTES", 2)

    with pytest.raises(ValueError, match="2 byte extraction limit"):
        skill_manager._safe_extract_zip(b"forged", tmp_path / "target")


def test_zip_install_rejects_special_files(tmp_path):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(link, "SKILL.md")

    with pytest.raises(ValueError, match="unsupported special file"):
        skill_manager._safe_extract_zip(payload.getvalue(), tmp_path / "target")


def test_zip_install_rejects_encrypted_members():
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    member = zipfile.ZipInfo("SKILL.md")
    member.flag_bits |= 0x1

    with pytest.raises(ValueError, match="Encrypted ZIP members"):
        skill_manager._preflight_zip_members([member])


@pytest.mark.asyncio
async def test_zip_install_streams_normal_archive(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skill_manager, "get_skills_dir", lambda: skills_dir)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("demo/SKILL.md", "# Demo\n")
        archive.writestr("demo/run.py", "print('ok')\n")

    class Response:
        status_code = 200
        content = payload.getvalue()

    async def fetch(*_args, **_kwargs):
        return Response()

    monkeypatch.setattr(skill_manager, "fetch_public_response", fetch)
    ok, message = await skill_manager.install_skill_from_url_async(
        "https://example.test/demo.zip?signature=do-not-reflect", "demo"
    )

    assert ok, message
    assert (skills_dir / "demo" / "demo" / "SKILL.md").read_text() == "# Demo\n"
    assert (skills_dir / "demo" / "demo" / "run.py").is_file()
    assert "do-not-reflect" not in message


@pytest.mark.asyncio
async def test_zip_install_failure_does_not_reflect_url_query(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skill_manager, "get_skills_dir", lambda: skills_dir)

    class Response:
        status_code = 403
        content = b""

    async def fetch(*_args, **_kwargs):
        return Response()

    monkeypatch.setattr(skill_manager, "fetch_public_response", fetch)
    ok, message = await skill_manager.install_skill_from_url_async(
        "https://example.test/demo.zip?signature=do-not-reflect", "demo"
    )

    assert not ok
    assert "HTTP status 403" in message
    assert "do-not-reflect" not in message
    assert not (skills_dir / "demo").exists()
    assert not list(skills_dir.glob(".demo.*"))


@pytest.mark.asyncio
async def test_cancelled_direct_url_install_removes_staging(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import skill_manager

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skill_manager, "get_skills_dir", lambda: skills_dir)
    started = asyncio.Event()

    async def slow_fetch(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(skill_manager, "fetch_public_response", slow_fetch)
    task = asyncio.create_task(
        skill_manager.install_skill_from_url_async(
            "https://example.test/SKILL.md", "demo"
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not (skills_dir / "demo").exists()
    assert not list(skills_dir.glob(".demo.*"))


@pytest.mark.asyncio
async def test_downloaders_reject_public_redirect_to_loopback(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import file_download, skill_manager
    from RxyCode.RxyCode1_1_0.utils import safe_http

    public_ip = "93.184.216.34"

    async def resolve(_hostname, _port):
        return [public_ip]

    async def handler(_request):
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/private"},
        )

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skill_manager, "get_skills_dir", lambda: skills_dir)
    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve)
    monkeypatch.setattr(safe_http.httpx, "AsyncClient", client_factory)

    download_result = await file_download.download_file_async(
        "https://example.com/file.txt",
        save_path=str(tmp_path / "file.txt"),
    )
    skill_ok, skill_message = await skill_manager.install_skill_from_url_async(
        "https://example.com/SKILL.md",
        "demo",
    )

    assert "private or non-routable" in download_result
    assert not (tmp_path / "file.txt").exists()
    assert not skill_ok
    assert "private or non-routable" in skill_message
    assert not (skills_dir / "demo").exists()
    assert not list(skills_dir.glob(".demo.*"))


def test_download_mcp_supports_custom_add_and_remove(monkeypatch):
    from RxyCode.RxyCode1_1_0.tools import mcp_manager
    from RxyCode.RxyCode1_1_0.tools.download_tool import download_mcp

    added = []
    monkeypatch.setattr(mcp_manager, "list_mcp_servers", lambda: [])
    monkeypatch.setattr(
        mcp_manager,
        "add_mcp_server",
        lambda name, command, args: (added.append((name, command, args)) or True, "saved"),
    )
    monkeypatch.setattr(mcp_manager, "remove_mcp_server", lambda name: (True, name))

    add_result = download_mcp(
        "files", operation="add", command="node", args=["server.js"]
    )
    remove_result = download_mcp("files", operation="remove")

    assert added == [("files", "node", ["server.js"])]
    assert add_result.startswith("Successfully added")
    assert remove_result.startswith("Successfully removed")
