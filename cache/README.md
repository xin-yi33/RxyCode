# cache/ - 缓存模块

## 模块职责

RxyCode 使用两层应用答案缓存，并单独统计 Provider 侧 prompt token 缓存：

1. `PreciseCache`：所有请求分量的 UTF-8 字节完全相同时才命中。
2. `SemanticCache`：仅对无会话上下文、同命名空间的近重复问题做模糊匹配。
3. Provider prompt cache：由 `core/agent_v2.py` 注入稳定的 `cache_control` 前缀；它不是应用答案缓存。

工具感知路径可能读取或修改外部状态，因此始终绕过两个应用答案缓存。

## 文件

| 文件 | 职责 |
|---|---|
| `precise_cache.py` | 精确 SHA-256 key、TTL、命中次数和一级缓存 API |
| `semantic_cache.py` | `SequenceMatcher >= 0.95`、实体重叠 `>= 0.60` 和二级缓存 API |
| `json_store.py` | 路径级线程锁、原子 JSON 替换和损坏索引恢复 |
| `text_normalizer.py` | 可供语义/意图处理使用的文本规范化工具；不参与 precise key |

## 精确缓存契约

`PreciseCache._make_key` 对以下分量做长度前缀编码后使用完整 SHA-256：

- namespace（provider endpoint、model、credential 摘要）和完整 system prompt；
- 完整 query；
- 可选 tool name 和 tool args；
- 可选 prompt version。

这里不做 trim、空格折叠、大小写转换、标点或填充词删除，也不做 Unicode 归一化。任一原始 UTF-8 字节变化都会生成不同 key。长度前缀保证分量内的 `:` 或空字符不会造成边界碰撞。

Agent 调用端始终把 user input 与可选 memory digest 编码为规范 JSON 数组后再传入 query 分量，避免无上下文的字面查询与“查询 + memory”组合产生分隔符碰撞。

## 语义缓存契约

语义缓存使用两阶段校验：

- 规范化字符串的 `SequenceMatcher` 相似度至少为 `0.95`；
- 关键实体 token 的重叠比例至少为 `0.60`。

它按 namespace 隔离，只在没有 conversation memory 时查询。错误响应和少于 10 个字符的响应不会写入。索引超过 500 条时按命中次数保留 300 条。

## JSON 持久化

两个索引都位于配置的数据目录下：

- `cache/precise_index.json`
- `cache/semantic_index.json`

同一路径的每个操作共享进程级 `RLock`。修改操作在锁内重新读取最新磁盘索引，防止多个实例的线程并发更新丢失。写入过程使用同目录临时文件，完成 `flush` 和 `fsync` 后通过 `os.replace` 原子替换目标文件。

遇到截断 JSON、错误根类型或错误条目结构时，原文件会保存为 `<index>.corrupt-<timestamp>`，活动索引会恢复为空的有效 JSON。

## 统计口径

`utils/streaming.py` 中的 `TokenStats` 分别维护 `precise` 和 `semantic`：

- `hits`、`misses`、`eligible`：真正执行缓存 lookup 的结果；
- `bypassed`：因工具路径、会话上下文或上层 precise 命中而未查询该层；
- `hit_rate`/`miss_rate`：分母为 `eligible`；
- `eligibility_rate`/`bypass_rate`：分母为该层 `requests`。

`GET /status` 和 `/cache` 在 `application_cache` 返回上述结构，在 `provider_cache` 返回 Provider token 缓存指标。两套命中率不能相加或混用。

## 公开 API

- `precise_cache.get(system, query, namespace="")`
- `precise_cache.put(system, query, response, namespace="")`
- `precise_cache.get_stats()` / `clean_expired()` / `clear()`
- `semantic_cache.get(query, namespace="")`
- `semantic_cache.put(query, response, namespace="")`
- `semantic_cache.get_stats()` / `clean_expired()` / `clear()`
