"""Appserver test fixture: read stdin, never write JSON-RPC responses."""
import sys

def main() -> None:
    for _ in sys.stdin:
        pass

if __name__ == "__main__":
    main()
