"""BM25-based memory search across all memory files."""

import math
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir


@dataclass
class SearchResult:
    path: str
    score: float
    snippet: str


# Common English stopwords to filter out
_STOPWORDS = frozenset({
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
    'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'both',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
    'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't',
    'just', 'don', 'now', 'and', 'but', 'or', 'if', 'while', 'that',
    'this', 'these', 'those', 'it', 'its', 'i', 'me', 'my', 'we', 'our',
    'you', 'your', 'he', 'him', 'his', 'she', 'her', 'they', 'them', 'their',
    'what', 'which', 'who', 'whom',
})

# Common Chinese stopwords to filter out
_CJK_STOPWORDS = frozenset({
    '\u7684', '\u4e86', '\u5728', '\u662f', '\u6211', '\u6709', '\u548c', '\u5c31', '\u4e0d', '\u4eba', '\u90fd', '\u4e00',
    '\u4e00\u4e2a', '\u4e0a', '\u4e5f', '\u5f88', '\u5230', '\u8bf4', '\u8981', '\u53bb', '\u4f60', '\u4f1a', '\u7740', '\u6ca1\u6709',
    '\u770b', '\u597d', '\u81ea\u5df1', '\u8fd9', '\u4ed6', '\u5979', '\u5b83', '\u4eec', '\u6211\u4eec', '\u4f60\u4eec', '\u4ed6\u4eec',
    '\u90a3', '\u91cc', '\u4e48', '\u628a', '\u8ba9', '\u88ab', '\u4ece', '\u56e0\u4e3a', '\u6240\u4ee5', '\u4f46\u662f', '\u800c',
    '\u5982\u679c', '\u867d\u7136', '\u53ef\u4ee5', '\u5df2\u7ecf', '\u8fd8\u662f', '\u6216\u8005', '\u4ee5\u53ca', '\u800c\u4e14', '\u4f46',
})


def _tokenize(text: str) -> list[str]:
    cjk = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    cjk_single = re.findall(r'[\u4e00-\u9fff]', text)
    ascii_tokens = re.findall(r'[a-zA-Z0-9_]+', text.lower())
    cjk = [t for t in cjk if t not in _CJK_STOPWORDS]
    cjk_single = [t for t in cjk_single if t not in _CJK_STOPWORDS]
    ascii_tokens = [t for t in ascii_tokens if t not in _STOPWORDS and len(t) > 1]
    return cjk + cjk_single + ascii_tokens


def _collect_memory_dirs() -> list[Path]:
    base = get_data_dir() / "memory"
    if not base.exists():
        return []
    dirs = []
    for sub in ["sessions", "user", "projects"]:
        p = base / sub
        if p.exists():
            dirs.append(p)
    return dirs


def _iter_markdown_files(dirs: list[Path]):
    for d in dirs:
        yield from d.rglob("*.md")


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = []
        self.doc_paths: list[str] = []
        self.doc_lengths: list[int] = []
        self.avgdl: float = 0.0
        self.df: dict[str, int] = {}

    def add_document(self, path: str, text: str):
        tokens = _tokenize(text)
        if not tokens:
            return
        self.docs.append(tokens)
        self.doc_paths.append(path)
        self.doc_lengths.append(len(tokens))
        seen = set(tokens)
        for t in seen:
            self.df[t] = self.df.get(t, 0) + 1
        n = len(self.docs)
        if n > 0:
            self.avgdl = sum(self.doc_lengths) / n

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        query_tokens = _tokenize(query)
        if not query_tokens or not self.docs:
            return []
        n = len(self.docs)
        scores = [0.0] * n
        for qt in query_tokens:
            df_t = self.df.get(qt, 0)
            if df_t == 0:
                continue
            idf = math.log((n - df_t + 0.5) / (df_t + 0.5) + 1.0)
            for i in range(n):
                tf = self.docs[i].count(qt)
                if tf == 0:
                    continue
                dl = self.doc_lengths[i]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[i] += idf * numerator / denominator

        ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)[:top_k]
        results = []
        for i in ranked:
            if scores[i] <= 0:
                break
            snippet = self._make_snippet(self.docs[i], query_tokens)
            results.append(SearchResult(
                path=self.doc_paths[i],
                score=round(scores[i], 4),
                snippet=snippet,
            ))
        return results

    def _make_snippet(self, tokens: list[str], query_tokens: list[str], window: int = 40) -> str:
        best_pos = 0
        best_count = 0
        for pos in range(len(tokens)):
            end = min(pos + window, len(tokens))
            chunk = tokens[pos:end]
            count = sum(1 for qt in query_tokens if qt in chunk)
            if count > best_count:
                best_count = count
                best_pos = pos
        snippet_tokens = tokens[best_pos:best_pos + window]
        result = []
        for i, tok in enumerate(snippet_tokens):
            if i > 0 and re.match(r'[a-zA-Z0-9]', tok) and re.match(r'[a-zA-Z0-9]', snippet_tokens[i-1]):
                result.append(' ')
            result.append(tok)
        return "".join(result)

    def build_index(self):
        dirs = _collect_memory_dirs()
        for fp in _iter_markdown_files(dirs):
            try:
                text = fp.read_text(encoding="utf-8")
                self.add_document(str(fp), text)
            except (OSError, UnicodeDecodeError):
                continue


def search_memory(query: str, top_k: int = 10) -> list[SearchResult]:
    bm25 = BM25()
    bm25.build_index()
    return bm25.search(query, top_k=top_k)
