# cache/ - Caching System

## Overview

RxyCode has two application answer caches and a separate provider prompt cache:

1. `PreciseCache` reuses an answer only for byte-exact request components.
2. `SemanticCache` reuses an answer for a namespace-scoped near duplicate.
3. The LLM provider may reuse prompt-prefix tokens independently of either answer cache.

Tool-aware turns bypass both application answer caches because tools can observe or
change external state. Semantic caching is also bypassed when conversation memory is
present or when the precise layer already answered the request.

## Precise Cache

`cache/precise_cache.py` hashes the following UTF-8 values without trimming,
case-folding, punctuation removal, Unicode normalization, or filler-word removal:

- provider/model/credential namespace and the complete system prompt;
- the complete query;
- optional tool name and arguments;
- optional prompt version.

Each group is length-prefixed before SHA-256 hashing. This keeps component boundaries
unambiguous and means that any byte difference produces a different key. Fuzzy matching
belongs only in the semantic layer. The agent encodes user input and its optional memory
digest as a canonical JSON array before passing the query component, avoiding delimiter
collisions between context-free and context-aware requests.

## Semantic Cache

`cache/semantic_cache.py` uses normalized string similarity plus entity overlap:

- `SequenceMatcher` similarity must be at least `0.95`;
- meaningful entity-token overlap must be at least `0.60`;
- entries must share the same provider/model/credential namespace;
- expired, short, and known error responses are not reused.

The cache is bounded to 500 entries and retains the 300 most-hit entries when compacted.

## Persistence

Both caches persist JSON indexes under the configured data directory:

- `cache/precise_index.json`
- `cache/semantic_index.json`

`cache/json_store.py` provides the shared persistence contract. Operations on the same
path share a process-wide re-entrant lock. A mutating operation reloads the current disk
index while holding that lock, preventing lost updates between cache instances in
different threads. Writes go to a same-directory temporary file, are flushed and
`fsync`'d, then atomically replace the index with `os.replace`.

Malformed JSON, an invalid root type, or invalid entry shapes are preserved as
`<index>.corrupt-<timestamp>`. The active index is immediately recreated as an empty,
valid JSON document.

## Metrics

Provider prompt-cache metrics and application answer-cache metrics use different
denominators and are never combined.

For each `precise` and `semantic` application layer, `TokenStats` exposes:

- `requests`, `eligible`, and `bypassed` counts;
- `hits` and `misses` among eligible lookups;
- `hit_rate` and `miss_rate`, divided by `eligible`;
- `eligibility_rate` and `bypass_rate`, divided by `requests`.

`GET /status` returns these under `application_cache` and returns provider token-cache
data under `provider_cache`. The `/cache` command returns the same structured fields and
prints the per-layer session counts and rates alongside persisted entry statistics.

## Core API

- `precise_cache.get(system, query, namespace="") -> dict | None`
- `precise_cache.put(system, query, response, namespace="")`
- `precise_cache.get_stats() -> dict`
- `semantic_cache.get(query, namespace="") -> dict | None`
- `semantic_cache.put(query, response, namespace="")`
- `semantic_cache.get_stats() -> dict`
