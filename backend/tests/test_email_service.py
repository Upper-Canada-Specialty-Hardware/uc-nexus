"""SMTP config resolution for outbound email (#500).

The important behaviour is that an unconfigured deployment is DISABLED rather than broken: a PR
environment has no SMTP and must never accidentally mail a real vendor, and the absence of a mailbox
is not an error state anyone should see as a failure.
"""

import pytest

from app.services import email as email_service


@pytest.fixture(autouse=True)
def _clear_smtp_env(monkeypatch):
    for key in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_ADDRESS",
        "SMTP_USE_TLS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_no_host_means_disabled():
    assert email_service.get_config() is None
    assert email_service.is_configured() is False


def test_host_without_any_from_address_stays_disabled(monkeypatch):
    """A host with nothing to send as is a misconfiguration, not a working mailbox. Disabled rather
    than failing later at the first send."""
    monkeypatch.setenv("SMTP_HOST", "smtp.office365.com")

    assert email_service.get_config() is None


def test_from_address_falls_back_to_username(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.office365.com")
    monkeypatch.setenv("SMTP_USERNAME", "purchasing@example.test")

    config = email_service.get_config()

    assert config is not None
    assert config.from_address == "purchasing@example.test"
    assert config.port == 587
    assert config.use_tls is True


def test_explicit_from_address_wins(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.office365.com")
    monkeypatch.setenv("SMTP_USERNAME", "svc-nexus@example.test")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "purchasing@example.test")

    assert email_service.get_config().from_address == "purchasing@example.test"


def test_tls_can_be_turned_off_for_a_capture_server(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "nexus@example.test")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    assert email_service.get_config().use_tls is False


def test_sending_while_unconfigured_is_refused():
    with pytest.raises(email_service.EmailError):
        email_service.send_email(to="v@example.test", subject="x", body="y")
