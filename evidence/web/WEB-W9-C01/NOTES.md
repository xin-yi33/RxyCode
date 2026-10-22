# WEB-W9-C01 handoff notes — auth, admission, rate ceilings, device lock

## What shipped

| File | Role |
|------|------|
| `packages/rxycode-server/src/rxycode_server/api/auth.py` | local password + GitHub OAuth login, email verification-code registration, password reset, durable `auth_sessions` rows (no per-process dicts) |
| `packages/rxycode-server/src/rxycode_server/altcha.py` | internal ALTCHA-compatible proof-of-work challenge for register/login/forgot-password bot prevention |
| `packages/rxycode-server/src/rxycode_server/mailer.py` | SMTP verification/reset mail delivery |
| `packages/rxycode-server/src/rxycode_server/persistence/models.py` | `AuthSession`, `DeviceLock`, `PasswordReset`, email-code tables |
| `apps/web/src/` login/register/console shell | `/login`, `/register`, `/oauth/callback` public routes; `/app*` behind `AuthGate`; post-login console with sessions/diff/PTY/workbench |

## Verified behavior

- Email verification code required for registration; login supports password or code mode; forgot-password issues a reset link/code.
- Per-IP and per-mailbox fixed-window rate ceilings on code-send and register endpoints (429 + Retry-After).
- Single-device login lock: a second session takes over via 409 modal; lock idles out after 10 minutes.
- Covered by `tests/web/w9/test_rate_and_device.py` (code-send email cap, IP window, register hourly cap, device-lock takeover + expiry), `tests/web/w9/test_auth.py`, `tests/web/w9/test_email_codes.py`, `tests/web/w9/test_password_reset.py`.
- Recorded in `docs/release-notes/CHANGELOG_v1.4.4.md` W9/W10-D5 sections.
