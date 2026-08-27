"""Protocol package version."""

PROTOCOL_VERSION = "1.1.0"
PROTOCOL_VERSION_MIN = "1.0.0"
PROTOCOL_VERSION_MAX = "1.1.0"
APPSERVER_VERSION = "1.2.10"


def parse_protocol_version(value: str) -> tuple[int, ...]:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty protocol version")
    parts: list[int] = []
    for item in text.split("."):
        if not item.isdigit():
            raise ValueError(f"invalid protocol version: {value!r}")
        parts.append(int(item))
    return tuple(parts)


def protocol_version_compatible(client_version: str) -> bool:
    """Empty version is treated as unspecified (legacy clients)."""
    text = (client_version or "").strip()
    if not text:
        return True
    try:
        version = parse_protocol_version(text)
    except ValueError:
        return False
    return (
        parse_protocol_version(PROTOCOL_VERSION_MIN)
        <= version
        <= parse_protocol_version(PROTOCOL_VERSION_MAX)
    )
