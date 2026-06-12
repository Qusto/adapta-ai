"""SMTP async client — Phase 1.

Sends invite email via aiosmtplib. Default config targets local MailHog
(no auth, no TLS), but the same client supports real SMTP providers
(Yandex / Gmail / etc.) when smtp_username / smtp_password / smtp_security
are configured in Settings.

Configured via Settings:
  - smtp_host / smtp_port / smtp_from      — connection target
  - smtp_username / smtp_password          — optional auth (None → no AUTH)
  - smtp_security: "none" | "tls" | "starttls"
      "none"     → plain SMTP (MailHog dev mode)
      "tls"      → implicit TLS from connect (smtps, typically port 465)
      "starttls" → upgrade plain connection via STARTTLS (typically port 587)

send_invite_email is best-effort: if SMTP is unavailable it logs a warning
and does NOT raise (per PRD §Risks — commit to DB first, email after).
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "invite.html"


def _render_invite_html(
    first_name: str,
    last_name: str,
    invite_url: str,
    company_name: str,
) -> str:
    """Render invite HTML email body."""
    if _TEMPLATE_PATH.exists():
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
        return (
            template.replace("{{first_name}}", first_name)
            .replace("{{last_name}}", last_name)
            .replace("{{invite_url}}", invite_url)
            .replace("{{company_name}}", company_name)
        )
    # Fallback inline template
    return f"""<!DOCTYPE html>
<html>
<body>
<p>Здравствуйте, {first_name} {last_name}!</p>
<p>Компания {company_name} приглашает вас присоединиться к AdaptaAI.</p>
<p><a href="{invite_url}">Принять приглашение</a></p>
</body>
</html>"""


async def send_invite_email(
    to_email: str,
    first_name: str,
    last_name: str,
    invite_url: str,
    company_name: str,
) -> None:
    """Send invite email to *to_email* via MailHog SMTP.

    Best-effort: logs warning on failure instead of raising.
    """
    settings = get_settings()

    html_body = _render_invite_html(first_name, last_name, invite_url, company_name)
    plain_body = (
        f"Здравствуйте, {first_name} {last_name}!\n"
        f"Компания {company_name} приглашает вас в AdaptaAI.\n"
        f"Ссылка: {invite_url}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Приглашение в AdaptaAI от {company_name}"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    use_tls = settings.smtp_security == "tls"
    start_tls = settings.smtp_security == "starttls"

    send_kwargs: dict = {
        "hostname": settings.smtp_host,
        "port": settings.smtp_port,
        "use_tls": use_tls,
        "start_tls": start_tls,
    }
    if settings.smtp_username:
        send_kwargs["username"] = settings.smtp_username
        send_kwargs["password"] = settings.smtp_password

    try:
        await aiosmtplib.send(msg, **send_kwargs)
        logger.info("Invite email sent to %s", to_email)
    except Exception as exc:
        logger.warning("Failed to send invite email to %s: %s", to_email, exc)
