"""Local, deterministic OpenAI-compatible HTTPS provider for clipboard E2E.

This is a wire-level control provider, not a live model or an agent stub. The
production OpenTUI -> appserver -> worker -> AgentV2 path still runs normally;
only the remote model endpoint is replaced with a loopback server.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import ipaddress
import json
import re
import ssl
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image


SYNTHETIC_API_KEY = "clipboard-e2e-local-only-not-a-secret"
SYNTHETIC_USAGE = {"prompt_tokens": 37, "completion_tokens": 11, "total_tokens": 48}


@dataclass
class ProviderCase:
    name: str
    read_marker: str
    read_path: str
    file_marker: str
    final_text: str = "E2E_CLIPBOARD_FINAL_OK"
    require_image: bool = False
    gate: threading.Event | None = None
    gated_marker: str | None = None
    gate_reached: threading.Event = field(default_factory=threading.Event)


def _create_ephemeral_server_certificate(directory: Path) -> tuple[Path, Path, str]:
    """Create a short-lived localhost leaf and private CA in the run tempdir."""
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RxyCode clipboard E2E ephemeral CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / "ephemeral-test-ca.pem"
    cert_path = directory / "localhost-cert.pem"
    key_path = directory / "localhost-key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    digest = hashlib.sha256(ca_path.read_bytes()).hexdigest()
    return ca_path, cert_path, digest


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
    )


def _image_urls(messages: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") not in {
                "image_url",
                "input_image",
            }:
                continue
            value = part.get("image_url", part)
            if isinstance(value, dict):
                value = value.get("url")
            if isinstance(value, str):
                result.append(value)
    return result


def _safe_content(content: Any) -> Any:
    """Keep synthetic text, but never persist image base64 payloads."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    safe: list[Any] = []
    for part in content:
        if not isinstance(part, dict):
            safe.append(part)
            continue
        if part.get("type") in {"image_url", "input_image"}:
            url = part.get("image_url", part)
            if isinstance(url, dict):
                url = url.get("url", "")
            raw = str(url)
            match = re.fullmatch(r"data:([^;,]+);base64,(.+)", raw, re.DOTALL)
            safe.append(
                {
                    "type": part.get("type"),
                    "mime": match.group(1) if match else None,
                    "payload_sha256": hashlib.sha256(
                        base64.b64decode(match.group(2), validate=True)
                        if match
                        else raw.encode("utf-8")
                    ).hexdigest(),
                    "payload_bytes": len(base64.b64decode(match.group(2), validate=True))
                    if match
                    else None,
                }
            )
        else:
            safe.append(part)
    return safe


class LocalOpenAIProvider:
    """Loopback TLS Chat Completions endpoint with inspectable synthetic traces."""

    def __init__(self, temp_dir: Path, evidence_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.evidence_dir = evidence_dir
        self.ca_path, cert_path, self.ca_sha256 = _create_ephemeral_server_certificate(
            temp_dir / "tls"
        )
        self._condition = threading.Condition()
        self._case: ProviderCase | None = None
        self._requests: list[dict[str, Any]] = []
        self._request_trace: list[dict[str, Any]] = []
        self._decision_trace: list[dict[str, Any]] = []
        self._server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._handler_type()
        )
        self._server.daemon_threads = True
        self._server.allow_reuse_address = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert_path), str(temp_dir / "tls" / "localhost-key.pem"))
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self.port = int(self._server.server_address[1])
        self.base_url = f"https://127.0.0.1:{self.port}/v1"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="clipboard-e2e-loopback-provider",
            daemon=True,
        )
        self._thread.start()

    def _handler_type(self):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *args: object) -> None:
                # Request paths and bodies are kept only in the sanitized trace.
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.client_address[0] != "127.0.0.1" or self.path != "/v1/health":
                    self.send_error(404)
                    return
                payload = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                if self.client_address[0] != "127.0.0.1":
                    self.send_error(403)
                    return
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                if self.headers.get("Authorization") != f"Bearer {SYNTHETIC_API_KEY}":
                    self._json_error(401, "synthetic local credential missing")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 32 * 1024 * 1024:
                        raise ValueError("request body outside test bounds")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("request body must be an object")
                except Exception:
                    self._json_error(400, "invalid test request")
                    return
                decision = owner._capture_and_decide(body)
                gate = decision.pop("gate", None)
                if gate is not None:
                    gate_reached = decision.pop("gate_reached")
                    gate_reached.set()
                    if not gate.wait(25):
                        self._json_error(504, "test response gate timed out")
                        return
                if body.get("stream"):
                    self._stream_response(body, decision)
                else:
                    self._json_response(200, owner._completion(body, decision))

            def _json_error(self, status: int, message: str) -> None:
                payload = json.dumps(
                    {"error": {"message": message, "type": "clipboard_e2e"}}
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

            def _json_response(self, status: int, value: dict[str, Any]) -> None:
                payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

            def _stream_response(self, body: dict[str, Any], decision: dict[str, Any]) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                completion_id = f"chatcmpl-clipboard-e2e-{decision['ordinal']}"
                model = str(body.get("model") or "gpt-4.1")

                def send(chunk: dict[str, Any]) -> None:
                    self.wfile.write(
                        b"data: "
                        + json.dumps(chunk, ensure_ascii=False).encode("utf-8")
                        + b"\n\n"
                    )
                    self.wfile.flush()

                base = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                }
                response = owner._completion(body, decision)
                message = response["choices"][0]["message"]
                if message.get("tool_calls"):
                    tool = message["tool_calls"][0]
                    send(
                        {
                            **base,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": tool["id"],
                                                "type": "function",
                                                "function": tool["function"],
                                            }
                                        ],
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    finish_reason = "tool_calls"
                else:
                    send(
                        {
                            **base,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"role": "assistant", "content": message.get("content", "")},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    finish_reason = "stop"
                send(
                    {
                        **base,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    }
                )
                send({**base, "choices": [], "usage": dict(SYNTHETIC_USAGE)})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        return Handler

    def set_case(self, case: ProviderCase) -> None:
        with self._condition:
            self._case = case

    def verify_tls_client(self) -> dict[str, Any]:
        """Prove a normal verified TLS client trusts only this ephemeral CA."""
        context = ssl.create_default_context(cafile=str(self.ca_path))
        with urllib.request.urlopen(
            self.base_url + "/health", context=context, timeout=3
        ) as response:
            payload = json.loads(response.read(1024))
            if response.status != 200 or payload != {"ok": True}:
                raise RuntimeError("local HTTPS provider TLS self-check failed")
            return {
                "verified": True,
                "ca_sha256": self.ca_sha256,
                "server": "127.0.0.1",
                "trust_scope": "ephemeral test CA; no system trust store changes",
            }

    def _capture_and_decide(self, body: dict[str, Any]) -> dict[str, Any]:
        messages = body.get("messages")
        messages = messages if isinstance(messages, list) else []
        last_user = next(
            (
                (index, item)
                for index, item in reversed(list(enumerate(messages)))
                if isinstance(item, dict) and item.get("role") == "user"
            ),
            (len(messages), {}),
        )
        user_index, user_message = last_user
        user_text = _text_from_content(user_message.get("content"))
        image_urls = _image_urls([user_message] if isinstance(user_message, dict) else [])
        image_observations = [self._inspect_data_image(url) for url in image_urls]
        with self._condition:
            case = self._case
            ordinal = len(self._requests) + 1
            captured = {
                "ordinal": ordinal,
                "at_monotonic": time.monotonic(),
                "body": body,
                "latest_user_text": user_text,
                "image_observations": image_observations,
            }
            self._requests.append(captured)
            self._request_trace.append(
                {
                    "ordinal": ordinal,
                    "model": body.get("model"),
                    "stream": bool(body.get("stream")),
                    "message_count": len(messages),
                    "latest_user_text": user_text,
                    "messages": [
                        {
                            "role": message.get("role"),
                            "content": _safe_content(message.get("content")),
                            "tool_call_names": [
                                call.get("function", {}).get("name")
                                for call in message.get("tool_calls", [])
                                if isinstance(call, dict)
                            ],
                        }
                        for message in messages
                        if isinstance(message, dict)
                    ],
                    "image_observations": image_observations,
                    "tools": [
                        item.get("function", {}).get("name")
                        for item in body.get("tools", [])
                        if isinstance(item, dict)
                    ],
                    "synthetic_usage": dict(SYNTHETIC_USAGE),
                    "usage_is_synthetic": True,
                }
            )
            self._condition.notify_all()

        if case is None:
            return {"ordinal": ordinal, "text": "E2E_PROVIDER_CASE_NOT_CONFIGURED"}

        decision: dict[str, Any] = {"ordinal": ordinal, "text": case.final_text}
        if case.gated_marker and case.gated_marker in user_text and case.gate:
            decision["gate"] = case.gate
            decision["gate_reached"] = case.gate_reached

        if case.read_marker and case.read_marker in user_text:
            tool_followup = any(
                isinstance(message, dict) and message.get("role") == "tool"
                for message in messages[user_index + 1 :]
            )
            if not tool_followup:
                tool_names = {
                    item.get("function", {}).get("name")
                    for item in body.get("tools", [])
                    if isinstance(item, dict)
                }
                if "read" in tool_names:
                    decision["tool_call"] = {
                        "id": f"call-clipboard-read-{ordinal}",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps(
                                {"filePath": case.read_path, "offset": 1, "limit": 20},
                                ensure_ascii=False,
                            ),
                        },
                    }
                else:
                    decision["text"] = "E2E_READ_TOOL_NOT_OFFERED"
            else:
                tool_text = "\n".join(
                    str(message.get("content", ""))
                    for message in messages[user_index + 1 :]
                    if isinstance(message, dict) and message.get("role") == "tool"
                )
                if case.file_marker not in tool_text:
                    decision["text"] = "E2E_READ_RESULT_MISSING"

        if image_urls:
            decision["image_observations"] = image_observations
        if case.require_image:
            valid = bool(image_observations) and all(
                item.get("valid_data_image") and item.get("format") == "PNG"
                for item in image_observations
            )
            if not valid:
                decision["text"] = "E2E_IMAGE_PAYLOAD_INVALID"
        with self._condition:
            self._decision_trace.append(
                {
                    "ordinal": ordinal,
                    "case": case.name,
                    "tool_call": decision.get("tool_call", {}).get("function", {}).get("name"),
                    "tool_result_marker_seen": case.file_marker in str(
                        [message.get("content", "") for message in messages if isinstance(message, dict) and message.get("role") == "tool"]
                    ),
                    "image_observations": image_observations,
                    "decision_text": decision.get("text"),
                }
            )
        return decision

    @staticmethod
    def _inspect_data_image(url: str) -> dict[str, Any]:
        match = re.fullmatch(r"data:(image/[^;,]+);base64,(.+)", url, re.DOTALL)
        if not match:
            return {"valid_data_image": False, "error": "not a base64 image data URL"}
        try:
            raw = base64.b64decode(match.group(2), validate=True)
            with Image.open(__import__("io").BytesIO(raw)) as image:
                image.load()
                pixel = image.convert("RGB").getpixel((0, 0))
                return {
                    "valid_data_image": True,
                    "mime": match.group(1),
                    "format": image.format,
                    "size": list(image.size),
                    "pixel_0_0_rgb": list(pixel),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
        except Exception as exc:
            return {"valid_data_image": False, "error_type": type(exc).__name__}

    def _completion(self, body: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": decision.get("text", "")}
        tool_call = decision.get("tool_call")
        if tool_call:
            message["tool_calls"] = [tool_call]
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"
        return {
            "id": f"chatcmpl-clipboard-e2e-{decision['ordinal']}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": str(body.get("model") or "gpt-4.1"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": dict(SYNTHETIC_USAGE),
        }

    def wait_for_request(
        self,
        predicate,
        *,
        timeout: float = 60.0,
        after: int = 0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for request in self._requests[after:]:
                    if predicate(request):
                        return request
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for local provider request")
                self._condition.wait(min(remaining, 0.25))

    @property
    def requests(self) -> list[dict[str, Any]]:
        with self._condition:
            return list(self._requests)

    @property
    def request_trace(self) -> list[dict[str, Any]]:
        with self._condition:
            return list(self._request_trace)

    @property
    def decision_trace(self) -> list[dict[str, Any]]:
        with self._condition:
            return list(self._decision_trace)

    def save_trace(self) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / "provider-requests.jsonl"
        rows = self.request_trace
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        decisions = self.evidence_dir / "provider-decisions.jsonl"
        decisions.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.decision_trace),
            encoding="utf-8",
        )
        return path

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("loopback provider thread did not stop")
