"""Email delivery via Gmail SMTP (App Password) — the initial test channel.

Requires 2-step verification on the Google account and an App Password
(Google Account → Security → 2-Step Verification → App passwords).
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send(
    *,
    smtp_user: str,
    smtp_app_password: str,
    to_addr: str,
    subject: str,
    html: str,
    text: str,
    smtp_client: smtplib.SMTP | None = None,
) -> str:
    """Send and return the Message-ID the server accepted. Raises on failure."""
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="sport-planner.local")
    msg.set_content(text)
    msg.add_alternative(_wrap(html), subtype="html")
    if smtp_client is not None:
        smtp_client.send_message(msg)
    else:
        # python.org macOS builds ship without system root CAs; certifi (already a dependency via httpx) has them.
        try:
            import certifi

            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as s:
            s.login(smtp_user, smtp_app_password)
            s.send_message(msg)
    return msg["Message-ID"] or "(no id)"


def _wrap(telegram_html: str) -> str:
    """The report is Telegram-flavoured HTML (b/i/a only, newlines). Make it readable in a mail client."""
    body = telegram_html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return (
        "<html><body style=\"font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#222\">"
        f"<p>{body}</p></body></html>"
    )
