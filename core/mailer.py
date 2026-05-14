"""
Email delivery.

Currently a stub: writes the digest to data/digests/{date}.md and prints
the file location. To enable real email later, implement one of the
provider functions below and set the MAILER env var.

Supported (stubbed): resend, gmail
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


DIGEST_DIR = Path("data/digests")


def send_digest(subject: str, body_markdown: str, recipient: str | None = None) -> str:
    """Send (or stub-send) the digest. Returns a status string for CI logs."""
    recipient = recipient or os.environ.get("DIGEST_RECIPIENT", "(unset)")
    provider = os.environ.get("MAILER", "stub").lower()

    if provider == "stub":
        return _send_stub(subject, body_markdown, recipient)
    if provider == "resend":
        return _send_resend(subject, body_markdown, recipient)
    if provider == "gmail":
        return _send_gmail(subject, body_markdown, recipient)
    return (
        f"Unknown MAILER='{provider}' — falling back to stub.\n"
        + _send_stub(subject, body_markdown, recipient)
    )


def _send_stub(subject: str, body_markdown: str, recipient: str) -> str:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    path = DIGEST_DIR / f"{today}.md"
    content = f"Subject: {subject}\n\n{body_markdown}\n"
    path.write_text(content, encoding="utf-8")
    return f"[stub mailer] Digest written to {path} (would have emailed: {recipient})"


def _send_resend(subject: str, body_markdown: str, recipient: str) -> str:
    # When ready, install resend and replace with:
    #   import resend
    #   resend.api_key = os.environ["RESEND_API_KEY"]
    #   resend.Emails.send({
    #       "from": os.environ["DIGEST_FROM"],
    #       "to": recipient,
    #       "subject": subject,
    #       "text": body_markdown,
    #   })
    return ("[resend mailer] Not yet implemented. Install `resend`, set "
            "RESEND_API_KEY + DIGEST_FROM, and fill in this function.")


def _send_gmail(subject: str, body_markdown: str, recipient: str) -> str:
    # When ready, replace with:
    #   import smtplib
    #   from email.message import EmailMessage
    #   msg = EmailMessage()
    #   msg["Subject"] = subject
    #   msg["From"] = os.environ["GMAIL_ADDRESS"]
    #   msg["To"] = recipient
    #   msg.set_content(body_markdown)
    #   with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    #       s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    #       s.send_message(msg)
    return ("[gmail mailer] Not yet implemented. Set GMAIL_ADDRESS + "
            "GMAIL_APP_PASSWORD and fill in this function (use smtplib + ssl).")
