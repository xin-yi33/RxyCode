"""Appserver test fixture: respond to initialize only."""
import json
import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("method") == "initialize" and "id" in msg:
            sys.stdout.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True}},
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
