"""LSP client - communicates with language servers via JSON-RPC."""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Diagnostic:
    """LSP diagnostic (error/warning)."""
    file_path: str
    line: int
    column: int
    severity: str  # "error", "warning", "info", "hint"
    message: str
    source: str = ""


class LSPClient:
    """Language Server Protocol client."""

    SEVERITY_MAP = {1: "error", 2: "warning", 3: "info", 4: "hint"}

    def __init__(self, name: str, command: str, args: list[str] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._diagnostics: dict[str, list[Diagnostic]] = {}
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._initialized = False

    def start(self, workspace: str = ".") -> bool:
        """Start the language server process."""
        try:
            cmd = [self.command] + self.args
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace,
            )
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Initialize
            resp = self._send_request("initialize", {
                "processId": os.getpid(),
                "rootUri": f"file://{os.path.abspath(workspace)}",
                "capabilities": {},
            })
            if resp:
                self._send_notification("initialized", {})
                self._initialized = True
                return True
            return False
        except FileNotFoundError:
            return False

    def stop(self):
        """Stop the language server."""
        if self._process:
            try:
                self._send_request("shutdown", None)
                self._send_notification("exit", None)
                self._process.terminate()
            except Exception:
                pass
            self._process = None
            self._initialized = False

    def open_file(self, file_path: str, content: str = None):
        """Notify the server that a file was opened."""
        if not self._initialized:
            return
        if content is None:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                return

        uri = f"file://{os.path.abspath(file_path)}"
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": self._get_language_id(file_path),
                "version": 1,
                "text": content,
            }
        })

    def notify_change(self, file_path: str, content: str):
        """Notify the server that a file was changed."""
        if not self._initialized:
            return
        uri = f"file://{os.path.abspath(file_path)}"
        self._send_notification("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": content}],
        })

    def get_diagnostics(self, file_path: str = None) -> list[Diagnostic]:
        """Get diagnostics for a file or all files."""
        with self._lock:
            if file_path:
                abs_path = os.path.abspath(file_path)
                return self._diagnostics.get(abs_path, [])
            else:
                all_diag = []
                for diags in self._diagnostics.values():
                    all_diag.extend(diags)
                return sorted(all_diag, key=lambda d: (d.severity, d.file_path, d.line))

    def get_diagnostics_summary(self, file_path: str = None) -> str:
        """Get a human-readable diagnostics summary."""
        diags = self.get_diagnostics(file_path)
        if not diags:
            return "No diagnostics found."

        errors = sum(1 for d in diags if d.severity == "error")
        warnings = sum(1 for d in diags if d.severity == "warning")
        infos = sum(1 for d in diags if d.severity == "info")

        lines = [f"Diagnostics: {errors} errors, {warnings} warnings, {infos} info"]
        for d in diags[:50]:
            fname = os.path.basename(d.file_path)
            sev = d.severity.upper()[:1]
            lines.append(f"  [{sev}] {fname}:{d.line}:{d.column} {d.message}")
        if len(diags) > 50:
            lines.append(f"  ... and {len(diags) - 50} more")
        return "\n".join(lines)

    def _send_request(self, method: str, params) -> Optional[dict]:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin:
            return None

        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        try:
            body = json.dumps(msg)
            header = f"Content-Length: {len(body)}\r\n\r\n"
            self._process.stdin.write((header + body).encode())
            self._process.stdin.flush()
            return {"ok": True}
        except Exception:
            return None

    def _send_notification(self, method: str, params):
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            body = json.dumps(msg)
            header = f"Content-Length: {len(body)}\r\n\r\n"
            self._process.stdin.write((header + body).encode())
            self._process.stdin.flush()
        except Exception:
            pass

    def _read_loop(self):
        """Read responses and notifications from the server."""
        if not self._process or not self._process.stdout:
            return

        buffer = b""
        while self._process and self._process.poll() is None:
            try:
                chunk = self._process.stdout.read(1)
                if not chunk:
                    break
                buffer += chunk

                # Parse Content-Length header
                if b"\r\n\r\n" in buffer:
                    header_end = buffer.index(b"\r\n\r\n")
                    header = buffer[:header_end].decode()
                    body_start = header_end + 4

                    if "Content-Length:" in header:
                        length = int(header.split("Content-Length:")[1].strip())
                        while len(buffer) < body_start + length:
                            chunk = self._process.stdout.read(body_start + length - len(buffer))
                            if not chunk:
                                break
                            buffer += chunk

                        body = buffer[body_start:body_start + length]
                        buffer = buffer[body_start + length:]

                        try:
                            msg = json.loads(body)
                            self._handle_message(msg)
                        except json.JSONDecodeError:
                            pass
            except Exception:
                break

    def _handle_message(self, msg: dict):
        """Handle a message from the server."""
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "textDocument/publishDiagnostics":
            uri = params.get("uri", "")
            file_path = uri.replace("file://", "")
            diags = []
            for d in params.get("diagnostics", []):
                start = d.get("range", {}).get("start", {})
                diags.append(Diagnostic(
                    file_path=file_path,
                    line=start.get("line", 0) + 1,
                    column=start.get("character", 0) + 1,
                    severity=self.SEVERITY_MAP.get(d.get("severity", 3), "info"),
                    message=d.get("message", ""),
                    source=d.get("source", ""),
                ))
            with self._lock:
                self._diagnostics[file_path] = diags

    def _get_language_id(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        return {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".go": "go", ".rs": "rust", ".java": "java",
            ".c": "c", ".cpp": "cpp", ".h": "c",
        }.get(ext, "plaintext")


# Supported language servers
LSP_SERVERS = {
    "python": {"command": "pyright-langserver", "args": ["--stdio"]},
    "typescript": {"command": "typescript-language-server", "args": ["--stdio"]},
    "go": {"command": "gopls"},
}


def create_lsp_client(language: str, workspace: str = ".") -> Optional[LSPClient]:
    """Create and start an LSP client for the given language."""
    config = LSP_SERVERS.get(language)
    if not config:
        return None

    client = LSPClient(
        name=language,
        command=config["command"],
        args=config.get("args", []),
    )
    if client.start(workspace):
        return client
    return None
