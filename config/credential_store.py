"""Private, atomic storage for model credentials.

The public YAML configuration contains only opaque credential references.
Windows values are protected with the current user's DPAPI key.  POSIX has no
portable stdlib keyring, so values live in a separate owner-only file.
"""

from __future__ import annotations

import base64
import csv
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid

import yaml


SECRET_FILE_NAME = "credentials.yaml"
_STORE_VERSION = 1
_STORE_LOCK = threading.RLock()
_REFERENCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SID_PATTERN = re.compile(r"^S-\d(?:-\d+)+$")


def _windows_current_sid() -> str:
    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    row = next(csv.reader(result.stdout.splitlines()))
    sid = row[-1].strip()
    if not _SID_PATTERN.fullmatch(sid):
        raise OSError("Unable to determine the current Windows user SID")
    return sid


def restrict_file_permissions(path: Path) -> None:
    """Restrict a configuration or secret file to trusted local principals."""
    if not path.exists():
        return
    if os.name != "nt":
        os.chmod(path, 0o600)
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
        timeout=15,
    )
    if result.returncode != 0:
        raise OSError("Unable to restrict local configuration file permissions")


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
        restrict_file_permissions(path)
        _fsync_directory(path.parent)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


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


def _protect(value: str) -> str:
    payload = value.encode("utf-8")
    if os.name == "nt":
        protected = _dpapi_transform(payload, decrypt=False)
        prefix = "dpapi-v1:"
    else:
        protected = payload
        prefix = "file-v1:"
    return prefix + base64.b64encode(protected).decode("ascii")


def _unprotect(value: str) -> str:
    if value.startswith("dpapi-v1:"):
        if os.name != "nt":
            raise ValueError("This credential is bound to a Windows user account")
        payload = _dpapi_transform(
            base64.b64decode(value[9:], validate=True), decrypt=True
        )
    elif value.startswith("file-v1:"):
        payload = base64.b64decode(value[8:], validate=True)
    else:
        raise ValueError("Unsupported credential storage format")
    return payload.decode("utf-8")


def _secret_path(config_path: Path) -> Path:
    return config_path.parent / SECRET_FILE_NAME


def _read_store(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    restrict_file_permissions(path)
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
    return credentials


def _write_store(path: Path, credentials: dict[str, str]) -> None:
    document = {"version": _STORE_VERSION, "credentials": credentials}
    text = yaml.safe_dump(document, allow_unicode=True, sort_keys=True)
    atomic_write_text(path, text)


def store_credential(value: str, config_path: Path) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Credential must not be empty")
    path = _secret_path(config_path)
    with _STORE_LOCK:
        credentials = _read_store(path)
        reference = uuid.uuid4().hex
        credentials[reference] = _protect(value)
        _write_store(path, credentials)
    return reference


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


def delete_credential(reference: str, config_path: Path) -> None:
    if not isinstance(reference, str) or not _REFERENCE_PATTERN.fullmatch(reference):
        return
    path = _secret_path(config_path)
    with _STORE_LOCK:
        credentials = _read_store(path)
        if reference not in credentials:
            return
        del credentials[reference]
        _write_store(path, credentials)
