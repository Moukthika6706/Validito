"""Notification channels. Each exposes `enabled` and `send(message)`; `send` raises
`ChannelError` on failure so the task can retry and audit it. Nothing here touches the
database or the pipeline."""

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

import httpx

from app.core.config import Settings


class ChannelError(RuntimeError):
    pass


@dataclass
class Message:
    subject: str
    text: str  # plain text body
    html: str  # email HTML body
    slack_blocks: list[dict] = field(default_factory=list)
    fallback: str = ""  # Slack notification preview


class EmailChannel:
    name = "email"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.notify_email_enabled and self.s.smtp_host and self.s.notify_email_to)

    @property
    def recipients(self) -> list[str]:
        return [r.strip() for r in self.s.notify_email_to.split(",") if r.strip()]

    def send(self, message: Message) -> dict:
        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = self.s.notify_email_from
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(message.text)
        msg.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=self.s.notify_timeout_seconds) as smtp:
                if self.s.smtp_starttls:
                    smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password or "")
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise ChannelError(f"SMTP: {type(exc).__name__}: {exc}") from exc
        return {"recipients": self.recipients}


class SlackChannel:
    name = "slack"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.notify_slack_enabled and self.s.slack_webhook_url)

    def send(self, message: Message) -> dict:
        payload = {"text": message.fallback or message.subject, "blocks": message.slack_blocks or None}
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            resp = httpx.post(self.s.slack_webhook_url, json=payload, timeout=self.s.notify_timeout_seconds)
        except httpx.HTTPError as exc:
            raise ChannelError(f"Slack: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 300:
            raise ChannelError(f"Slack webhook returned {resp.status_code}: {resp.text[:200]}")
        return {"status_code": resp.status_code}


def channels(settings: Settings) -> list:
    return [EmailChannel(settings), SlackChannel(settings)]


def enabled_channels(settings: Settings) -> list:
    return [c for c in channels(settings) if c.enabled]
