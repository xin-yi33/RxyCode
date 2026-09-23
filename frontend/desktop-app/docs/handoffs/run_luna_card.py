"""Phase G frontend luna audit. Key from OPENCODE_GO_API_KEY or TEMP file only."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY_CHAT = "https://opencode.ai/zen/go/v1/chat/completions"
GATEWAY_RESP = "https://opencode.ai/zen/go/v1/responses"
MODEL = "gpt-5.6-luna"


def load_key() -> str:
    env = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if env:
        return env
    temp = Path(os.environ.get("TEMP", "/tmp")) / "rxycode-luna.key"
    if temp.is_file():
        return temp.read_text(encoding="utf-8").strip()
    raise SystemExit("OPENCODE_GO_API_KEY missing")


def post(url: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "rxycode-phaseg-luna-audit/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_text(payload: dict) -> str:
    if "choices" in payload:
        return payload["choices"][0]["message"]["content"]
    if "output_text" in payload and isinstance(payload["output_text"], str):
        return payload["output_text"]
    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    chunks.append(str(content.get("text", "")))
        return "\n".join(chunks)
    return json.dumps(payload, ensure_ascii=False)[:4000]


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: run_luna_card.py CARD_ID PROMPT_FILE [OUT_FILE]", file=sys.stderr)
        return 2
    card = sys.argv[1]
    prompt = Path(sys.argv[2]).read_text(encoding="utf-8")
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(sys.argv[2]).with_suffix(".luna.txt")
    key = load_key()
    try:
        payload = post(
            GATEWAY_RESP,
            {"model": MODEL, "input": prompt, "max_output_tokens": 2500},
            key,
        )
    except urllib.error.HTTPError:
        payload = post(
            GATEWAY_CHAT,
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2500,
                "temperature": 0.2,
            },
            key,
        )
    text = extract_text(payload)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n# luna card={card} wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
