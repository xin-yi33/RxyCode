"""Transactional mail for password resets. Stdlib smtplib only.

``RXYCODE_SMTP_URL`` shapes:
  smtps://user:pass@host:465        implicit TLS
  smtp://user:pass@host:587         plain connect + STARTTLS when offered
  smtp://host:25                    no auth, no TLS (site-local relays)

The sender address is ``RXYCODE_SMTP_FROM`` or falls back to the URL user.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)


def send_mail(smtp_url: str, *, to: str, subject: str, body: str, sender: str = "") -> bool:
    """Best-effort send. Returns False on any failure — delivery never raises."""
    try:
        url = urlparse(smtp_url)
        tls = url.scheme == "smtps"
        host = url.hostname or ""
        if not host or url.scheme not in {"smtp", "smtps"}:
            log.warning("smtp url malformed: %r", url.scheme)
            return False
        port = url.port or (465 if tls else 587)
        user = unquote(url.username or "")
        password = unquote(url.password or "")
        from_addr = sender or user or "rxycode@localhost"

        message = EmailMessage()
        message["From"] = from_addr
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        if tls:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        return True
    except Exception:
        log.exception("password-reset mail to %s failed", to)
        return False
