"""脱敏只改模型可见文本。落盘原文不经过这里。"""
from __future__ import annotations

_KEYS_BY_FIRST = {
    "a": ("authorization", "api_key", "api-key", "apikey"),
    "p": ("password", "passwd"),
    "s": ("secret",),
    "t": ("token",),
}
_REDACTION_MARKERS = tuple(
    dict.fromkeys(
        (
            "bearer",
            *(key for keys in _KEYS_BY_FIRST.values() for key in keys),
        )
    )
)


def redact_secrets(text: str) -> str:
    """抹掉密钥。引号值可以跨过键和冒号之间的换行；裸值停在本行。"""
    lowered = text.lower()
    if not any(marker in lowered for marker in _REDACTION_MARKERS):
        return text
    return _redact_assignments(_redact_bearer(text))


def _is_name_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _redact_bearer(text: str) -> str:
    out: list[str] = []
    index = 0
    limit = len(text)
    while index < limit:
        if (
            text[index : index + 6].lower() == "bearer"
            and (index == 0 or not _is_name_char(text[index - 1]))
        ):
            cursor = index + 6
            if cursor < limit and text[cursor] in " \t":
                while cursor < limit and text[cursor] in " \t":
                    cursor += 1
                token = cursor
                while token < limit and text[token] not in " \t\r\n\"',;{}\\":
                    token += 1
                if token > cursor:
                    out.append("Bearer ***")
                    index = token
                    continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _key_end(text: str, index: int) -> int | None:
    limit = len(text)
    if index >= limit:
        return None
    quote = ""
    name_at = index
    if text[index] in "\"'":
        quote = text[index]
        name_at = index + 1
    elif index > 0 and _is_name_char(text[index - 1]):
        return None
    if name_at >= limit:
        return None
    for key in _KEYS_BY_FIRST.get(text[name_at].lower(), ()):
        after = name_at + len(key)
        if after > limit or text[name_at:after].lower() != key:
            continue
        if quote:
            if after < limit and text[after] == quote:
                return after + 1
            continue
        if after < limit and _is_name_char(text[after]):
            continue
        return after
    return None


def _quoted_value_end(text: str, index: int) -> int:
    quote = text[index]
    cursor = index + 1
    limit = len(text)
    while cursor < limit and text[cursor] not in "\r\n":
        if text[cursor] == "\\":
            if cursor + 1 < limit and text[cursor + 1] not in "\r\n":
                cursor += 2
                continue
            return cursor + 1
        if text[cursor] == quote:
            return cursor + 1
        cursor += 1
    return cursor


def _assignment_at(text: str, key_end: int) -> tuple[str, int] | None:
    limit = len(text)
    cursor = key_end
    while cursor < limit and text[cursor] in " \t\r\n":
        cursor += 1
    if cursor >= limit or text[cursor] not in ":=":
        return None
    separator = cursor
    probe = separator + 1
    while probe < limit and text[probe] in " \t\r\n":
        probe += 1
    if probe < limit and text[probe] in "\"'":
        value_end = _quoted_value_end(text, probe)
        quote = text[probe]
        return text[key_end:probe] + quote + "***" + quote, value_end
    bare = separator + 1
    while bare < limit and text[bare] in " \t":
        bare += 1
    if bare >= limit or text[bare] in "\r\n\"'":
        return None
    value_end = bare
    while value_end < limit and text[value_end] not in " \t\r\n\"',;{}":
        value_end += 1
    if value_end == bare:
        return None
    return text[key_end:bare] + "***", value_end


def _redact_assignments(text: str) -> str:
    out: list[str] = []
    index = 0
    limit = len(text)
    while index < limit:
        key_end = _key_end(text, index)
        if key_end is not None:
            replaced = _assignment_at(text, key_end)
            if replaced is not None:
                suffix, next_index = replaced
                out.append(text[index:key_end])
                out.append(suffix)
                index = next_index
                continue
        out.append(text[index])
        index += 1
    return "".join(out)
