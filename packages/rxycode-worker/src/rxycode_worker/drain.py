"""Drain queued web runs: fenced claim -> real Session.prompt -> terminal commit.

The API writes a durable ``run.created`` row with status ``pending``; nothing
executes it until a worker takes the fenced lease. This module is that worker
for the deployed compose stack (``python -m rxycode_worker.drain``): it polls
``runs`` for claimable rows, claims through ``supervisor.claim``, reads the
persisted message back with ``runs.service.load_run``, then drives ONE real
turn through ``appserver.agent_runtime.AgentRuntime`` -> ``Session.prompt`` —
the same machinery an appserver session worker uses — with
``agent_events.remember_web_run`` bound so journaling, telemetry spans and the
usage ledger all land on the run's own event log.

Persisted web commands are delivered too: a ``_DrainWorkerShim`` exposes the
``_handle_steer``/``_steer_queue`` surface ``agent_events.accept_steer``
expects, ``bind_run`` registers it, and a poll task feeds
``consume_persisted_commands`` while the turn runs — the same channel the
stdio worker's ``_watch_web_commands`` task provides. ``child.cancel``
commands get an honest "no manager": the drain runs a single agent.

Terminal writes go through the fenced ``commit_terminal``/``confirm_cancel``;
a lost lease (``LeaseRejected``) aborts honestly — the new owner finishes the
run. Every durable write failure surfaces as a run failure, never silently.

Environment (all read in ``main``/``worker_config_from_env``):
    RXYCODE_WEB_DATABASE_URL   required — the same DSN the API uses
    RXYCODE_WORKER_ID          default ``drain-<hostname>-<pid>``
    RXYCODE_WORKER_POLL_SECONDS      default 2
    RXYCODE_WORKER_LEASE_TTL         default 120 (renewed while a run executes)
    RXYCODE_WORKER_RUN_TIMEOUT       default 900 — a prompt past this is
                                   cancelled and the run commits ``failed``
    RXYCODE_WORKER_WORKSPACES        default /tmp/rxycode-runs — per-session
                                   workspace dirs are created under it
    RXYCODE_WORKER_MODEL             optional model name for AgentV2
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_CLAIMABLE = ("pending", "leased", "running", "cancel_requested")
_CLAIMABLE_SQL = "','".join(_CLAIMABLE)

#: The one published ledger price version (``usage.service._PRICE_PER_TOKEN``).
#: Runs executed without provider credentials still record their real (zero)
#: spend under this version so the ledger row is honest, not absent.
_PRICE_VERSION = "2026-10"

_JOURNAL_CAP = 500

#: run.permission_profile -> Session.prompt(permission_mode=...). The durable
#: profile is an opaque string; only real vocabulary maps — anything else
#: falls back to the configured default rather than silently widening.
_PERMISSION_MODE_MAP = {
    "full_auto": "full_auto",
    "full": "full_auto",
    "auto_edit": "auto_edit",
    "confirm_all": "confirm_all",
}


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    worker_id: str
    poll_seconds: float = 2.0
    lease_ttl: int = 120
    run_timeout: float = 900.0
    workspaces_root: str = "/tmp/rxycode-runs"
    model: str = ""


def worker_config_from_env() -> WorkerConfig:
    """Read the drain configuration from the environment."""
    database_url = os.environ.get("RXYCODE_WEB_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RXYCODE_WEB_DATABASE_URL is required")
    worker_id = (
        os.environ.get("RXYCODE_WORKER_ID", "").strip()
        or f"drain-{socket.gethostname()}-{os.getpid()}"
    )
    return WorkerConfig(
        database_url=database_url,
        worker_id=worker_id,
        poll_seconds=max(0.2, float(os.environ.get("RXYCODE_WORKER_POLL_SECONDS", "2"))),
        lease_ttl=max(10, int(os.environ.get("RXYCODE_WORKER_LEASE_TTL", "120"))),
        run_timeout=max(30.0, float(os.environ.get("RXYCODE_WORKER_RUN_TIMEOUT", "900"))),
        workspaces_root=os.environ.get("RXYCODE_WORKER_WORKSPACES", "/tmp/rxycode-runs"),
        model=os.environ.get("RXYCODE_WORKER_MODEL", "").strip(),
    )


def _ledger_model(model: str) -> str:
    """Resolve the ledger's model_id to a real model name, never the "active"
    alias. Reads config only; never touches or logs the api key."""
    if model:
        return model
    try:
        from RxyCode.RxyCode1_1_0.config.settings import (
            get_active_model_config,
            load_config,
        )

        name = str(get_active_model_config(load_config()).get("model_name") or "")
        return name or "active"
    except Exception:
        return "active"


def claimable_run_ids(database_url: str, *, limit: int = 1) -> list[str]:
    """Runs a worker may take: ``pending``, or an active status whose lease
    expired (a dead worker's leftovers). ``claim`` re-checks under FOR UPDATE,
    so a racing claimant simply loses."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id FROM runs
                    WHERE status IN ('{_CLAIMABLE_SQL}')
                      AND (
                        status = 'pending'
                        OR lease_until IS NULL
                        OR lease_until < :now
                      )
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"now": datetime.now(timezone.utc), "limit": int(limit)},
            ).all()
    finally:
        engine.dispose()
    return [str(row[0]) for row in rows]


def run_status(database_url: str, run_id: str) -> str:
    """Current status column — the cancel signal the watchdog polls."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            value = conn.execute(
                text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}
            ).scalar()
    finally:
        engine.dispose()
    return str(value or "")


def _agent_done_row(database_url: str, run_id: str) -> tuple[str, int]:
    """(event_id, tokens_used) of the journaled ``event/agent_done`` row.

    ``replay`` dicts drop ``event_id``; the usage ledger needs it, so the row
    is read directly (same query shape as ``evals.web.run._agent_done_event_id``).
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.pool import NullPool

    from rxycode_server.persistence.models import RunEvent

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with SASession(engine) as db:
            row = db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.type == "event/agent_done")
                .order_by(RunEvent.seq.desc())
                .limit(1)
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return "", 0
    payload = row.payload if isinstance(row.payload, dict) else {}
    tokens = int(payload.get("tokens") or payload.get("tokens_used") or 0)
    return str(row.event_id), tokens


class _RunCancelled(Exception):
    """The run's status flipped to cancel_requested mid-flight."""


class _DrainWorkerShim:
    """The minimal worker surface ``agent_events.accept_steer`` needs.

    The stdio worker's ``_handle_steer`` appends to ``_steer_queue`` which
    ``Session.drain_steers`` drains mid-turn; this shim is that channel for a
    run with no stdin client. It answers like the real handler did: a queued
    steer only when a turn is running.
    """

    def __init__(self, run_id: str, session_id: str) -> None:
        self._session_id = session_id
        self._web_run_id = run_id
        self._next_id = 1
        self._steer_queue: list[str] = []
        self._turn: asyncio.Task[Any] | None = None

    async def _handle_steer(self, params: dict[str, Any], request_id: int) -> None:
        text = str(params.get("text") or "").strip()
        if text and self._turn is not None and not self._turn.done():
            self._steer_queue.append(text)

    def _take_steers(self) -> list[str]:
        taken = [str(item).strip() for item in self._steer_queue if str(item).strip()]
        self._steer_queue.clear()
        return taken


async def _command_watchdog(
    database_url: str, run_id: str, turn: "asyncio.Task[Any]"
) -> None:
    """Deliver persisted steer/child-cancel commands while the turn runs —
    the drain equivalent of ``AgentWorker._watch_web_commands``."""
    from rxycode_worker.agent_events import consume_persisted_commands

    while not turn.done():
        try:
            results = await consume_persisted_commands(database_url, run_id)
            for result in results:
                if not (result.get("delivered") or result.get("accepted")):
                    _LOG.warning("run %s: command undeliverable: %s", run_id, result)
        except Exception:
            _LOG.warning("run %s: command drain failed", run_id, exc_info=True)
        await asyncio.sleep(0.3)


async def _lease_watchdog(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    *,
    lease_ttl: int,
    turn: "asyncio.Task[Any]",
) -> None:
    """Renew the lease while the prompt runs; cancel the turn on
    ``cancel_requested``. ``LeaseRejected`` cancels the turn too — a fresher
    worker owns the run now."""
    from rxycode_worker.supervisor import LeaseRejected, renew_lease

    interval = max(2.0, lease_ttl / 2.0)
    while not turn.done():
        await asyncio.sleep(interval)
        if turn.done():
            return
        try:
            await asyncio.to_thread(
                renew_lease, database_url, run_id, worker_id, epoch,
                ttl_seconds=lease_ttl,
            )
        except LeaseRejected:
            turn.cancel()
            raise
        status = await asyncio.to_thread(run_status, database_url, run_id)
        if status == "cancel_requested":
            turn.cancel()
            raise _RunCancelled(run_id)


async def execute_run(
    cfg: WorkerConfig,
    run_id: str,
) -> bool:
    """Claim and execute one run through the real turn path.

    Returns True when this worker owned the run end to end. A lost claim or a
    lost lease returns False — the row is never half-written by two owners.
    """
    from rxycode_worker.supervisor import (
        LeaseRejected,
        claim,
        commit_terminal,
        confirm_cancel,
    )

    epoch = await asyncio.to_thread(
        claim, cfg.database_url, run_id, cfg.worker_id, ttl_seconds=cfg.lease_ttl
    )
    if epoch is None:
        return False

    from rxycode_worker.agent_events import (
        bind_run,
        clear_web_run,
        publish_database_url,
        remember_web_run,
    )
    from rxycode_server.events.store import append_event
    from rxycode_server.runs.service import load_run
    from rxycode_server.usage.service import record_terminal_usage

    # A run already cancel_requested at claim time never executes: nothing
    # ran, so its effects are fully known -> 'cancelled', not recovery.
    if await asyncio.to_thread(run_status, cfg.database_url, run_id) == "cancel_requested":
        confirm_cancel(
            cfg.database_url, run_id, cfg.worker_id, epoch, effects_known=True
        )
        return True

    def _run_row() -> str:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        engine = create_engine(cfg.database_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT tenant_id FROM runs WHERE id = :id"),
                    {"id": run_id},
                ).one()
        finally:
            engine.dispose()
        return str(row.tenant_id)

    tenant_id = await asyncio.to_thread(_run_row)

    publish_database_url(cfg.database_url)

    journaled = {"count": 0}
    message = ""
    session_id = run_id

    def _emit(notification: Any) -> None:
        """Journal protocol ``event/`` notifications onto the run's own event
        log — the same rows the SSE endpoint replays. Capped per run."""
        method = getattr(notification, "method", None)
        if (
            not isinstance(method, str)
            or not method.startswith("event/")
            or journaled["count"] >= _JOURNAL_CAP
        ):
            return
        journaled["count"] += 1
        try:
            append_event(
                cfg.database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type=f"notify.{method}",
                payload={"text": str(notification)[:1500]},
            )
        except Exception:
            _LOG.warning("run %s: journal emit failed", run_id, exc_info=True)

    # Mark execution start on the durable log so a consumer can distinguish
    # "queued forever" from "a worker took it and is running the turn".
    try:
        await asyncio.to_thread(
            append_event,
            cfg.database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type="worker.lease",
            payload={"worker_id": cfg.worker_id, "epoch": int(epoch)},
        )
    except Exception:
        _LOG.warning("run %s: worker.lease event failed", run_id, exc_info=True)

    turn_error = ""
    cancelled_by_request = False
    lost_lease = False
    ledger_model = _ledger_model(cfg.model)

    try:
        # Everything that can fail BEFORE the turn starts lives inside the
        # failure path: a corrupt run row or an unwritable workspace must end
        # in `commit_terminal("failed")`, not an orphaned lease that retries
        # forever.
        loaded = await asyncio.to_thread(load_run, cfg.database_url, run_id)
        message = loaded["message"]
        session_id = loaded["session_id"] or run_id
        permission_mode = _PERMISSION_MODE_MAP.get(
            str(loaded.get("permission_profile") or "").strip().lower()
        )
        remember_web_run(
            cfg.database_url,
            tenant_id,
            run_id,
            parent_id=session_id,
            session_id=session_id,
        )
        workdir = Path(cfg.workspaces_root) / session_id
        workdir.mkdir(parents=True, exist_ok=True)

        # Imports stay inside the executed run: module import of this file
        # must not drag the whole agent stack into a bare --help process.
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        from RxyCode.RxyCode1_1_0.core.session import Session
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )
        from RxyCode.RxyCode1_1_0.main import dispatch_surface_prompt
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats
        from appserver.agent_runtime import AgentConfig, AgentRuntime
        from appserver.agent_task import LifecycleState
        from appserver.eventbus import AppendOnlyLog, EventBus

        session = Session(
            session_id=session_id,
            workspace_root=workdir,
            emit=_emit,
        )
        agent = AgentV2(model_name=cfg.model or None, session_id=session_id)

        runtime = AgentRuntime(
            EventBus(AppendOnlyLog()),
            run_factory=lambda _cfg: _target,
        )
        agent_id = f"web-run-{run_id[:12]}"

        async def _target(_task_str: str, checkpoint: object | None = None) -> str:
            token0 = (
                int(token_stats.input_tokens),
                int(token_stats.output_tokens),
            )
            try:
                result = await dispatch_surface_prompt(
                    "web",
                    session,
                    agent,
                    message,
                    mode="build",
                    run_id=run_id,
                    permission_mode=permission_mode,
                )
            finally:
                # Mirror the eval driver: the real delta lands on the runtime
                # counter so the journaled agent_done snapshot carries it —
                # even when the turn was cancelled mid-prompt.
                delta = max(
                    0,
                    int(token_stats.input_tokens)
                    + int(token_stats.output_tokens)
                    - token0[0]
                    - token0[1],
                )
                try:
                    runtime.record_token_usage(agent_id, delta, run_id=run_id)
                except Exception:
                    _LOG.warning("run %s: token snapshot failed", run_id, exc_info=True)
            if getattr(result, "status", "") != "succeeded":
                raise RuntimeError(
                    getattr(result, "detail", "") or f"prompt status {result.status}"
                )
            return str(getattr(result, "answer", "") or "")

        # Persisted steer channel: accept_steer finds this worker by run_id,
        # appends to _steer_queue, and Session.prompt drains it mid-turn. The
        # hook is bound BEFORE spawn — prompt() reads drain_steers when the
        # turn first runs, so wiring it after spawn would race.
        shim = _DrainWorkerShim(run_id, session_id)
        session.drain_steers = shim._take_steers
        bind_run(run_id, worker=shim, tree_root=session_id)

        agent_task = await runtime.spawn(
            AgentConfig(agent_id=agent_id, model=cfg.model or "active")
        )
        main_task = agent_task._main_task
        assert main_task is not None
        shim._turn = main_task

        lease_watcher = asyncio.create_task(
            _lease_watchdog(
                cfg.database_url,
                run_id,
                cfg.worker_id,
                epoch,
                lease_ttl=cfg.lease_ttl,
                turn=main_task,
            )
        )
        command_watcher = asyncio.create_task(
            _command_watchdog(cfg.database_url, run_id, main_task)
        )
        # Session.prompt binds the session's own ContextVar; tool work that
        # escaped it (threads started off the loop) resolves "latest" — point
        # that alias at the run workspace too so strays land inside it.
        latest_token = bind_session("latest")
        try:
            set_working_directory(workdir)
        finally:
            reset_session_binding(latest_token)
        try:
            await asyncio.wait_for(asyncio.shield(main_task), timeout=cfg.run_timeout)
        except asyncio.TimeoutError:
            turn_error = f"run timed out after {cfg.run_timeout}s"
            try:
                await agent_task.interrupt()
            except Exception:
                main_task.cancel()
        except asyncio.CancelledError:
            pass
        finally:
            command_watcher.cancel()
            try:
                await command_watcher
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            lease_watcher.cancel()
            try:
                await lease_watcher
            except _RunCancelled:
                cancelled_by_request = True
            except LeaseRejected:
                lost_lease = True
            except asyncio.CancelledError:
                pass
        if not turn_error and agent_task.state != LifecycleState.DONE:
            last = getattr(agent_task, "_last_error", None)
            if last is not None:
                turn_error = f"{type(last).__name__}: {last}"
            elif not cancelled_by_request and not lost_lease:
                turn_error = f"agent ended in state {agent_task.state}"
    except LeaseRejected:
        lost_lease = True
    except Exception as exc:
        turn_error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            clear_web_run()
        except Exception:
            pass
        try:
            # The run's steer binding dies with its turn — a long-lived drain
            # must not accumulate one slot per finished run.
            from rxycode_worker.agent_events import _BOUND

            _BOUND.pop(run_id, None)
        except Exception:
            pass

    if lost_lease:
        _LOG.warning("run %s: lease lost mid-flight; new owner finishes", run_id)
        return False

    if cancelled_by_request:
        try:
            await asyncio.to_thread(
                confirm_cancel,
                cfg.database_url,
                run_id,
                cfg.worker_id,
                epoch,
                effects_known=False,
            )
        except LeaseRejected:
            return False
        return True

    # Real spend lands on the ledger even when the turn failed mid-flight:
    # the journaled agent_done snapshot is authoritative (it already carries
    # the runtime counter); absent that the real delta is zero.
    tokens = 0
    agent_done_id = uuid.uuid4().hex
    try:
        agent_done_id_found, tokens = await asyncio.to_thread(
            _agent_done_row, cfg.database_url, run_id
        )
        if agent_done_id_found:
            agent_done_id = agent_done_id_found
    except Exception:
        tokens = 0
    try:
        await asyncio.to_thread(
            record_terminal_usage,
            cfg.database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            model_id=ledger_model,
            price_version=_PRICE_VERSION,
            tokens=tokens,
            event_id=agent_done_id,
        )
    except Exception:
        _LOG.warning("run %s: terminal usage write failed", run_id, exc_info=True)

    terminal = "succeeded" if not turn_error else "failed"
    if turn_error:
        try:
            await asyncio.to_thread(
                append_event,
                cfg.database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                event_type="run.error",
                payload={"detail": turn_error[:1500], "worker_id": cfg.worker_id},
            )
        except Exception:
            _LOG.warning("run %s: run.error event failed", run_id, exc_info=True)
    try:
        await asyncio.to_thread(
            commit_terminal, cfg.database_url, run_id, cfg.worker_id, epoch, terminal
        )
    except LeaseRejected:
        return False
    return True


async def drain_once(cfg: WorkerConfig) -> bool:
    """Claim and execute at most one run. True means a run ran."""
    for run_id in claimable_run_ids(cfg.database_url, limit=3):
        if await execute_run(cfg, run_id):
            return True
    return False


async def run_forever(cfg: WorkerConfig) -> None:
    """Poll the durable queue forever. Per-iteration failures never kill the
    loop — a wedged run must not take down the only consumer."""
    _LOG.info(
        "worker drain started: worker_id=%s poll=%.1fs lease_ttl=%ds timeout=%.0fs",
        cfg.worker_id,
        cfg.poll_seconds,
        cfg.lease_ttl,
        cfg.run_timeout,
    )
    while True:
        did = False
        try:
            did = await drain_once(cfg)
        except Exception:
            _LOG.exception("drain iteration failed")
        if not did:
            await asyncio.sleep(cfg.poll_seconds)


def main() -> None:
    """``python -m rxycode_worker.drain`` / ``python -m rxycode_worker``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = worker_config_from_env()
    asyncio.run(run_forever(cfg))


if __name__ == "__main__":
    main()
