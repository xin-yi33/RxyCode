# rag/ - Codebase Vector Search

## What Is This Module?
The rag module provides codebase-level vector search for RxyCode. It chunks source files into embedding-ready segments, generates vector embeddings via an OpenAI-compatible API, stores them in a numpy-backed vector store with brute-force cosine similarity search, and generates repository maps using symbol-graph PageRank ranking.

**Design stitched from:**
- **mentat** (AGPL-3.0): embeddings design pattern — batch requests, local disk cache, graceful degradation
- **aider** (MIT): repo map design — symbol graph extraction + simplified PageRank ranking with token budget

Only design patterns are ported; all implementation is original.

## Architecture

### Key Files
| File | Purpose |
|------|---------|
| `chunker.py` | Code chunker: `CodeChunk` dataclass, `chunk_file()`, `chunk_directory()` |
| `embed.py` | Embedding client: `get_embeddings()`, `is_embedding_available()`, disk cache |
| `store.py` | Vector store: `NumpyVectorStore`, `VectorStore` protocol, `ScoredChunk` |
| `search.py` | Search + repo map: `code_search()` tool, `generate_repomap()` |
| `index.py` | CLI + incremental indexer: `index_project()`, one-worker debounced `BackgroundIndexer`, lifecycle/status APIs |
| `__init__.py` | Package metadata |

### Core Code: chunker.py (Code Chunker)

**Dataclasses:**
- `CodeChunk` — A single chunk: `path`, `symbol_name`, `start_line`, `end_line`, `content`, `language`, `mtime`, `hash`. Supports `to_dict()` / `from_dict()` for JSONL persistence.
- `ScoredChunk` — A chunk with a similarity score (frozen dataclass).

**Chunking Strategy:**
- **Python files**: AST-based — splits by top-level functions/classes, captures module-level preamble (docstring/imports) as a `<module>` chunk
- **Other languages**: Sliding window — 50 lines per window, 10-line overlap
- Skips: binary files (by extension + null-byte detection), files >1 MB, `.gitignore`-listed paths, common noise dirs (`__pycache__`, `node_modules`, `.venv`, etc.)

**Constants:**
- `WINDOW_SIZE = 50`, `WINDOW_OVERLAP = 10`, `MAX_FILE_SIZE = 1 MB`
- `LANG_MAP`: 30+ file extension to language mappings

**Functions:**
- `chunk_file(path) -> list[CodeChunk]`: Chunk a single file (returns empty for binary/oversized/ignored)
- `chunk_directory(root) -> list[CodeChunk]`: Recursively chunk all source files under root, respecting `.gitignore`

### Core Code: embed.py (Embedding Client)

- `get_embeddings(texts, config) -> np.ndarray`: Batch embed texts via OpenAI-compatible `/embeddings` API (64 texts per batch). Returns `(N, dim)` float32 array. Empty array if unavailable.
- `is_embedding_available() -> bool`: Check if embedding is configured and enabled
- `_EmbeddingCache`: Thread-safe disk cache (`~/.rxycode/rag_cache/embeddings.json`), keyed by `sha256(text)[:16]`
- Config resolution: `rag.embedding.base_url` / `api_key` default to None, which means the active model's credentials are reused automatically
- `clear_embedding_cache()`: Clear the on-disk embedding cache

### Core Code: store.py (NumpyVectorStore)

**Protocol:**
- `VectorStore` (runtime_checkable Protocol): `add()`, `search()`, `delete_files()`, `get_indexed_files()`

**NumpyVectorStore:**
- Persistence layout: `~/.rxycode/rag_index/<project_hash>/` containing:
  - `meta.jsonl` — one CodeChunk dict per line
  - `vectors.npy` — `(N, dim)` float32 numpy array
  - `file_index.json` — `{path: {mtime, hash}}` for incremental updates
- `add(chunks, vectors)`: Add or replace chunks for given file paths (re-indexing replaces existing entries)
- `search(query_vec, top_k=8) -> list[ScoredChunk]`: Brute-force cosine similarity search
- `delete_files(paths)`: Remove all chunks for given paths
- `needs_reindex(path, mtime, file_hash) -> bool`: Incremental update check (mtime + hash change detection)
- `get_indexed_files() -> dict`: Return `{path: {mtime, hash}}` for all indexed files
- Thread-safe via `threading.Lock()`

### Core Code: search.py (Code Search + Repo Map)

**Code Search:**
- `code_search(query, top_k=8) -> str`: Search the codebase for code relevant to a natural language query. Uses vector similarity search if embeddings are available, falls back to keyword matching otherwise.
- `_vector_search(query, top_k)`: Vector similarity search via the store
- `_keyword_search(query, top_k)`: Fallback keyword-based search on chunk content (simple word matching, normalized by content length)
- Auto-registered as a `StructuredTool` in the global tool registry on import

**Repo Map (aider-style):**
- `generate_repomap(root, max_tokens=2000) -> str`: Generate a markdown repository map using symbol extraction + PageRank
- `_extract_symbols_python(content)`: AST-based symbol extraction (defs + refs)
- `_extract_symbols_generic(content, language)`: Regex-based for non-Python languages
- `_build_symbol_graph(root)`: Build undirected symbol reference graph
- `_pagerank(graph)`: Simplified PageRank (no networkx dependency, damping=0.85, 30 iterations)
- Symbol ranking: files sorted by max symbol PageRank score, top 8 symbols shown per file, token budget enforced

### Core Code: index.py (CLI + Background Indexer)

- `index_project(root, store) -> int`: Index all source files under root with incremental updates (only re-chunks files whose mtime or hash changed). Uses pseudo-vectors (hash-based deterministic) as fallback when real embeddings are unavailable.
- `start_background_indexer(root, delay=2.0) -> BackgroundIndexer | None`: Reuse one daemon worker per resolved project root. Returns `None` without creating a thread when RAG is disabled.
- `BackgroundIndexer.request_refresh()`: Queue a trailing-edge debounced incremental `index_project()` run. Bursts of code-affecting tool calls update one pending generation instead of spawning threads.
- `BackgroundIndexer.status()`: Report worker state, liveness, generations, success/failure counts, and the last error type without exposing source content.
- `BackgroundIndexer.stop()` / `stop_background_indexer()`: Explicit shutdown; registered workers are also stopped at interpreter exit.
- `_get_project_root() -> Path | None`: Detect project root (looks for `.git` or `pyproject.toml`)
- `_get_store_for_cwd() -> NumpyVectorStore | None`: Get or create a vector store for the current project (cached globally)

Indexing exceptions are recorded but do not kill the worker. A later refresh can recover. A successful refresh also reloads the process-local `code_search` store so it cannot keep serving an old in-memory snapshot.

## Work Flow

1. **Indexing**: `index_project(root)` chunks all source files, generates embeddings (or pseudo-vectors), and stores in `NumpyVectorStore`
2. **Incremental update**: Only re-chunks files whose mtime or content hash has changed since last index
3. **Mutation freshness**: AgentV2's production `tool_call.after` hook invalidates context after a successful write/edit/patch/format/bash/git/workflow-style tool and queues one refresh. Failed and read-only tools do nothing.
4. **Live bridge**: Until that refresh generation succeeds, prompt retrieval reads current files directly. This closes the write-to-index gap without blocking the tool result.
5. **Search**: `code_search(query)` embeds the query, performs cosine similarity search against stored vectors, returns formatted results with file paths, line numbers, and code snippets
6. **Fallback**: If embeddings are unavailable, falls back to keyword matching on chunk content
7. **Repo map**: `generate_repomap(root)` builds a symbol graph, runs PageRank, and generates a markdown map within a token budget

## CLI

```bash
# Index a codebase
python -m rag.index /path/to/project
```

**Background indexing** is started automatically when RAG is enabled in config:
```python
from rag.index import start_background_indexer
indexer = start_background_indexer()  # shared worker, 2s initial delay
generation = indexer.request_refresh() if indexer else None
```

## Configuration

In `config.yaml`:
```yaml
rag:
  enabled: false                    # Enable/disable RAG
  embedding:
    base_url: null                  # Reuse active model's base_url if null
    api_key: null                   # Reuse active model's api_key if null
    model: text-embedding-3-small   # Embedding model name
  top_k: 8                          # Default number of search results
  max_context_chars: 6000           # Hard prompt-injection character bound
  context_cache_entries: 64         # Thread-safe LRU entry bound
  context_cache_ttl_seconds: 30     # In-run expiry; clears each top-level run
  index_delay_seconds: 2            # Non-blocking initial index delay
  refresh_debounce_seconds: 0.25    # Collapse mutation bursts into one scan
```

**Data locations:**
- Embedding cache: `~/.rxycode/rag_cache/embeddings.json`
- Vector index: `~/.rxycode/rag_index/<project_hash>/` (meta.jsonl + vectors.npy + file_index.json)

## Dependencies
- **Internal**: `config/settings.py` (rag config, model credentials), `tools/registry` (code_search tool registration)
- **External**: `numpy` (vector operations), `httpx` (embedding API calls)
- **Stitched from**: mentat (embeddings pattern), aider (repomap design)
