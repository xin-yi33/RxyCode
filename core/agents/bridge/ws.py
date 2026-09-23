# 废弃代码（2026-09-22）：WsChannel 没有任何导入方。现网桥接只走 stdio（bridge/stdio.py、worker.py、leader.py）。禁止再引用。

# """WebSocket relay. Real sockets optional; tests inject a mock channel."""
#
# from __future__ import annotations
#
# import json
# from typing import Any
# from urllib.parse import urlparse
#
#
# class WsChannel:
#     """Minimal wss client. Auth is a query/header secret, never logged."""
#
#     def __init__(self, url: str, *, secret: str | None = None) -> None:
#         parsed = urlparse(url)
#         if parsed.scheme not in {"ws", "wss"}:
#             raise ValueError("ws_url must be ws:// or wss://")
#         self.url = url
#         self._secret = secret
#         self._closed = False
#         try:
#             import websocket  # type: ignore
#         except ImportError as exc:  # pragma: no cover - exercised via mock
#             raise RuntimeError("websocket-client is required for live WS bridge") from exc
#         header = []
#         if secret:
#             header.append(f"Authorization: Bearer {secret}")
#         self._ws = websocket.create_connection(url, header=header, timeout=10)
#
#     def send(self, message: dict[str, Any]) -> None:
#         self._ws.send(json.dumps(message, ensure_ascii=False))
#
#     def recv(self, timeout: float) -> dict[str, Any] | None:
#         self._ws.settimeout(timeout)
#         try:
#             raw = self._ws.recv()
#         except Exception:
#             return None
#         if not raw:
#             return None
#         payload = json.loads(raw)
#         return payload if isinstance(payload, dict) else None
#
#     def close(self) -> None:
#         if not self._closed:
#             self._closed = True
#             try:
#                 self._ws.close()
#             except Exception:
#                 pass
#
#     def kill(self) -> None:
#         self.close()
#
#     def is_alive(self) -> bool:
#         return not self._closed
