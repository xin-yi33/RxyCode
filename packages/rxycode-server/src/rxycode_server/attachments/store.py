"""Attachment object storage. S3 in deployed mode, a rooted directory in dev/test.

Both implementations expose the same three verbs so the API and the worker
stay storage-agnostic. Keys are always namespaced under ``tenants/{id}/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class BlobConfig:
    """One attachment store. ``kind`` is "s3" or "fs"."""

    kind: str
    root: str = ""
    endpoint: str = ""
    bucket: str = ""
    access_key: str = ""
    secret_key: str = ""


def blob_config_from_env(prefix: str = "RXYCODE_ATTACHMENTS") -> BlobConfig:
    root = os.environ.get(f"{prefix}_ROOT", "").strip()
    endpoint = os.environ.get("RXYCODE_S3_ENDPOINT", "").strip()
    bucket = os.environ.get("RXYCODE_S3_BUCKET", "").strip()
    key = os.environ.get("RXYCODE_S3_ACCESS_KEY", "").strip()
    secret = os.environ.get("RXYCODE_S3_SECRET_KEY", "").strip()
    if endpoint and bucket and key and secret:
        return BlobConfig("s3", endpoint=endpoint, bucket=bucket, access_key=key, secret_key=secret)
    if not root:
        root = str(Path.home() / ".rxycode" / "attachments")
    return BlobConfig("fs", root=root)


class BlobStore:
    def put_stream(self, object_key: str, stream: BinaryIO, *, content_type: str) -> int:
        raise NotImplementedError

    def open_read(self, object_key: str) -> BinaryIO:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


class S3BlobStore(BlobStore):
    def __init__(self, config: BlobConfig) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            self._client.create_bucket(Bucket=self._bucket)
        self._client.put_bucket_acl(Bucket=self._bucket, ACL="private")

    def put_stream(self, object_key: str, stream: BinaryIO, *, content_type: str) -> int:
        self._client.upload_fileobj(stream, self._bucket, object_key)
        return 0

    def open_read(self, object_key: str) -> BinaryIO:
        return self._client.get_object(Bucket=self._bucket, Key=object_key)["Body"]

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)


class FSBlobStore(BlobStore):
    def __init__(self, config: BlobConfig) -> None:
        self._root = Path(config.root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        candidate = (self._root / object_key).resolve()
        if not str(candidate).startswith(str(self._root) + os.sep):
            raise ValueError("object key escapes attachment root")
        return candidate

    def put_stream(self, object_key: str, stream: BinaryIO, *, content_type: str) -> int:
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        written = 0
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
            os.replace(tmp, target)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return written

    def open_read(self, object_key: str) -> BinaryIO:
        return open(self._path(object_key), "rb")

    def delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink(missing_ok=True)
        except OSError:
            pass


def open_store(config: BlobConfig) -> BlobStore:
    if config.kind == "s3":
        return S3BlobStore(config)
    return FSBlobStore(config)
