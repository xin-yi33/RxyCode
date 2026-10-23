"""Operator CLI for the web auth store. Part of WEB-W9-B1.

    python -m rxycode_server.admin invite create --uses 5 --days 7
    python -m rxycode_server.admin invite list
    python -m rxycode_server.admin user reset-password --email a@b.c < pw.txt
    python -m rxycode_server.admin user disable --email a@b.c

The database URL comes from ``RXYCODE_WEB_DATABASE_URL``. Plaintext invite
codes are printed exactly once — only their SHA-256 digest is stored — and
``reset-password`` reads the new password from stdin so it never lands in
argv or shell history. Disabling a user and resetting a password both revoke
every live session for that user.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import _normalize_email, hash_password, invite_digest
from rxycode_server.persistence.models import AuthSession, Invite, User


def _db_url() -> str:
    url = os.environ.get("RXYCODE_WEB_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("RXYCODE_WEB_DATABASE_URL is not set")
    return url


def _revoke_sessions(db: Session, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return int(result.rowcount or 0)


def _invite_create(args: argparse.Namespace) -> int:
    code = secrets.token_urlsafe(24)
    expires_at = None
    if args.days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.days)
    engine = create_engine(_db_url(), poolclass=NullPool)
    try:
        with Session(engine) as db:
            db.add(
                Invite(
                    code_hash=invite_digest(code),
                    max_uses=args.uses,
                    expires_at=expires_at,
                    note=args.note or "",
                )
            )
            db.commit()
    finally:
        engine.dispose()
    print(code)  # shown once; only its sha256 digest was stored
    return 0


def _invite_list(args: argparse.Namespace) -> int:
    engine = create_engine(_db_url(), poolclass=NullPool)
    try:
        with Session(engine) as db:
            rows = db.scalars(select(Invite).order_by(Invite.created_at.desc())).all()
            for row in rows:
                stamp = (
                    row.expires_at.isoformat() if row.expires_at is not None else "-"
                )
                print(f"{row.code_hash[:12]}  {row.used}/{row.max_uses}  {stamp}  {row.note}")
    finally:
        engine.dispose()
    return 0


def _user_reset_password(args: argparse.Namespace) -> int:
    email = _normalize_email(args.email)
    password = sys.stdin.readline().rstrip("\n")
    if not 8 <= len(password) <= 128:
        raise SystemExit("password must be 8-128 characters")
    engine = create_engine(_db_url(), poolclass=NullPool)
    try:
        with Session(engine) as db:
            user = db.scalars(select(User).where(User.email == email).limit(1)).first()
            if user is None:
                raise SystemExit(f"no user with email {email}")
            user.password_hash = hash_password(password)
            revoked = _revoke_sessions(db, user.id)
            db.commit()
    finally:
        engine.dispose()
    print(f"password reset for {email}; {revoked} session(s) revoked")
    return 0


def _user_disable(args: argparse.Namespace) -> int:
    email = _normalize_email(args.email)
    engine = create_engine(_db_url(), poolclass=NullPool)
    try:
        with Session(engine) as db:
            user = db.scalars(select(User).where(User.email == email).limit(1)).first()
            if user is None:
                raise SystemExit(f"no user with email {email}")
            if user.disabled_at is None:
                user.disabled_at = datetime.now(timezone.utc)
            revoked = _revoke_sessions(db, user.id)
            db.commit()
    finally:
        engine.dispose()
    print(f"{email} disabled; {revoked} session(s) revoked")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rxycode_server.admin")
    commands = parser.add_subparsers(dest="command", required=True)

    invite = commands.add_parser("invite")
    invite_sub = invite.add_subparsers(dest="action", required=True)
    invite_create = invite_sub.add_parser("create")
    invite_create.add_argument("--uses", type=int, default=1)
    invite_create.add_argument("--days", type=int, default=0)
    invite_create.add_argument("--note", default="")
    invite_create.set_defaults(func=_invite_create)
    invite_list = invite_sub.add_parser("list")
    invite_list.set_defaults(func=_invite_list)

    user = commands.add_parser("user")
    user_sub = user.add_subparsers(dest="action", required=True)
    reset = user_sub.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    reset.set_defaults(func=_user_reset_password)
    disable = user_sub.add_parser("disable")
    disable.add_argument("--email", required=True)
    disable.set_defaults(func=_user_disable)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
