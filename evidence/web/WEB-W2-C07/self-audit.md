# WEB-W2-C07 self-audit

- RED, before the packages existed: collection failed with `No module named 'rxycode_server.artifacts'` and `No module named 'rxycode_server.usage'`. See red.txt.
- `store_artifact` uploads the bytes to MinIO with a private ACL, saves sha256, size, and content_type, and writes `artifact.created` in the same database transaction. The event payload has no file bytes and no object key.
- `open_download` signs `artifact_id`, tenant, expiry, and sha256. TTL longer than 900 seconds is rejected. `read_download` checks expiry, owner, and signature before `GetObject`. A mismatch raises ArtifactForbidden and does not return the body.
- The download route uses the session tenant. Tenant B with A's artifact id gets HTTP 403 `ARTIFACT_FORBIDDEN`.
- `record_terminal_usage` locks the run, inserts one `usage_records` row per `(run_id, model_id, price_version)`, and writes `usage.updated` only on that insert. A replay returns the first id, amount, and token count.
- Price version `2026-10` is 0.000002 USD per token. An unknown price version still records tokens and stores amount 0.
- Nested whitelist is a6163df. ToolOutcome and Trace source files were not edited. That ruling is in the nested phase doc.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
- Owner HTTP download now goes through create_app S3 settings. A local user in tenant-c07 receives the object bytes and text/plain. Missing storage config after a valid signature raises RuntimeError instead of ARTIFACT_FORBIDDEN.
