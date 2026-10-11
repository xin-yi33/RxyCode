"""Private, atomic storage for model credentials.

The public YAML configuration contains only opaque credential references.
Windows values are protected with the current user's DPAPI key.  POSIX has no
portable stdlib keyring, so values live in a separate owner-only file.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import ctypes
from contextlib import contextmanager
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator

import yaml


SECRET_FILE_NAME = "credentials.yaml"
_STORE_VERSION = 1
_STORE_LOCK = threading.RLock()
_REFERENCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SID_PATTERN = re.compile(r"^S-\d(?:-\d+)+$")
# Module-level platform probe so tests can force POSIX vs Windows branches.
_os_name = os.name


_cached_windows_sid: str | None = None

# ── credentials.yaml 解析缓存 ─────────────────────────────────────────
# models/list 每个模型 resolve 一次都调 load_credential → _read_store，
# 66 个模型 = 57 次纯 Python yaml.safe_load（2026-10-11 profile：list_models
# 2.08s 中 1.37s 是重复解析同一文件）。按 (path, size, mtime_ns) 签名缓存解析
# 结果；任何写入（含原子替换）都会改 mtime 自动失效，_write_store 也主动清。
# 返回浅拷贝，防调用方（如 store_credential 的写入前拼装）污染缓存。
# RXYCODE_DISABLE_ACL_CACHE=1 一并禁用本缓存（与 ACL 缓存同一个回退开关）。
_READ_STORE_CACHE: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}


def _read_store_cache_key(path: Path) -> str:
    key = str(path)
    return os.path.normcase(key) if os.name == "nt" else key


def _invalidate_read_store_cache(path: Path) -> None:
    _READ_STORE_CACHE.pop(_read_store_cache_key(path), None)


# ── Per-path ACL cache ────────────────────────────────────────────────
# Every config/credential load or save used to spawn one or two ``icacls``
# child processes (15s timeout each); a single model switch could accumulate
# 15-30+ subprocess spawns and freeze the caller for seconds.  ``icacls`` is
# idempotent, so after a *successful* restrict we remember the file
# signature ``(size, mtime_ns, exists)`` and skip the subprocess while the
# file is unchanged.  Each process carries its own cache, which concurrent
# processes tolerate: the worst case is one redundant ``icacls`` run.
# ``RXYCODE_DISABLE_ACL_CACHE=1`` restores the old always-run behavior.
_ACL_CACHE: dict[str, tuple[int, int, bool]] = {}
_ACL_CACHE_LOCK = threading.Lock()


def _acl_cache_disabled() -> bool:
    return os.environ.get("RXYCODE_DISABLE_ACL_CACHE") == "1"


def _acl_cache_key(path: Path) -> str:
    key = str(path)
    return os.path.normcase(key) if os.name == "nt" else key


def _acl_signature(path: Path) -> tuple[int, int, bool]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0, False)
    return (stat.st_size, stat.st_mtime_ns, True)


def _invalidate_acl_cache(path: Path) -> None:
    with _ACL_CACHE_LOCK:
        _ACL_CACHE.pop(_acl_cache_key(path), None)


def _windows_current_sid_from_token() -> str:
    """Read the process token SID in-process.

    Hosted Windows runners sometimes fail to *start* ``whoami.exe``
    (``STATUS_DLL_INIT_FAILED`` / 3221225794) after many subprocesses.
    The token is already in this process, so no extra executable is required.
    """
    token_query = 0x0008
    token_user = 1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, token_user, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token, token_user, buf, needed.value, ctypes.byref(needed)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        info = ctypes.cast(buf, ctypes.POINTER(TOKEN_USER)).contents
        string_sid = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(info.User.Sid, ctypes.byref(string_sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = string_sid.value or ""
        finally:
            kernel32.LocalFree(string_sid)
    finally:
        kernel32.CloseHandle(token)
    if not _SID_PATTERN.fullmatch(sid):
        raise OSError("Unable to determine the current Windows user SID")
    return sid


def _windows_current_sid_from_whoami() -> str:
    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    row = next(csv.reader(result.stdout.splitlines()))
    sid = row[-1].strip()
    if not _SID_PATTERN.fullmatch(sid):
        raise OSError("Unable to determine the current Windows user SID")
    return sid


def _windows_current_sid() -> str:
    global _cached_windows_sid
    if _cached_windows_sid:
        return _cached_windows_sid
    try:
        sid = _windows_current_sid_from_token()
    except OSError:
        last: BaseException | None = None
        for attempt in range(3):
            try:
                sid = _windows_current_sid_from_whoami()
                break
            except (OSError, subprocess.SubprocessError) as exc:
                last = exc
                time.sleep(0.2 * (attempt + 1))
        else:
            raise OSError("Unable to determine the current Windows user SID") from last
    _cached_windows_sid = sid
    return sid


async def _windows_current_sid_async() -> str:
    """Async variant (C2): the short ``whoami`` command is not a process-class
    tool; it delegates to the sync impl via ``asyncio.to_thread``.  Per
    PHASE-C §4.3 a timeout here only stops waiting — it does not terminate a
    subprocess (there is none to kill)."""
    return await asyncio.to_thread(_windows_current_sid)


def restrict_file_permissions(path: Path) -> None:
    """Restrict a configuration or secret file to trusted local principals."""
    if not path.exists():
        return
    if os.name != "nt":
        os.chmod(path, 0o600)
        return

    cache_key = _acl_cache_key(path)
    signature = _acl_signature(path)
    if not _acl_cache_disabled():
        with _ACL_CACHE_LOCK:
            if _ACL_CACHE.get(cache_key) == signature:
                return
    sid = _windows_current_sid()
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(F)",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        raise OSError("Unable to restrict local configuration file permissions")
    if not _acl_cache_disabled():
        with _ACL_CACHE_LOCK:
            _ACL_CACHE[cache_key] = signature


async def restrict_file_permissions_async(path: Path) -> None:
    """Async variant (C2): short ``icacls`` call delegates via to_thread
    (stop-waiting boundary, PHASE-C §4.3)."""
    await asyncio.to_thread(restrict_file_permissions, path)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably replace *path* from a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        restrict_file_permissions(temporary_path)
        os.replace(temporary_path, path)
        # 写后主动失效缓存条目：目标文件内容已变化，而一次性临时文件名
        # 滞留在缓存里只会泄漏。
        _invalidate_acl_cache(temporary_path)
        _invalidate_acl_cache(path)
        restrict_file_permissions(path)
        _fsync_directory(path.parent)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        _invalidate_acl_cache(temporary_path)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


_FILE_LOCK_STATE = threading.local()


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Lock *path* across processes for a read-modify-write.

    ``os.replace`` keeps a single write atomic. It does not stop two
    processes from each reading the old file and then replacing it.
    The same thread may re-enter; another thread or process waits.
    """
    key = str(path)
    depth = int(getattr(_FILE_LOCK_STATE, "depth", 0) or 0)
    if depth and getattr(_FILE_LOCK_STATE, "key", None) == key:
        _FILE_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            _FILE_LOCK_STATE.depth = depth
        return

    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() < 1:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 5.0
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    time.sleep(0.02)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _FILE_LOCK_STATE.depth = 1
        _FILE_LOCK_STATE.key = key
        try:
            yield
        finally:
            _FILE_LOCK_STATE.depth = 0
            _FILE_LOCK_STATE.key = None
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def _dpapi_transform(payload: bytes, *, decrypt: bool) -> bytes:
    input_buffer = ctypes.create_string_buffer(payload)
    input_blob = _DataBlob(len(payload), ctypes.cast(input_buffer, ctypes.c_void_p))
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    description = None if decrypt else "RxyCode model credential"
    if not function(
        ctypes.byref(input_blob),
        None if decrypt else description,
        None,
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


_KEYRING_SERVICE = "rxycode.credentials"


def _keyring_available() -> bool:
    """True when a desktop keyring backend is importable and usable."""
    try:
        import keyring  # noqa: F401

        return True
    except Exception:
        return False


def _protect(value: str, reference: str | None = None) -> str:
    """Encrypt *value* for the current user.

    Windows: DPAPI.  POSIX with a desktop keyring (macOS Keychain / Linux
    Secret Service): the raw secret lives in the OS keyring keyed by
    *reference*, and only a ``keyring-v1:<reference>`` marker is persisted.
    POSIX without a keyring (CI / headless): owner-only file, base64 value.
    """
    if _os_name == "nt":
        payload = value.encode("utf-8")
        protected = _dpapi_transform(payload, decrypt=False)
        return "dpapi-v1:" + base64.b64encode(protected).decode("ascii")
    if reference is not None and _keyring_available():
        try:
            import keyring

            keyring.set_password(_KEYRING_SERVICE, reference, value)
            return "keyring-v1:" + reference
        except Exception:
            # Keyring unusable at runtime (locked keychain, no DBus): fall back.
            pass
    payload = value.encode("utf-8")
    return "file-v1:" + base64.b64encode(payload).decode("ascii")


def _unprotect(value: str) -> str:
    if value.startswith("dpapi-v1:"):
        if _os_name != "nt":
            raise ValueError("This credential is bound to a Windows user account")
        payload = _dpapi_transform(
            base64.b64decode(value[9:], validate=True), decrypt=True
        )
        return payload.decode("utf-8")
    if value.startswith("file-v1:"):
        payload = base64.b64decode(value[8:], validate=True)
        return payload.decode("utf-8")
    if value.startswith("keyring-v1:"):
        reference = value[len("keyring-v1:"):]
        try:
            import keyring

            secret = keyring.get_password(_KEYRING_SERVICE, reference)
        except Exception:
            secret = None
        if not secret:
            raise ValueError("Stored model credential is unavailable")
        return secret
    raise ValueError("Unsupported credential storage format")


def _secret_path(config_path: Path) -> Path:
    return config_path.parent / SECRET_FILE_NAME


def _read_store(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    restrict_file_permissions(path)
    if not _acl_cache_disabled():
        cache_key = _read_store_cache_key(path)
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        cached = _READ_STORE_CACHE.get(cache_key)
        if cached is not None and cached[0] == signature:
            return dict(cached[1])
    with path.open("r", encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}
    if document.get("version") != _STORE_VERSION:
        raise ValueError("Unsupported credential store version")
    credentials = document.get("credentials", {})
    if not isinstance(credentials, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in credentials.items()
    ):
        raise ValueError("Invalid credential store")
    if not _acl_cache_disabled():
        _READ_STORE_CACHE[cache_key] = (signature, dict(credentials))
    return credentials


def _write_store(path: Path, credentials: dict[str, str]) -> None:
    document = {"version": _STORE_VERSION, "credentials": credentials}
    text = yaml.safe_dump(document, allow_unicode=True, sort_keys=True)
    atomic_write_text(path, text)
    # 写入后主动失效：下一次读必须拿到新内容，而不是本进程旧缓存。
    _invalidate_read_store_cache(path)


def store_credential(value: str, config_path: Path) -> str:
    return store_credentials([value], config_path)[0]


def _credential_rmw_pause() -> None:
    """Test-only gap between a credential read and its write.

    Unset in production. A positive ``RXYCODE_CREDENTIAL_RMW_PAUSE`` makes
    two processes overlap inside the read-modify-write so a missing
    cross-process lock fails closed instead of passing by timing.
    """
    raw = os.environ.get("RXYCODE_CREDENTIAL_RMW_PAUSE", "").strip()
    if not raw:
        return
    time.sleep(float(raw))


def store_credentials(values: list[str], config_path: Path) -> list[str]:
    """Protect every value under its own reference and write the store once.

    References are not shared. Deleting or rolling back one model removes
    only that reference.
    """
    cleaned = [value.strip() for value in values]
    if any(not item for item in cleaned):
        raise ValueError("Credential must not be empty")
    if not cleaned:
        return []
    path = _secret_path(config_path)
    references: list[str] = []
    # File lock outside the in-process lock. Never take the config lock
    # while this credential lock is held; config edits run before or after.
    with exclusive_file_lock(path):
        with _STORE_LOCK:
            credentials = _read_store(path)
            _credential_rmw_pause()
            for value in cleaned:
                reference = uuid.uuid4().hex
                credentials[reference] = _protect(value, reference)
                references.append(reference)
            _write_store(path, credentials)
    return references


def load_credential(reference: str, config_path: Path) -> str:
    if not isinstance(reference, str) or not _REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError("Invalid credential reference")
    path = _secret_path(config_path)
    with _STORE_LOCK:
        credentials = _read_store(path)
        protected = credentials.get(reference)
    if protected is None:
        raise ValueError("Stored model credential is unavailable")
    return _unprotect(protected)


def delete_credentials(references: list[str], config_path: Path) -> None:
    """Drop many references in one store write. Unknown refs are ignored."""
    path = _secret_path(config_path)
    keyring_refs: list[str] = []
    with exclusive_file_lock(path):
        with _STORE_LOCK:
            credentials = _read_store(path)
            _credential_rmw_pause()
            changed = False
            for reference in references:
                if not isinstance(reference, str) or not _REFERENCE_PATTERN.fullmatch(reference):
                    continue
                current = credentials.get(reference)
                if current is None:
                    continue
                if str(current).startswith("keyring-v1:"):
                    keyring_refs.append(reference)
                del credentials[reference]
                changed = True
            if changed:
                _write_store(path, credentials)
    for reference in keyring_refs:
        try:
            import keyring

            keyring.delete_password(_KEYRING_SERVICE, reference)
        except Exception:
            pass


def delete_credential(reference: str, config_path: Path) -> None:
    # 单条删除走 delete_credentials，避免再维护第二份读写。
    if not isinstance(reference, str) or not _REFERENCE_PATTERN.fullmatch(reference):
        return
    delete_credentials([reference], config_path)
