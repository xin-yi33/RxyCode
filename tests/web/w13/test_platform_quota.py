"""W13. Platform-funded quota grants — slots, resolver, admission,
settlement, worker credential confinement.

The platform credential is a canary (``sk-canary-platform-*``) — it must
appear ONLY in the parent-side gateway headers, never in child env,
child config, run snapshots, events, or API responses.
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.models import (  # noqa: E402
    Membership,
    Organization,
    PlatformGrant,
    Run,
    RunEvent,
    User,
)
from rxycode_server.platform_quota import service as pq  # noqa: E402
from rxycode_worker import drain  # noqa: E402

CANARY = "sk-canary-platform-00aa11bb22"


def _seed_user(postgres_url: str, *, with_membership: bool = True) -> tuple[str, str]:
    """Insert tenant + user (+ membership); return (tenant_id, user_id)."""
    tenant_id = "t-" + uuid.uuid4().hex[:12]
    user_id = "u-" + uuid.uuid4().hex[:12]
    with Session(create_engine(postgres_url)) as db:
        db.add(Organization(id="org-" + tenant_id, tenant_id=tenant_id))
        db.add(User(id=user_id, kind="local"))
        if with_membership:
            db.add(
                Membership(
                    id="mem-" + uuid.uuid4().hex[:12],
                    tenant_id=tenant_id,
                    user_id=user_id,
                    role="owner",
                )
            )
        db.commit()
    return tenant_id, user_id


def _claim(postgres_url: str, user_id: str, tenant_id: str) -> PlatformGrant:
    # expire_on_commit=False: callers read slot_no/id/user_id AFTER the
    # session closes — a default session would expire attributes at commit
    # and detached access would raise DetachedInstanceError.
    with Session(create_engine(postgres_url), expire_on_commit=False) as db:
        grant = pq.claim_slot(db, user_id=user_id, tenant_id=tenant_id)
        db.commit()
        assert grant is not None
        return grant


def _record(tenant_id: str, user_id: str):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id)


def _platform_snapshot() -> dict:
    return {
        "model_ref": "platform",
        "model_id": "deepseek-v4.1-flash",
        "provider_id": "opencode-go",
        "provider_name": "OpenCode Go",
        "credential_source": "platform",
        "connection_id": "",
        "credential_version": 0,
    }


def _identity(tenant_id: str, user_id: str, snapshot: dict | None) -> dict:
    return {
        "tenant_id": tenant_id,
        "project_id": "p1",
        "actor_id": user_id,
        "traceparent": "",
        "model": snapshot,
    }


# ---------------------------------------------------------------------------
# Slots: migration seed, claim, exhaustion, races, backfill


def test_migration_seeds_ten_open_slots(postgres_url):
    with Session(create_engine(postgres_url)) as db:
        state = pq.slot_state(db)
        assert state["slots"] == 10
        assert state["open"] == 10
        assert state["claimed"] == []
        rows = db.scalars(select(PlatformGrant).order_by(PlatformGrant.slot_no)).all()
        assert [r.slot_no for r in rows] == list(range(1, 11))
        for row in rows:
            assert row.model_id == "deepseek-v4.1-flash"
            assert row.token_cap == 10_000_000
            assert row.tokens_used == 0
            assert row.status == "active"
            assert row.user_id is None


def test_claim_lowest_slot_and_idempotent(postgres_url):
    t1, u1 = _seed_user(postgres_url)
    t2, u2 = _seed_user(postgres_url)
    g1 = _claim(postgres_url, u1, t1)
    assert g1.slot_no == 1
    assert g1.user_id == u1
    assert g1.claimed_at is not None
    again = _claim(postgres_url, u1, t1)
    assert again.id == g1.id  # idempotent — never a second grant
    g2 = _claim(postgres_url, u2, t2)
    assert g2.slot_no == 2
    with Session(create_engine(postgres_url)) as db:
        state = pq.slot_state(db)
        assert state["open"] == 8
        assert len(state["claimed"]) == 2


def test_claim_exhaustion(postgres_url):
    grants = []
    for _ in range(10):
        t, u = _seed_user(postgres_url)
        grants.append(_claim(postgres_url, u, t))
    assert {g.slot_no for g in grants} == set(range(1, 11))
    t11, u11 = _seed_user(postgres_url)
    with Session(create_engine(postgres_url)) as db:
        assert pq.claim_slot(db, user_id=u11, tenant_id=t11) is None
        db.commit()
        assert pq.grant_for_user(db, u11) is None


def test_claim_concurrent_distinct_users(postgres_url):
    """Twenty threads racing for ten slots: each winner gets a distinct
    lowest-free slot, losers get None — never a doubled slot or grant."""
    users = [_seed_user(postgres_url) for _ in range(20)]
    results: dict[str, PlatformGrant | None] = {}
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(tenant_id: str, user_id: str) -> None:
        try:
            engine = create_engine(postgres_url)
            # grant attributes are read after the session closes.
            with Session(engine, expire_on_commit=False) as db:
                grant = pq.claim_slot(db, user_id=user_id, tenant_id=tenant_id)
                db.commit()
                with lock:
                    results[user_id] = grant
            engine.dispose()
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t, u)) for t, u in users]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors
    winners = [g for g in results.values() if g is not None]
    assert len(winners) == 10
    assert {g.slot_no for g in winners} == set(range(1, 11))
    assert len({g.user_id for g in winners}) == 10


def test_claim_concurrent_same_user(postgres_url):
    """Two racing claims for ONE user cannot produce two grants — the
    partial unique index + idempotent re-read make it single-winner."""
    tenant_id, user_id = _seed_user(postgres_url)
    barrier = threading.Barrier(2)
    got: list[PlatformGrant | None] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            engine = create_engine(postgres_url)
            with Session(engine) as db:
                got.append(pq.claim_slot(db, user_id=user_id, tenant_id=tenant_id))
                db.commit()
            engine.dispose()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors
    with Session(create_engine(postgres_url)) as db:
        rows = db.scalars(select(PlatformGrant).where(PlatformGrant.user_id == user_id)).all()
        assert len(rows) == 1


def test_backfill_oldest_first_and_idempotent(postgres_url):
    """Deterministic ``users.created_at`` order; rerun grants nobody twice."""
    seeded = [_seed_user(postgres_url) for _ in range(3)]
    engine = create_engine(postgres_url)
    # created_at is server_default now(); make order explicit.
    with Session(engine) as db:
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for idx, (_t, u) in enumerate(seeded):
            db.execute(
                update(User).where(User.id == u).values(created_at=base + timedelta(minutes=idx))
            )
        db.commit()
    with Session(engine) as db:
        out = pq.backfill_grants(db)
    assert [g["user_id"] for g in out["granted_now"]] == [u for _t, u in seeded]
    assert out["open"] == 7
    with Session(engine) as db:
        again = pq.backfill_grants(db)
    assert again["granted_now"] == []
    assert again["open"] == 7
    engine.dispose()


def test_backfill_caps_at_ten(postgres_url):
    for _ in range(12):
        _seed_user(postgres_url)
    with Session(create_engine(postgres_url)) as db:
        out = pq.backfill_grants(db)
        assert len(out["granted_now"]) == 10
        assert out["open"] == 0


# ---------------------------------------------------------------------------
# Resolver: the platform ref only resolves for a grant holder


def test_resolver_platform_holder(postgres_url):
    from rxycode_server.byok.resolver import resolve_run_model

    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    with Session(create_engine(postgres_url)) as db:
        snap = resolve_run_model(db, _record(tenant_id, user_id), "platform")
        assert snap["credential_source"] == "platform"
        assert snap["model_id"] == "deepseek-v4.1-flash"
        assert snap["provider_id"] == "opencode-go"
        # Identifiers only — no credential-shaped key anywhere.
        assert not any("key" in str(k).lower() for k in snap)


def test_resolver_platform_denied_and_stale_ref(postgres_url):
    from rxycode_server.byok.resolver import resolve_run_model

    tenant_id, user_id = _seed_user(postgres_url)
    with Session(create_engine(postgres_url)) as db:
        with pytest.raises(HTTPException) as err:
            resolve_run_model(db, _record(tenant_id, user_id), "platform")
        assert err.value.status_code == 404
        assert err.value.detail == "MODEL_NOT_FOUND"
        # No explicit ref, no grant, no BYOK default → honest refusal.
        with pytest.raises(HTTPException) as err2:
            resolve_run_model(db, _record(tenant_id, user_id), None)
        assert err2.value.status_code == 403
        assert err2.value.detail == "BYOK_REQUIRED"


def test_resolver_implicit_platform_default(postgres_url):
    """A grant holder submitting no model_ref runs the platform model —
    the free tier's first-send path."""
    from rxycode_server.byok.resolver import resolve_run_model

    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    with Session(create_engine(postgres_url)) as db:
        snap = resolve_run_model(db, _record(tenant_id, user_id), None)
        assert snap["credential_source"] == "platform"
        # An explicit stale default_model_ref survives only with a grant.
        user = db.get(User, user_id)
        user.default_model_ref = "platform"
        snap2 = resolve_run_model(db, _record(tenant_id, user_id), None)
        assert snap2["credential_source"] == "platform"


def test_resolver_stale_platform_default_no_grant(postgres_url):
    """``default_model_ref='platform'`` with the grant gone falls through
    to BYOK_REQUIRED — a dead ref never resurrects access."""
    from rxycode_server.byok.resolver import resolve_run_model

    tenant_id, user_id = _seed_user(postgres_url)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(update(User).where(User.id == user_id).values(default_model_ref="platform"))
        db.commit()
        with pytest.raises(HTTPException) as err:
            resolve_run_model(db, _record(tenant_id, user_id), None)
        assert err.value.status_code == 403
    engine.dispose()


def test_resolver_env_allowlist_grants_nothing(postgres_url, monkeypatch):
    """RXYCODE_PLATFORM_MODEL_USERS is retired — env can never mint access."""
    from rxycode_server.byok.resolver import resolve_run_model

    tenant_id, user_id = _seed_user(postgres_url)
    monkeypatch.setenv("RXYCODE_PLATFORM_MODEL_USERS", user_id)
    with Session(create_engine(postgres_url)) as db:
        with pytest.raises(HTTPException) as err:
            resolve_run_model(db, _record(tenant_id, user_id), "platform")
        assert err.value.status_code == 404


# ---------------------------------------------------------------------------
# Admission + settlement counters


def test_admission_exhausted_and_active(postgres_url):
    tenant_id, user_id = _seed_user(postgres_url)
    grant = _claim(postgres_url, user_id, tenant_id)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        # Cap reached → PLATFORM_QUOTA_EXHAUSTED.
        db.execute(
            update(PlatformGrant).where(PlatformGrant.id == grant.id).values(tokens_used=10_000_000)
        )
        db.commit()
        with pytest.raises(pq.PlatformQuotaRefused) as err:
            pq.check_admission(db, tenant_id=tenant_id, user_id=user_id)
        assert err.value.code == "PLATFORM_QUOTA_EXHAUSTED"
        db.execute(
            update(PlatformGrant).where(PlatformGrant.id == grant.id).values(tokens_used=500)
        )
        db.commit()
    engine.dispose()


def test_admission_second_active_run_refused(postgres_url):
    """One platform run in flight blocks the next — across sessions, not
    just within one session — so overspend stays bounded."""
    from rxycode_server.persistence.models import Project, SessionRow
    from rxycode_server.runs.service import create_run

    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.add(Project(id="p1", tenant_id=tenant_id, name="p1", repo_config={}))
        db.add(SessionRow(id="s1", tenant_id=tenant_id, project_id="p1", title="a"))
        db.add(SessionRow(id="s2", tenant_id=tenant_id, project_id="p1", title="b"))
        db.commit()
    snap = _platform_snapshot()
    accepted = create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id="s1",
        message="hi",
        target_id=f"cloud:{tenant_id}:p1",
        permission_profile="confirm",
        request_id="req-" + uuid.uuid4().hex[:16],
        user_id=user_id,
        model_snapshot=snap,
        request_model_ref="platform",
    )
    assert accepted.run_id
    with pytest.raises(pq.PlatformQuotaRefused) as err:
        create_run(
            postgres_url,
            tenant_id=tenant_id,
            session_id="s2",
            message="again",
            target_id=f"cloud:{tenant_id}:p1",
            permission_profile="confirm",
            request_id="req-" + uuid.uuid4().hex[:16],
            user_id=user_id,
            model_snapshot=snap,
            request_model_ref="platform",
        )
    assert err.value.code == "PLATFORM_RUN_ACTIVE"
    engine.dispose()


def test_admission_platform_run_no_grant(postgres_url):
    tenant_id, user_id = _seed_user(postgres_url)
    with Session(create_engine(postgres_url)) as db:
        with pytest.raises(pq.PlatformQuotaRefused) as err:
            pq.check_admission(db, tenant_id=tenant_id, user_id=user_id)
        assert err.value.code == "PLATFORM_NOT_ALLOWED"


def _platform_run(postgres_url: str, tenant_id: str, user_id: str) -> str:
    from rxycode_server.persistence.models import Project, SessionRow
    from rxycode_server.runs.service import create_run

    with Session(create_engine(postgres_url)) as db:
        if db.get(Project, "p1") is None:
            db.add(Project(id="p1", tenant_id=tenant_id, name="p1", repo_config={}))
        sid = "s-" + uuid.uuid4().hex[:8]
        db.add(SessionRow(id=sid, tenant_id=tenant_id, project_id="p1", title="t"))
        db.commit()
    return create_run(
        postgres_url,
        tenant_id=tenant_id,
        session_id=sid,
        message="hi",
        target_id=f"cloud:{tenant_id}:p1",
        permission_profile="confirm",
        request_id="req-" + uuid.uuid4().hex[:16],
        user_id=user_id,
        model_snapshot=_platform_snapshot(),
        request_model_ref="platform",
    ).run_id


def test_settle_grant_monotonic_clamped(postgres_url):
    """Re-settlement applies only the residue (lease-loss safe), the
    counter clamps at cap, and a platform.settled marker journals each
    fold."""
    tenant_id, user_id = _seed_user(postgres_url)
    grant = _claim(postgres_url, user_id, tenant_id)
    run_id = _platform_run(postgres_url, tenant_id, user_id)

    used = pq.settle_grant(
        postgres_url,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        tokens=1000,
    )
    assert used == 1000
    used = pq.settle_grant(
        postgres_url,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        tokens=1000,
    )
    assert used == 1000  # same cumulative total → residue zero
    used = pq.settle_grant(
        postgres_url,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        tokens=1500,
    )
    assert used == 1500  # only the +500 residue folded
    used = pq.settle_grant(
        postgres_url,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        tokens=99_999_999,
    )
    assert used == 10_000_000  # clamped at the durable cap

    engine = create_engine(postgres_url)
    with Session(engine) as db:
        grant2 = db.get(PlatformGrant, grant.id)
        assert grant2.tokens_used == 10_000_000
        markers = db.scalars(
            select(RunEvent).where(
                RunEvent.run_id == run_id,
                RunEvent.type == "platform.settled",
            )
        ).all()
        assert len(markers) == 4
        assert markers[-1].payload["applied_total"] == 99_999_999
        assert markers[-1].payload["tokens_used"] == 10_000_000
        # Admission now refuses — the counter is durable, no re-open.
        with pytest.raises(pq.PlatformQuotaRefused) as err:
            pq.check_admission(db, tenant_id=tenant_id, user_id=user_id)
        assert err.value.code == "PLATFORM_QUOTA_EXHAUSTED"
    engine.dispose()


def test_grant_overrun_watchdog(postgres_url):
    tenant_id, user_id = _seed_user(postgres_url)
    grant = _claim(postgres_url, user_id, tenant_id)
    run_id = _platform_run(postgres_url, tenant_id, user_id)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PlatformGrant).where(PlatformGrant.id == grant.id).values(tokens_used=9_999_000)
        )
        db.commit()
    assert pq.grant_overrun(postgres_url, user_id=user_id, run_id=run_id, metered=500) is False
    assert pq.grant_overrun(postgres_url, user_id=user_id, run_id=run_id, metered=1000) is True
    # A second settle folds the metered spend; the watchdog subtracts the
    # already-applied total so the same spend never double-counts.
    pq.settle_grant(
        postgres_url,
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=run_id,
        tokens=2000,
    )
    assert pq.grant_overrun(postgres_url, user_id=user_id, run_id=run_id, metered=2000) is True
    # Unknown user → no grant → False (nothing to kill).
    assert pq.grant_overrun(postgres_url, user_id="", run_id=run_id, metered=0) is False
    engine.dispose()


# ---------------------------------------------------------------------------
# Worker credential path — canary confinement


def test_worker_platform_gateway(postgres_url, monkeypatch):
    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    monkeypatch.setenv("RXYCODE_PLATFORM_API_KEY", CANARY)
    monkeypatch.delenv("RXYCODE_PLATFORM_BASE_URL", raising=False)
    snap = _platform_snapshot()
    gateway = drain._resolve_run_gateway(
        postgres_url, "run-p1", _identity(tenant_id, user_id, snap), snap
    )
    assert gateway.scheme == "https"
    assert gateway.host == "opencode.ai"
    assert gateway.port == 443
    assert gateway.base_path == "/zen/go/v1"
    assert gateway.vet is True
    assert gateway.headers["authorization"] == f"Bearer {CANARY}"
    # The canary lives ONLY in parent-side headers — the snapshot that
    # travels to the run row / events carries no key material.
    assert CANARY not in str(snap)


def test_worker_platform_no_key(postgres_url, monkeypatch):
    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    monkeypatch.delenv("RXYCODE_PLATFORM_API_KEY", raising=False)
    snap = _platform_snapshot()
    with pytest.raises(drain._CredentialRefused) as err:
        drain._resolve_run_gateway(
            postgres_url, "run-p2", _identity(tenant_id, user_id, snap), snap
        )
    assert err.value.code == "PLATFORM_UNAVAILABLE"


def test_child_env_and_config_carry_no_platform_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("RXYCODE_PLATFORM_API_KEY", CANARY)
    monkeypatch.setenv("RXYCODE_PLATFORM_BASE_URL", "https://opencode.ai/zen/go/v1")
    env = drain._child_env({"RXYCODE_TURN_ID": "t1"})
    assert CANARY not in str(env)
    assert "RXYCODE_PLATFORM_API_KEY" not in env
    assert "RXYCODE_PLATFORM_BASE_URL" not in env

    child = drain._build_child_config(
        {"safety": {"enabled": True}},
        workdir=tmp_path / "ws",
        egress_port=18882,
        env_model="",
        model_override={
            "model_id": "deepseek-v4.1-flash",
            "provider_id": "opencode-go",
            "provider_name": "OpenCode Go",
        },
    )
    dumped = yaml.safe_dump(child)
    assert child["active_model"] == "opencode-go/deepseek-v4.1-flash"
    entry = child["models"]["opencode-go/deepseek-v4.1-flash"]
    assert entry["api_key"] == "confined"
    assert entry["base_url"] == "http://127.0.0.1:18882"
    assert CANARY not in dumped
    assert "opencode.ai" not in dumped


def test_run_created_event_carries_no_secret(postgres_url, monkeypatch):
    """The persisted run.created payload echoes the non-secret snapshot
    only — even with the platform key in the worker env, nothing can
    smuggle it into the durable log."""
    monkeypatch.setenv("RXYCODE_PLATFORM_API_KEY", CANARY)
    tenant_id, user_id = _seed_user(postgres_url)
    _claim(postgres_url, user_id, tenant_id)
    run_id = _platform_run(postgres_url, tenant_id, user_id)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run.credential_source == "platform"
        assert run.model_id == "deepseek-v4.1-flash"
        event = db.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.type == "run.created")
        ).one()
        import json

        assert CANARY not in json.dumps(event.payload)
        model_echo = event.payload.get("model") or {}
        assert model_echo.get("credential_source") == "platform"
        assert model_echo.get("model_id") == "deepseek-v4.1-flash"
        assert "api_key" not in model_echo
    engine.dispose()


# ---------------------------------------------------------------------------
# HTTP surface: catalog, default, run submission


def _client(postgres_url: str, email: str, monkeypatch):
    monkeypatch.setenv("RXYCODE_WEB_REGISTRATION", "open")
    from tests.web.w9.test_runs_api import _client as _w9_client

    return _w9_client(postgres_url, email)


def test_registration_claims_slot(postgres_url, monkeypatch):
    client, me = _client(postgres_url, "w13-reg@example.com", monkeypatch)
    user_id = me["user"]["id"]
    assert user_id
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        grant = pq.grant_for_user(db, user_id)
        assert grant is not None
        assert grant.slot_no == 1
        assert grant.user_id == user_id
        assert grant.tenant_id == me["organization"]["tenant_id"]
        assert grant.model_id == "deepseek-v4.1-flash"
        assert grant.token_cap == 10_000_000
    engine.dispose()


def test_catalog_platform_only_for_holders(postgres_url, monkeypatch):
    holder, me1 = _client(postgres_url, "w13-holder@example.com", monkeypatch)
    other, me2 = _client(postgres_url, "w13-other@example.com", monkeypatch)

    listing = holder.get("/api/v1/models")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    platform_items = [m for m in body["models"] if m["model_ref"] == "platform"]
    assert len(platform_items) == 1
    item = platform_items[0]
    assert item["model_id"] == "deepseek-v4.1-flash"
    assert item["source"] == "platform"
    assert item["status"] == "available"
    assert item["quota"]["token_cap"] == 10_000_000
    assert item["quota"]["tokens_remaining"] == 10_000_000
    assert body["default_model_ref"] == "platform"
    # The holder's access endpoint agrees.
    access = holder.get("/api/v1/models/access").json()
    assert access["platform_allowed"] is True
    assert access["platform_quota"]["tokens_remaining"] == 10_000_000

    # The non-holder's view: registration claimed a slot while slots
    # last, so exhaust it to see what a grant-less catalog looks like.
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PlatformGrant)
            .where(PlatformGrant.user_id == me2["user"]["id"])
            .values(status="exhausted", tokens_used=10_000_000)
        )
        db.commit()
    listing2 = other.get("/api/v1/models")
    assert listing2.status_code == 200
    body2 = listing2.json()
    assert [m for m in body2["models"] if m["model_ref"] == "platform"] == []
    assert body2["default_model_ref"] != "platform"
    access2 = other.get("/api/v1/models/access").json()
    assert access2["platform_allowed"] is False
    assert access2["platform_quota"] is None
    engine.dispose()


def test_set_default_platform_ref(postgres_url, monkeypatch):
    from tests.web.w9.test_runs_api import _csrf, _headers

    client, me = _client(postgres_url, "w13-def@example.com", monkeypatch)
    headers = _headers(_csrf(client))
    ok = client.post("/api/v1/models/default", json={"model_ref": "platform"}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["default_model_ref"] == "platform"

    # Revoke the grant → the same POST 404s like any unknown ref.
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PlatformGrant)
            .where(PlatformGrant.user_id == me["user"]["id"])
            .values(status="exhausted")
        )
        db.commit()
    denied = client.post("/api/v1/models/default", json={"model_ref": "platform"}, headers=headers)
    assert denied.status_code == 404
    assert denied.json()["code"] == "MODEL_NOT_FOUND"
    engine.dispose()


def _post_task(client, model_ref: str | None = None):
    from tests.web.w9.test_runs_api import _csrf, _headers

    return client.post(
        "/api/v1/tasks",
        json={
            "message": "hi",
            "request_id": "req-" + uuid.uuid4().hex[:16],
            "permission_profile": "confirm",
            **({"model_ref": model_ref} if model_ref else {}),
        },
        headers=_headers(_csrf(client)),
    )


def test_runs_api_platform_ref_denied_for_non_holder(postgres_url, monkeypatch):
    client, me = _client(postgres_url, "w13-deny@example.com", monkeypatch)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PlatformGrant)
            .where(PlatformGrant.user_id == me["user"]["id"])
            .values(status="exhausted", tokens_used=10_000_000)
        )
        db.commit()
    resp = _post_task(client, "platform")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "MODEL_NOT_FOUND"
    engine.dispose()


def test_runs_api_platform_exhausted_429(postgres_url, monkeypatch):
    client, me = _client(postgres_url, "w13-cap@example.com", monkeypatch)
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        db.execute(
            update(PlatformGrant)
            .where(PlatformGrant.user_id == me["user"]["id"])
            .values(tokens_used=10_000_000)
        )
        db.commit()
    resp = _post_task(client, "platform")
    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert body["code"] == "QUOTA_EXCEEDED"
    assert body["reason"] == "platform_quota"
    engine.dispose()


def test_runs_api_platform_holder_202(postgres_url, monkeypatch):
    """End to end: register (claims a slot), submit model_ref=platform,
    run row + run.created carry the platform snapshot — no key material."""
    client, me = _client(postgres_url, "w13-ok@example.com", monkeypatch)
    resp = _post_task(client, "platform")
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    engine = create_engine(postgres_url)
    with Session(engine) as db:
        run = db.get(Run, run_id)
        assert run.credential_source == "platform"
        assert run.model_ref == "platform"
        assert run.model_id == "deepseek-v4.1-flash"
        assert run.provider_id == "opencode-go"
    engine.dispose()
