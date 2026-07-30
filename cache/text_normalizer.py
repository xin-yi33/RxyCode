"""Text normalizer for cache key generation."""

import re


def normalize_query(text: str) -> str:
    """Normalize query text for consistent cache matching.

    Rules:
    - Remove extra whitespace
    - Remove filler words
    - Remove punctuation
    - Convert to lowercase
    - Standardize common synonyms
    """
    if not text:
        return ""

    # Remove extra whitespace and newlines
    text = re.sub(r'\s+', ' ', text.strip())

    # Remove Chinese filler words
    cn_fillers = ['请', '帮', '一下', '帮我', '麻烦', '能不能', '可以', '能否', '想', '需要']
    for filler in cn_fillers:
        text = text.replace(filler, '')

    # Remove English filler words
    en_fillers = ['please', 'help', 'can you', 'could you', 'would you', 'i want to', 'i need to']
    for filler in en_fillers:
        text = text.replace(filler, '')

    # Remove punctuation
    text = re.sub(r'[，。？！、；：“”‘’（）【】《》,.?!;:\x22\x27()\[\]{}<>]', '', text)

    # Standardize common synonyms
    synonyms = {
        '查看': '看',
        '查询': '搜索',
        '找一下': '搜索',
        '帮我找': '搜索',
        '创建': '新建',
        '生成': '新建',
        '删除': '移除',
        '修改': '编辑',
        '更新': '编辑',
        'show': 'list',
        'find': 'search',
        'create': 'make',
        'delete': 'remove',
        'update': 'edit',
        'get': 'read',
    }
    for old, new in synonyms.items():
        text = text.replace(old, new)

    return text.strip().lower()


def normalize_tool_args(args: dict) -> str:
    """Normalize tool arguments for fingerprinting."""
    if not args:
        return ""

    # Sort keys for consistent ordering
    sorted_args = sorted(args.items())
    parts = []
    for k, v in sorted_args:
        if isinstance(v, str):
            # Normalize string values
            v = re.sub(r'\s+', ' ', v.strip())
        parts.append(f"{k}={v}")

    return "|".join(parts)


def extract_intent(text: str) -> str:
    """Extract the core intent from a query, removing context/history."""
    # Take only the last sentence (most likely the current request)
    sentences = re.split(r'[。？！\n]', text)
    if sentences:
        return sentences[-1].strip()
    return text.strip()
