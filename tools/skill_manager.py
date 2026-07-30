"""Skill Manager - Search, download, and manage skills from GitHub and other sources."""

import asyncio
import io
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode, urlsplit

from ..utils.safe_http import (
    fetch_public_response,
    fetch_public_response_sync,
)

# Real skill repositories with SKILL.md files
SKILL_REPOS = [
    "mxyhi/ok-skills",
    "FrancyJGLisboa/agent-skill-creator",
    "multica-ai/andrej-karpathy-skills",
]

# Well-known skills mapped to their actual GitHub repo paths
KNOWN_SKILLS = {
    "coding-workflow": ("mxyhi/ok-skills", "codebase-design"),
    "codebase-design": ("mxyhi/ok-skills", "codebase-design"),
    "systematic-debugging": ("mxyhi/ok-skills", "systematic-debugging"),
    "tdd": ("mxyhi/ok-skills", "tdd"),
    "test-driven-development": ("mxyhi/ok-skills", "tdd"),
    "diagnosing-bugs": ("mxyhi/ok-skills", "diagnosing-bugs"),
    "domain-modeling": ("mxyhi/ok-skills", "domain-modeling"),
    "planning-with-files": ("mxyhi/ok-skills", "planning-with-files"),
    "find-skills": ("mxyhi/ok-skills", "find-skills"),
    "find-docs": ("mxyhi/ok-skills", "find-docs"),
    "autoresearch": ("mxyhi/ok-skills", "autoresearch"),
    "agent-browser": ("mxyhi/ok-skills", "agent-browser"),
    "browser-trace": ("mxyhi/ok-skills", "browser-trace"),
    "prototype": ("mxyhi/ok-skills", "prototype"),
    "teach": ("mxyhi/ok-skills", "teach"),
    "grilling": ("mxyhi/ok-skills", "grilling"),
    "improve-codebase-architecture": ("mxyhi/ok-skills", "improve-codebase-architecture"),
    "caveman": ("mxyhi/ok-skills", "caveman"),
    "karpathy-guidelines": ("mxyhi/ok-skills", "karpathy-guidelines"),
    "agent-skill-creator": ("FrancyJGLisboa/agent-skill-creator", ""),
}


_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_SKILL_DOWNLOAD_BYTES = 25 * 1024 * 1024
_MAX_SKILL_ARCHIVE_MEMBERS = 1024
_MAX_SKILL_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
_MAX_SKILL_MEMBER_BYTES = 25 * 1024 * 1024
_MAX_SKILL_COMPRESSION_RATIO = 200.0
_SKILL_EXTRACT_CHUNK_BYTES = 64 * 1024


def _validate_skill_name(skill_name: str) -> str:
    name = skill_name.strip()
    if not _SAFE_SKILL_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Skill name must contain only letters, digits, '.', '_' or '-'")
    return name


def _validated_zip_parts(member: zipfile.ZipInfo) -> tuple[str, ...]:
    """Validate one member name and return its platform-neutral path parts."""
    name = member.filename.replace("\\", "/")
    member_path = PurePosixPath(name)
    if (
        not name
        or "\x00" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or member_path.is_absolute()
        or any(part in {"", ".", ".."} for part in member_path.parts)
        or any(":" in part for part in member_path.parts)
    ):
        raise ValueError("Unsafe ZIP member path")
    return member_path.parts


def _validate_zip_member_type(member: zipfile.ZipInfo) -> None:
    if member.flag_bits & 0x1:
        raise ValueError("Encrypted ZIP members are not supported")

    unix_mode = (member.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    allowed_type = stat.S_IFDIR if member.is_dir() else stat.S_IFREG
    if file_type not in {0, allowed_type}:
        raise ValueError("ZIP contains an unsupported special file")


def _preflight_zip_members(
    members: list[zipfile.ZipInfo],
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    if len(members) > _MAX_SKILL_ARCHIVE_MEMBERS:
        raise ValueError(
            f"ZIP exceeds {_MAX_SKILL_ARCHIVE_MEMBERS} member limit"
        )

    total_size = 0
    seen_paths: set[str] = set()
    validated = []
    for member in members:
        parts = _validated_zip_parts(member)
        _validate_zip_member_type(member)

        path_key = "/".join(parts).casefold()
        if path_key in seen_paths:
            raise ValueError("ZIP contains duplicate member paths")
        seen_paths.add(path_key)

        if member.file_size < 0 or member.compress_size < 0:
            raise ValueError("ZIP contains invalid member sizes")
        if member.file_size > _MAX_SKILL_MEMBER_BYTES:
            raise ValueError(
                f"ZIP member exceeds {_MAX_SKILL_MEMBER_BYTES} byte limit"
            )
        total_size += member.file_size
        if total_size > _MAX_SKILL_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"ZIP exceeds {_MAX_SKILL_UNCOMPRESSED_BYTES} byte extraction limit"
            )
        if not member.is_dir() and member.file_size:
            if member.compress_size == 0:
                raise ValueError("ZIP member has an unsafe compression ratio")
            ratio = member.file_size / member.compress_size
            if ratio > _MAX_SKILL_COMPRESSION_RATIO:
                raise ValueError("ZIP member has an unsafe compression ratio")
        validated.append((member, parts))
    return validated


def _safe_extract_zip(payload: bytes, target_dir: Path) -> None:
    """Extract a bounded archive without trusting ZIP metadata or paths."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = _preflight_zip_members(archive.infolist())
        actual_total = 0
        for member, parts in members:
            destination = target_dir.joinpath(*parts)
            try:
                destination.resolve(strict=False).relative_to(target_root)
            except ValueError as exc:
                raise ValueError("Unsafe ZIP member path") from exc

            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            actual_member = 0
            with archive.open(member, "r") as source, destination.open("xb") as output:
                while chunk := source.read(_SKILL_EXTRACT_CHUNK_BYTES):
                    actual_member += len(chunk)
                    actual_total += len(chunk)
                    if actual_member > _MAX_SKILL_MEMBER_BYTES:
                        raise ValueError(
                            f"ZIP member exceeds {_MAX_SKILL_MEMBER_BYTES} byte limit"
                        )
                    if actual_total > _MAX_SKILL_UNCOMPRESSED_BYTES:
                        raise ValueError(
                            "ZIP exceeds "
                            f"{_MAX_SKILL_UNCOMPRESSED_BYTES} byte extraction limit"
                        )
                    if actual_member > member.file_size:
                        raise ValueError("ZIP member expanded beyond its declared size")
                    output.write(chunk)


def get_skills_dir() -> Path:
    """Get the user skills directory."""
    d = Path.home() / ".rxycode" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_installed_skills() -> list[dict]:
    """List all installed skills."""
    skills_dir = get_skills_dir()
    skills = []
    if not skills_dir.exists():
        return skills
    for d in skills_dir.iterdir():
        if d.is_dir():
            skill_file = d / "SKILL.md"
            if skill_file.exists():
                skills.append({
                    "name": d.name,
                    "path": str(d),
                    "has_skill_md": True,
                })
            else:
                skills.append({
                    "name": d.name,
                    "path": str(d),
                    "has_skill_md": False,
                })
    return skills


def search_github_skills(query: str) -> list[dict]:
    """Search GitHub for skills matching the query."""
    results = []

    # First check known skills
    query_lower = query.lower().strip()
    for name, (repo, path) in KNOWN_SKILLS.items():
        if query_lower in name.lower() or query_lower in path.lower():
            results.append({
                "name": name,
                "repo": repo,
                "path": path,
                "source": "known",
            })

    # Then search GitHub API for repos with SKILL.md
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        params = urlencode({"q": f"{query} SKILL.md", "per_page": 5})
        url = f"https://api.github.com/search/repositories?{params}"
        resp = fetch_public_response_sync(
            url,
            timeout=15,
            max_bytes=5 * 1024 * 1024,
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("items", []):
                repo_name = item.get("full_name", "")
                if repo_name:
                    results.append({
                        "name": repo_name.split("/")[-1],
                        "repo": repo_name,
                        "path": "",
                        "source": "github",
                    })
    except Exception:
        pass

    return results


def download_skill_from_github(repo: str, path: str, skill_name: str) -> tuple[bool, str]:
    """Download a skill from a GitHub repository."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_download_skill_async(repo, path, skill_name))
    return False, "Download failed: synchronous install cannot run inside an event loop"


def install_skill_from_url(url: str, skill_name: str) -> tuple[bool, str]:
    """Install a skill from a direct URL (raw file or zip)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(install_skill_from_url_async(url, skill_name))
    return False, "Install failed: synchronous install cannot run inside an event loop"


async def install_skill_from_url_async(url: str, skill_name: str) -> tuple[bool, str]:
    """Cancellable direct-URL install with staged atomic publication."""
    skills_dir = get_skills_dir()
    try:
        skill_name = _validate_skill_name(skill_name)
    except ValueError as exc:
        return False, str(exc)
    if not url.lower().startswith(("http://", "https://")):
        return False, "Skill URL must use HTTP or HTTPS"

    target_dir = skills_dir / skill_name
    staging = Path(tempfile.mkdtemp(dir=skills_dir, prefix=f".{skill_name}."))
    try:
        response = await fetch_public_response(
            url,
            timeout=30,
            max_bytes=_MAX_SKILL_DOWNLOAD_BYTES,
        )
        if not 200 <= response.status_code < 300:
            return False, f"Install failed: HTTP status {response.status_code}"
        payload = response.content
        if urlsplit(url).path.lower().endswith(".zip"):
            _safe_extract_zip(payload, staging)
        else:
            (staging / "SKILL.md").write_bytes(payload)
        if target_dir.exists():
            return False, f"Skill '{skill_name}' is already installed"
        os.replace(staging, target_dir)
        return True, f"Installed skill at {target_dir}"
    except (ValueError, zipfile.BadZipFile) as exc:
        return False, f"Install failed: {exc}"
    except Exception as exc:
        return False, f"Install failed: {type(exc).__name__}"
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def remove_skill(skill_name: str) -> tuple[bool, str]:
    """Remove an installed skill."""
    skills_dir = get_skills_dir()
    try:
        skill_name = _validate_skill_name(skill_name)
    except ValueError as exc:
        return False, str(exc)
    target_dir = skills_dir / skill_name
    if not target_dir.exists():
        return False, f"Skill '{skill_name}' not found"
    shutil.rmtree(target_dir)
    return True, f"Removed skill '{skill_name}'"


def find_and_download_skill(query: str) -> tuple[bool, str]:
    """Search for a skill and download the best match."""
    # Check if already installed
    skills_dir = get_skills_dir()
    if (skills_dir / query).exists():
        return True, f"Skill '{query}' is already installed"

    # Check known skills first
    query_lower = query.lower().strip()
    if query_lower in KNOWN_SKILLS:
        repo, path = KNOWN_SKILLS[query_lower]
        return download_skill_from_github(repo, path, query_lower)

    # Search GitHub
    results = search_github_skills(query)
    if not results:
        return False, f"No skills found matching '{query}'"

    # Try the first result
    best = results[0]
    return download_skill_from_github(
        best["repo"], best["path"], best.get("name", query)
    )


async def find_and_download_skill_async(query: str) -> tuple[bool, str]:
    """Cancellable skill download that publishes only a complete directory."""
    skills_dir = get_skills_dir()
    query_lower = query.lower().strip()
    if (skills_dir / query_lower).exists():
        return True, f"Skill '{query_lower}' is already installed"

    if query_lower in KNOWN_SKILLS:
        repo, path = KNOWN_SKILLS[query_lower]
        return await _download_skill_async(repo, path, query_lower)

    try:
        params = urlencode({"q": f"{query} SKILL.md", "per_page": 5})
        response = await fetch_public_response(
            f"https://api.github.com/search/repositories?{params}",
            timeout=15,
            max_bytes=5 * 1024 * 1024,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        response.raise_for_status()
        items = response.json().get("items", [])
    except Exception as exc:
        return False, f"Skill search failed: {exc}"
    if not items:
        return False, f"No skills found matching '{query}'"
    repo = items[0].get("full_name", "")
    name = repo.split("/")[-1] if repo else query_lower
    return await _download_skill_async(repo, "", name)


async def _download_skill_async(
    repo: str,
    path: str,
    skill_name: str,
) -> tuple[bool, str]:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", skill_name).strip(".-")
    if not repo or not safe_name:
        return False, "Invalid skill repository or name"

    skills_dir = get_skills_dir()
    target_dir = skills_dir / safe_name
    if target_dir.exists():
        return True, f"Skill '{safe_name}' already installed at {target_dir}"

    staging = Path(tempfile.mkdtemp(dir=skills_dir, prefix=f".{safe_name}."))
    downloaded = 0
    try:
        api_path = f"/contents/{path.strip('/')}" if path else "/contents/"
        api_url = f"https://api.github.com/repos/{repo}{api_path}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        response = await fetch_public_response(
            api_url,
            timeout=30,
            max_bytes=5 * 1024 * 1024,
            headers=headers,
        )
        total_bytes = 0
        if response.status_code == 200:
            payload = response.json()
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if entry.get("type") != "file" and not entry.get("download_url"):
                    continue
                download_url = entry.get("download_url")
                file_name = Path(entry.get("name", "")).name
                if not download_url or not file_name:
                    continue
                remaining = _MAX_SKILL_DOWNLOAD_BYTES - total_bytes
                if remaining <= 0:
                    raise ValueError("Skill download exceeds 25 MiB limit")
                file_response = await fetch_public_response(
                    download_url,
                    timeout=30,
                    max_bytes=remaining,
                )
                file_response.raise_for_status()
                (staging / file_name).write_bytes(file_response.content)
                total_bytes += len(file_response.content)
                downloaded += 1

        if downloaded == 0:
            relative = f"{path.strip('/')}/" if path else ""
            candidates = [
                f"https://raw.githubusercontent.com/{repo}/{branch}/{relative}{name}"
                for branch in ("main", "master")
                for name in ("SKILL.md", "CLAUDE.md")
            ]
            for candidate in candidates:
                file_response = await fetch_public_response(
                    candidate,
                    timeout=30,
                    max_bytes=_MAX_SKILL_DOWNLOAD_BYTES,
                )
                if file_response.status_code == 200:
                    (staging / "SKILL.md").write_bytes(file_response.content)
                    downloaded = 1
                    break

        if downloaded == 0:
            return False, f"Could not find skill files in {repo}"
        os.replace(staging, target_dir)
        return True, f"Downloaded {downloaded} files to {target_dir}"
    except Exception as exc:
        return False, f"Download failed: {exc}"
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
