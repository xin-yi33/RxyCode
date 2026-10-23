"""OpenTelemetry-convention spans for the durable web run spine (WEB-W7-C04).

``opentelemetry`` is intentionally NOT a dependency: this module implements
the OTel wire conventions directly — W3C ``traceparent`` propagation
(``00-{32-hex trace_id}-{16-hex span_id}-{flags}``), span kinds, attributes
and durations — behind a constructor-injected exporter.  When the real OTel
SDK (or an OTLP/HTTP / Langfuse exporter) lands, the swap seam is the
exporter: any object with ``export(span_dict)`` drops into ``Tracer`` with
zero call-site changes.

Propagation is RUN-SCOPED: ``create_run`` persists the http span's
``traceparent`` inside the ``run.created`` event payload, and a claiming
worker reads it back per run_id through :func:`parent_for_run`.  Two
interleaved runs can therefore never cross-parent (a process-global
``os.environ`` value would leak the last-created run's context into the
next claim), and a worker started before any env var was set still finds
its parent.  ``inject_env``/``extract_env`` (``RXYCODE_TRACEPARENT``)
remain only as a test/compat channel and to re-publish the worker span's
own context to subprocesses — the production claim path never reads it.
In-process propagation uses a ContextVar
(``use_span`` / ``current_context``), the same mechanism
``rxycode_protocol.run_context`` uses for run scope.

Frozen card decisions honored here:

* Spans carry ``trace_id`` / ``run_id`` / ``tool_call_id`` through
  server -> worker -> runner.
* Full prompts and passwords are NEVER written to span storage by default.
  ``sanitize_attrs`` drops secret-shaped attribute keys entirely (recording
  only ``<key>_len`` and ``<key>_sha256``) and redacts + truncates every
  string value through ``log.log_helpers.redact_sensitive``.
* Span payloads carry ids and measurements, not content: run_id,
  tool_call_id, model, price_version, cache counters, durations.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# W3C trace context
# ---------------------------------------------------------------------------

_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_TRACE_ENV = "RXYCODE_TRACEPARENT"

#: Attribute keys that must never reach span storage. The values are
#: replaced by ``<key>_len`` and ``<key>_sha256`` so a reviewer can still
#: correlate without the content ever leaving the process.
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "completion",
        "cookie",
        "credential",
        "credentials",
        "instructions",
        "message",
        "messages",
        "password",
        "passwd",
        "prompt",
        "secret",
        "set-cookie",
        "system_prompt",
        "token",
        "x-api-key",
    }
)
_SECRET_KEY_MARKERS = ("key", "token", "secret", "password", "authorization", "cookie")
#: Usage counters are explainable cost data, not credentials — the
#: ``token`` marker must not swallow ``tokens_used`` into *_len/*_sha256.
_SAFE_TOKEN_COUNTERS = frozenset(
    {
        "tokens_used",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "cache_tokens",
        "input_tokens",
        "output_tokens",
        "budget_tokens",
        "budget_used",
        "token_usage",
        "token_count",
    }
)
_MAX_VALUE_CHARS = 200
#: Top-level identifier fields are short tokens, not blobs — a hard cap.
_MAX_ID_CHARS = 128
#: Span names read like "tool.<name>" / "http POST /route" — bounded too.
_MAX_NAME_CHARS = 200


def new_trace_id() -> str:
    """32 lowercase hex chars — the W3C trace-id."""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """16 lowercase hex chars — the W3C span-id."""
    return secrets.token_hex(8)


@dataclass(frozen=True)
class SpanContext:
    """Immutable W3C-style context carried through server -> worker -> runner."""

    trace_id: str
    span_id: str
    parent_span_id: str = ""
    run_id: str = ""
    tool_call_id: str = ""
    sampled: bool = True

    def traceparent(self) -> str:
        return format_traceparent(self)

    def child(self, **updates: Any) -> "SpanContext":
        """A new context in the same trace, parented on this span."""
        values = {
            "trace_id": self.trace_id,
            "span_id": new_span_id(),
            "parent_span_id": self.span_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "sampled": self.sampled,
        }
        values.update(updates)
        return SpanContext(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "sampled": self.sampled,
        }


def format_traceparent(ctx: SpanContext) -> str:
    """W3C ``traceparent``: ``{version}-{trace_id}-{span_id}-{flags}``."""
    flags = "01" if ctx.sampled else "00"
    return f"00-{ctx.trace_id}-{ctx.span_id}-{flags}"


def parse_traceparent(value: str | Mapping[str, Any] | None) -> SpanContext | None:
    """Parse a W3C traceparent header into the REMOTE parent context.

    The returned context's ``span_id`` is the caller's span — use it as the
    ``parent`` of :meth:`Tracer.start_span` so the new span records it in
    ``parent_span_id``. Malformed input returns ``None``, never a guess.
    """
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = str(
            value.get("traceparent") or value.get("Traceparent") or ""
        )
    if not isinstance(value, str):
        return None
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if match is None:
        return None
    version, trace_id, span_id, flags = match.groups()
    if version == "ff" or trace_id == "0" * 32 or span_id == "0" * 16:
        return None  # version ff and all-zero ids are invalid per W3C
    return SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        # W3C: ``sampled`` is bit 0x01 of the flags byte — ``02`` (and any
        # flag without the bit) is not sampled. The regex already pinned
        # flags to exactly two hex chars.
        sampled=bool(int(flags, 16) & 0x01),
    )


def inject_env(ctx: SpanContext) -> str:
    """Publish the traceparent into the process environment.

    COMPAT channel only: production parenting is run-scoped
    (``run.created`` payload -> :func:`parent_for_run`).  The env write is
    kept for tests and so worker subprocesses still inherit a sane parent
    exactly like ``RXYCODE_WEB_DATABASE_URL``
    (``agent_events.publish_database_url``).  Returns the header so the
    caller can also send it on a wire.
    """
    header = format_traceparent(ctx)
    os.environ[_TRACE_ENV] = header
    return header


def extract_env() -> SpanContext | None:
    """Read the injected traceparent back as the remote parent context.

    Legacy/test fallback only — a process-global value can name ANOTHER
    run's span.  Production callers (``supervisor.claim``,
    ``RunJournal``) resolve the parent through the run-scoped channels
    first and consult this only when the run predates persisted
    traceparents.
    """
    return parse_traceparent(os.environ.get(_TRACE_ENV))


@dataclass(frozen=True)
class ParentLookup:
    """Tri-state result of :func:`parent_for_run`.

    ``context`` is the run's persisted W3C parent — ``None`` when the run
    predates persisted traceparents or its payload is missing/malformed.

    ``run_event_found`` distinguishes WHY ``context`` is ``None``:

    * ``True`` — the run's own ``run.created`` event exists but carries no
      usable traceparent: a proven pre-traceparent (legacy) run, where the
      process-global env channel is the accepted last resort.
    * ``False`` — the ``run.created`` row is absent or the lookup itself
      failed (bad URL, DB down, …).  Production callers must NOT consult
      ``extract_env`` here: the env value can name ANOTHER run's span, so
      falling through would cross-parent two unrelated runs.
    """

    context: SpanContext | None
    run_event_found: bool


def parent_for_run(database_url: str, run_id: str) -> ParentLookup:
    """Read this run's persisted remote parent — the W3C ``traceparent``
    ``runs.service.create_run`` stored inside the ``run.created`` event
    payload.

    This is the production propagation channel: the parent context
    travels WITH the run row, so claiming run A can never pick up run B's
    span no matter what the process-global env currently holds.  Returns
    a :class:`ParentLookup` — never a guess; callers decide from
    ``run_event_found`` whether the legacy env fallback is acceptable.
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT payload FROM run_events "
                        "WHERE run_id = :rid AND type = 'run.created' "
                        "ORDER BY seq LIMIT 1"
                    ),
                    {"rid": run_id},
                ).first()
        finally:
            engine.dispose()
    except Exception:
        # Lookup itself failed: nothing is known about this run — the env
        # channel must not be consulted for it.
        return ParentLookup(None, False)
    if row is None:
        return ParentLookup(None, False)
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    if not isinstance(payload, Mapping):
        # The run's own event row exists — proven legacy run even though
        # its payload yields no context.
        return ParentLookup(None, True)
    return ParentLookup(
        parse_traceparent(payload.get("traceparent")), True
    )


_CURRENT: ContextVar[SpanContext | None] = ContextVar(
    "rxycode_otel_context", default=None
)


def bind_context(ctx: SpanContext | None):
    """Bind the current span context for implicit parenting."""
    return _CURRENT.set(ctx)


def reset_context(token) -> None:
    _CURRENT.reset(token)


def current_context() -> SpanContext | None:
    return _CURRENT.get()


# ---------------------------------------------------------------------------
# Attribute sanitization — prompts and passwords never leave the process
# ---------------------------------------------------------------------------


def _fallback_redact(value: object) -> str:
    """The same credential patterns as log.log_helpers.redact_sensitive.

    Kept in-line so redaction can NEVER fail because the core package is
    not importable from a stripped-down worker environment.
    """
    text = str(value)
    text = re.sub(r"\b(?:sk|ark)-[A-Za-z0-9_-]{16,}\b", "[REDACTED]", text)
    text = re.sub(r"\b(?:sk|ark)-[A-Za-z0-9_-]{4,}\*{8,}[A-Za-z0-9_-]*\b", "[REDACTED]", text)
    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)", r"\1[REDACTED]", text
    )
    text = re.sub(r"(?i)(\bbearer\s+)([^\s,;\"']+)", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        text,
    )
    return _extra_redact(text)


#: Credential shapes log.log_helpers.redact_sensitive does not cover:
#: GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_ + fine-grained github_pat_),
#: Slack tokens (xox[bapors]-) and AWS access key ids (AKIA…).  These are
#: applied ON TOP of the core patterns everywhere — including the inlined
#: fallback — so both redact paths mask the same set.
_EXTRA_SECRET_PATTERNS = (
    re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"\b(xox[bapors]-[A-Za-z0-9-]{8,})\b"),
    re.compile(r"\b(AKIA[A-Z0-9]{16})\b"),
)


def _extra_redact(text: str) -> str:
    for pattern in _EXTRA_SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _redact() -> Any:
    try:
        from RxyCode.RxyCode1_1_0.log.log_helpers import redact_sensitive

        return redact_sensitive
    except Exception:
        try:
            from log.log_helpers import redact_sensitive

            return redact_sensitive
        except Exception:
            return _fallback_redact


def _secret_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in _SAFE_TOKEN_COUNTERS:
        return False
    if lowered in _SECRET_KEYS:
        return True
    # dotted forms like http.request.header.authorization
    leaf = lowered.rsplit(".", 1)[-1]
    if leaf in _SECRET_KEYS:
        return True
    # conservative: any key that reads as a credential container
    return lowered.endswith("_key") or any(
        marker in lowered for marker in _SECRET_KEY_MARKERS
    )


def sanitize_value(value: Any, *, max_chars: int = _MAX_VALUE_CHARS) -> Any:
    """Redact credential forms inside a scalar value and bound its length."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    # The core redaction plus the telemetry-local token patterns — both the
    # redact_sensitive path and the inlined fallback mask the same set.
    text = _extra_redact(_redact()(value))
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def sanitize_ident(value: Any, *, max_chars: int = _MAX_ID_CHARS) -> str:
    """Sanitize a TOP-LEVEL span field (``name``, ``run_id``,
    ``tool_call_id``, …) before it leaves the process.

    These fields bypass ``sanitize_attrs`` because they are payload keys,
    not attrs — yet callers control them, so a secret-shaped value (a
    ``ghp_…`` token used as a call id, a prompt pasted into a span name)
    would otherwise land unredacted in the persisted payload.  Same
    treatment as attr values — core ``redact_sensitive`` plus the
    telemetry-local credential shapes — then a hard length cap: an
    identifier is a short token, never a blob.
    """
    text = _extra_redact(_redact()(str(value or "")))
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _sanitize_item(item: Any, *, max_chars: int) -> Any:
    """One element of a list/tuple attr — mappings recurse like any dict."""
    if isinstance(item, Mapping):
        return sanitize_attrs(item, max_chars=max_chars)
    if isinstance(item, (list, tuple)):
        return [_sanitize_item(x, max_chars=max_chars) for x in item]
    return sanitize_value(item, max_chars=max_chars)


def sanitize_attrs(
    attrs: Mapping[str, Any] | None, *, max_chars: int = _MAX_VALUE_CHARS
) -> dict[str, Any]:
    """Drop secret-shaped keys entirely; redact and bound every value.

    A dropped key leaves only ``<key>_len`` and ``<key>_sha256`` — enough to
    correlate identical content across spans without ever storing it.
    Mappings nested anywhere — inside lists as well as dicts — get the same
    treatment; nothing is ever stringified raw into the payload.
    """
    out: dict[str, Any] = {}
    for key, value in (attrs or {}).items():
        name = str(key)
        if _secret_key(name):
            # Idempotent: our own emitted metadata (<name>_len int /
            # <name>_sha256 hex) carries no content — keep it verbatim
            # instead of re-dropping it as a secret (``password_len`` must
            # not become ``password_len_len`` on the belt-and-suspenders
            # second pass in end_span).
            if name.endswith("_len") and isinstance(value, int):
                out[name] = value
                continue
            if (
                name.endswith("_sha256")
                and isinstance(value, str)
                and all(c in "0123456789abcdef" for c in value)
            ):
                out[name] = value
                continue
            raw = "" if value is None else str(value)
            out[f"{name}_len"] = len(raw)
            out[f"{name}_sha256"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
            continue
        if isinstance(value, Mapping):
            # Nested mappings get the same treatment: a credential hidden
            # under {"headers": {"authorization": ...}} is still a secret.
            out[name] = sanitize_attrs(value, max_chars=max_chars)
            continue
        if isinstance(value, (list, tuple)):
            # … and so does a mapping inside a list: a credential hidden in
            # {"events": [{"password": ...}]} is still a secret.
            out[name] = [
                _sanitize_item(item, max_chars=max_chars) for item in value
            ]
            continue
        out[name] = sanitize_value(value, max_chars=max_chars)
    return out


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

#: Our span kinds map onto OTel SpanKind for the dashboard/exporter seam.
OTEL_KIND = {
    "server": "SERVER",
    "client": "CLIENT",
    "worker": "INTERNAL",
    "runner": "CLIENT",
    "tool": "CLIENT",
    "internal": "INTERNAL",
    "producer": "PRODUCER",
    "consumer": "CONSUMER",
}

_SPAN_SCHEMA = "otel.span/v1"


@dataclass
class Span:
    """One in-flight span; ``to_dict`` is the stored payload shape."""

    name: str
    kind: str
    context: SpanContext
    start_epoch: float
    start_mono: float
    end_epoch: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"
    detail: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.context.run_id

    @run_id.setter
    def run_id(self, value: str) -> None:
        self.context = SpanContext(
            trace_id=self.context.trace_id,
            span_id=self.context.span_id,
            parent_span_id=self.context.parent_span_id,
            run_id=value,
            tool_call_id=self.context.tool_call_id,
            sampled=self.context.sampled,
        )

    def set_attrs(self, attrs: Mapping[str, Any]) -> None:
        self.attrs.update(sanitize_attrs(attrs))

    def to_dict(self) -> dict[str, Any]:
        # Top-level fields are caller-controlled strings too — they pass
        # through sanitize_ident so a secret used as a call id or span
        # name can never land raw in the persisted payload (the attr map
        # is sanitized separately by start_span/finalize_span).
        return {
            "schema": _SPAN_SCHEMA,
            "trace_id": sanitize_ident(self.context.trace_id),
            "span_id": sanitize_ident(self.context.span_id),
            "parent_span_id": sanitize_ident(self.context.parent_span_id),
            "run_id": sanitize_ident(self.context.run_id),
            "tool_call_id": sanitize_ident(self.context.tool_call_id),
            "name": sanitize_ident(self.name, max_chars=_MAX_NAME_CHARS),
            "kind": sanitize_ident(self.kind, max_chars=32),
            "otel_kind": OTEL_KIND.get(self.kind, "INTERNAL"),
            "status": sanitize_ident(self.status, max_chars=32),
            "detail": sanitize_value(self.detail),
            "start_epoch": round(self.start_epoch, 6),
            "end_epoch": round(self.end_epoch, 6),
            "duration_ms": round(self.duration_ms, 3),
            "attrs": dict(self.attrs),
        }


class SpanExporter(Protocol):
    """The OTLP/Langfuse seam: any object with ``export(span_dict)``."""

    dropped: int

    def export(self, span: dict[str, Any]) -> bool: ...


class InMemorySpanExporter:
    """Test/dev exporter — spans land in ``.spans``."""

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []
        self.dropped = 0

    def export(self, span: dict[str, Any]) -> bool:
        self.spans.append(dict(span))
        return True


class JsonlSpanExporter:
    """Per-run JSONL store — the file-backed alternative to run_events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.dropped = 0

    def export(self, span: dict[str, Any]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(span, ensure_ascii=False) + "\n")
            return True
        except OSError:
            self.dropped += 1
            return False


class RunEventsSpanExporter:
    """Durable store: spans become ``telemetry.span`` run_events rows.

    Rows are tenant-scoped (``append_event`` writes only for the owning
    tenant), durable, replayable through ``events.store.replay`` and fanned
    out to SSE subscribers like every other run event — so "users see
    summaries of THEIR OWN traces" inherits the existing tenant filter.

    Telemetry must never break a run: export failures increment
    ``dropped`` and return ``False`` instead of raising.
    """

    event_type = "telemetry.span"

    def __init__(
        self, database_url: str, tenant_id: str, emitter: Any | None = None
    ) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.dropped = 0
        # Confined turns have no database credentials: their spans travel
        # the parent-owned control channel instead (``emitter`` is
        # ``TurnChannel.emit`` -> append_event on the drain side).
        self._emitter = emitter

    def export(self, span: dict[str, Any]) -> bool:
        run_id = str(span.get("run_id") or "")
        if not run_id:
            self.dropped += 1
            return False
        try:
            if self._emitter is not None:
                self._emitter(self.event_type, dict(span))
                return True
            from rxycode_server.events.store import append_event

            append_event(
                self.database_url,
                tenant_id=self.tenant_id,
                run_id=run_id,
                event_type=self.event_type,
                payload=dict(span),
            )
            return True
        except Exception:
            self.dropped += 1
            return False

    def export_conn(self, conn, span: dict[str, Any]) -> bool:
        """The same event+outbox write on the caller's OPEN transaction.

        The follow-SSE endpoint stops when the run's status turns terminal —
        a span appended after the terminal commit could never stream. The
        durable worker span therefore lands atomically inside the terminal
        tx (same seq assignment as ``events.store.append_event``: the run's
        ``event_seq`` watermark, retained ``run_events`` max, +1).

        Callers run this inside ``conn.begin_nested()`` (SAVEPOINT) on
        PostgreSQL, so statement errors must PROPAGATE: only a raised
        error lets the nested transaction issue ROLLBACK TO SAVEPOINT.
        Swallowing the exception here would exit the block cleanly, emit
        RELEASE SAVEPOINT on the aborted tx — itself a failure — and take
        the caller's terminal UPDATE down with it.  The drop is still
        counted before re-raising.
        """
        run_id = str(span.get("run_id") or "")
        if not run_id:
            self.dropped += 1
            return False
        try:
            from sqlalchemy import text as _text

            retained = conn.execute(
                _text(
                    "SELECT COALESCE(MAX(seq), 0) FROM run_events "
                    "WHERE run_id = :rid"
                ),
                {"rid": run_id},
            ).scalar_one()
            current = conn.execute(
                _text("SELECT event_seq FROM runs WHERE id = :rid"),
                {"rid": run_id},
            ).scalar_one()
            seq = max(int(current or 0), int(retained or 0)) + 1
            event_id = uuid.uuid4().hex
            conn.execute(
                _text(
                    """
                    INSERT INTO run_events
                        (event_id, run_id, tenant_id, seq, type, payload, at)
                    VALUES
                        (:eid, :rid, :tid, :seq, :etype,
                         CAST(:payload AS jsonb), clock_timestamp())
                    """
                ),
                {
                    "eid": event_id,
                    "rid": run_id,
                    "tid": self.tenant_id,
                    "seq": seq,
                    "etype": self.event_type,
                    "payload": json.dumps(span, ensure_ascii=False),
                },
            )
            conn.execute(
                _text(
                    """
                    INSERT INTO outbox (id, event_id, dispatch_status, attempts)
                    VALUES (gen_random_uuid()::text, :eid, 'pending', 0)
                    """
                ),
                {"eid": event_id},
            )
            conn.execute(
                _text("UPDATE runs SET event_seq = :seq WHERE id = :rid"),
                {"seq": seq, "rid": run_id},
            )
            return True
        except Exception:
            self.dropped += 1
            # Re-raise: the surrounding begin_nested() must see the
            # failure to roll back to its savepoint. Returning False here
            # would look like a clean exit and poison the terminal tx.
            raise


class _MultiExporter:
    def __init__(self, exporters: list[Any]) -> None:
        self._exporters = exporters

    @property
    def dropped(self) -> int:
        return sum(int(getattr(e, "dropped", 0) or 0) for e in self._exporters)

    def export(self, span: dict[str, Any]) -> bool:
        ok = True
        for exporter in self._exporters:
            ok = bool(exporter.export(dict(span))) and ok
        return ok


def export_span_payload(
    exporter: Any, payload: Mapping[str, Any], *, conn: Any = None
) -> bool:
    """Ship one finalized span payload; never raises.

    With ``conn`` — the caller's OPEN terminal transaction — the write goes
    through ``export_conn`` inside ``conn.begin_nested()`` (SAVEPOINT): on
    PostgreSQL a failed statement aborts the surrounding tx, so it must
    propagate out of the block for ``__exit__`` to issue ROLLBACK TO
    SAVEPOINT — the telemetry write then rolls back ALONE instead of
    taking the terminal commit down with it.  (An exporter that swallowed
    the error inside the block would emit RELEASE SAVEPOINT on the aborted
    tx — itself a failure.)  Without a conn the plain ``export`` path is
    used.  Failures are logged and False returned — telemetry must not
    break a terminal commit.
    """
    try:
        if conn is not None and hasattr(exporter, "export_conn"):
            with conn.begin_nested():
                return bool(exporter.export_conn(conn, dict(payload)))
        return bool(exporter.export(dict(payload)))
    except Exception:
        _LOG.warning(
            "span export failed (run_id=%s name=%s)",
            payload.get("run_id"),
            payload.get("name"),
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class Tracer:
    """Creates spans with W3C context and ships them through an exporter.

    ``exporter`` may be a single ``export()``-shaped object or a list of
    them — inject the OTLP/HTTP exporter here when the real SDK lands.
    """

    def __init__(
        self, exporter: Any | list[Any] | None = None, *, service: str = "rxycode"
    ) -> None:
        if exporter is None:
            exporter = InMemorySpanExporter()
        if isinstance(exporter, list):
            exporter = _MultiExporter(exporter)
        self.exporter = exporter
        self.service = service

    @property
    def dropped(self) -> int:
        return int(getattr(self.exporter, "dropped", 0) or 0)

    def _resolve_parent(
        self, parent: SpanContext | str | Mapping[str, Any] | None
    ) -> SpanContext | None:
        if isinstance(parent, SpanContext):
            return parent
        if isinstance(parent, (str, Mapping)):
            # An explicit header that fails to parse is never guessed — but
            # a malformed parent inside an ambient context falls back to the
            # ambient span, it does not fork a fresh trace.
            parsed = parse_traceparent(parent)
            return parsed if parsed is not None else _CURRENT.get()
        return _CURRENT.get()

    def start_span(
        self,
        name: str,
        *,
        kind: str = "internal",
        parent: SpanContext | str | Mapping[str, Any] | None = None,
        attrs: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        tool_call_id: str = "",
    ) -> Span:
        """Start a span. ``parent`` may be a SpanContext, a traceparent
        header string, or a mapping carrying ``traceparent``; ``None`` uses
        the ContextVar-bound context, else starts a new trace."""
        remote = self._resolve_parent(parent)
        if remote is None:
            ctx = SpanContext(
                trace_id=new_trace_id(),
                span_id=new_span_id(),
                parent_span_id="",
                run_id=run_id or "",
                tool_call_id=tool_call_id,
            )
        else:
            ctx = remote.child(
                run_id=run_id if run_id is not None else remote.run_id,
                tool_call_id=tool_call_id or remote.tool_call_id,
            )
        base_attrs = {"service.name": self.service}
        base_attrs.update(sanitize_attrs(attrs))
        return Span(
            name=name,
            kind=kind,
            context=ctx,
            start_epoch=time.time(),
            start_mono=time.perf_counter(),
            attrs=base_attrs,
        )

    def finalize_span(
        self,
        span: Span,
        *,
        status: str = "ok",
        detail: str = "",
        attrs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close the span, stamp the real duration, sanitize — but do NOT
        export. Returns the stored payload so a caller can persist it inside
        its own transaction (the durable worker span lands atomically with
        the run's terminal commit, never post-terminal)."""
        span.end_epoch = time.time()
        span.duration_ms = max(
            0.0, (time.perf_counter() - span.start_mono) * 1000.0
        )
        span.status = status
        if detail:
            span.detail = str(sanitize_value(detail))
        if attrs:
            span.attrs.update(sanitize_attrs(attrs))
        # Belt and suspenders: even attrs poked in raw are sanitized before
        # the payload leaves the process (idempotent on clean values).
        span.attrs = sanitize_attrs(span.attrs)
        return span.to_dict()

    def end_span(
        self,
        span: Span,
        *,
        status: str = "ok",
        detail: str = "",
        attrs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close the span, stamp the real duration, sanitize, and export."""
        payload = self.finalize_span(
            span, status=status, detail=detail, attrs=attrs
        )
        self.exporter.export(payload)
        return payload

    @contextlib.contextmanager
    def span(
        self, name: str, *, status_ok: str = "ok", **kwargs: Any
    ) -> Iterator[Span]:
        """Context manager: yield the span, end it on exit (error on raise)."""
        opened = self.start_span(name, **kwargs)
        try:
            yield opened
        except BaseException as exc:
            self.end_span(
                opened,
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            raise
        self.end_span(opened, status=status_ok)

    @contextlib.contextmanager
    def use_span(self, span: Span | SpanContext) -> Iterator[SpanContext]:
        """Bind a context so nested ``start_span(parent=None)`` picks it up."""
        ctx = span.context if isinstance(span, Span) else span
        token = bind_context(ctx)
        try:
            yield ctx
        finally:
            reset_context(token)
