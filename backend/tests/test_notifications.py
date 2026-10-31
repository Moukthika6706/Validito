"""Feature 4: notifications via mocked SMTP and Slack webhook. No network calls."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.notifications.channels import ChannelError, SlackChannel
from app.notifications.service import build_message, triggers_for_run
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import register_and_login

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def notify_on(monkeypatch):
    s = get_settings()
    for k, v in {
        "notify_email_enabled": True, "smtp_host": "smtp.test", "notify_email_to": "risk@bank.test, ops@bank.test", "notify_email_from": "validito@bank.test",
        "notify_slack_enabled": True, "slack_webhook_url": "https://hooks.slack.test/T/B/x",
        "frontend_base_url": "https://validito.bank.test", "notify_dedupe_per_document": True, "notify_severity_threshold": "error",
    }.items():
        monkeypatch.setattr(s, k, v)
    return s


@pytest.fixture
def smtp(monkeypatch):
    instance = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = instance
    cls = MagicMock(return_value=ctx)
    monkeypatch.setattr("app.notifications.channels.smtplib.SMTP", cls)
    return cls, instance


@pytest.fixture
def slack(monkeypatch):
    post = MagicMock(return_value=httpx.Response(200, text="ok"))
    monkeypatch.setattr("app.notifications.channels.httpx.post", post)
    return post


def _upload(client, headers, name):
    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": (name, (SAMPLES / name).read_bytes(), "application/pdf")}, data={"rule_pack_key": "isda"})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_review_routing_notifies_both_channels(client, notify_on, smtp, slack):
    headers = register_and_login(client, "n1@example.com")
    doc_id = _upload(client, headers, "isda_irs_faulty.pdf")

    # Email: one message, both recipients, subject carries the file + reason + severity summary.
    smtp_cls, smtp_inst = smtp
    smtp_cls.assert_called_once_with("smtp.test", 587, timeout=notify_on.notify_timeout_seconds)
    smtp_inst.starttls.assert_called_once()
    msg = smtp_inst.send_message.call_args.args[0]
    assert msg["To"] == "risk@bank.test, ops@bank.test" and msg["From"] == "validito@bank.test"
    assert "isda_irs_faulty.pdf" in msg["Subject"] and "review queue" in msg["Subject"] and "critical" in msg["Subject"]
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert f"https://validito.bank.test/review/{doc_id}" in body
    assert "[CRITICAL] Governing law missing" in body or "[CRITICAL] Termination date precedes effective date" in body

    # Slack: webhook called with blocks and the deep link.
    slack.assert_called_once()
    payload = slack.call_args.kwargs["json"]
    assert payload["text"].startswith("[Validito] isda_irs_faulty.pdf")
    assert any(b["type"] == "actions" and b["elements"][0]["url"].endswith(f"/review/{doc_id}") for b in payload["blocks"])

    # Audited per channel, and the document itself is unaffected.
    trail = client.get("/api/v1/audit", headers=headers, params={"document_id": doc_id, "event_type": "notification.*"}).json()
    channels = sorted(e["payload"]["channel"] for e in trail["items"])
    assert channels == ["email", "slack"] and all(e["event_type"] == "notification.sent" for e in trail["items"])
    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers).json()["status"] == "needs_review"


def test_clean_document_does_not_notify(client, notify_on, smtp, slack):
    headers = register_and_login(client, "n2@example.com")
    _upload(client, headers, "isda_irs_clean.pdf")
    smtp[1].send_message.assert_not_called()
    slack.assert_not_called()


def test_channels_off_by_default(client, smtp, slack):
    s = get_settings()
    assert s.notify_email_enabled is False and s.notify_slack_enabled is False
    headers = register_and_login(client, "n3@example.com")
    _upload(client, headers, "isda_irs_faulty.pdf")
    smtp[1].send_message.assert_not_called()
    slack.assert_not_called()


def test_failures_are_audited_and_never_fail_the_document(client, notify_on, smtp, monkeypatch):
    monkeypatch.setattr("app.notifications.channels.httpx.post", MagicMock(side_effect=httpx.ConnectError("boom")))
    smtp[1].send_message.side_effect = OSError("smtp down")
    headers = register_and_login(client, "n4@example.com")
    doc_id = _upload(client, headers, "isda_irs_faulty.pdf")

    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers).json()["status"] == "needs_review"
    trail = client.get("/api/v1/audit", headers=headers, params={"document_id": doc_id, "event_type": "notification.failed"}).json()
    errors = {e["payload"]["channel"]: e["payload"]["error"] for e in trail["items"]}
    assert "smtp down" in errors["email"] and "boom" in errors["slack"]


def test_dedupe_per_document_and_severity_threshold(client, notify_on, smtp, slack, monkeypatch):
    headers = register_and_login(client, "n5@example.com")
    doc_id = _upload(client, headers, "isda_irs_faulty.pdf")
    assert slack.call_count == 1

    # Re-validating the same document does not notify again.
    with patch("app.workers.tasks.enqueue_validation", side_effect=lambda i: validate_document.apply(args=(i,))):
        assert client.post(f"/api/v1/documents/{doc_id}/validate", headers=headers).status_code == 202
    assert slack.call_count == 1

    # Threshold: 'critical' excludes an error-only document from the high_severity trigger.
    from app.models import FlagStatus, RoutingDecision, Severity

    class F:  # minimal flag stand-in
        def __init__(self, sev):
            self.severity, self.status = sev, FlagStatus.open

    monkeypatch.setattr(notify_on, "notify_severity_threshold", "critical")
    assert triggers_for_run(RoutingDecision.auto_approved, [F(Severity.error)], notify_on) == []
    assert triggers_for_run(RoutingDecision.auto_approved, [F(Severity.critical)], notify_on) == ["high_severity"]
    assert triggers_for_run(RoutingDecision.needs_review, [], notify_on) == ["needs_review"]


def test_slack_non_2xx_is_a_channel_error(notify_on, monkeypatch):
    monkeypatch.setattr("app.notifications.channels.httpx.post", MagicMock(return_value=httpx.Response(500, text="nope")))
    from app.notifications.channels import Message

    with pytest.raises(ChannelError, match="500"):
        SlackChannel(notify_on).send(Message(subject="s", text="t", html="h"))
