"""Tests for sms.py — outbound SMS/WhatsApp with a dev-mode fallback.

Mirrors mailer.py's contract: unconfigured = log to stderr and return True, so
the caregiver escalation ladder is exercisable without a Twilio account, and
callers can still tell a logged message from a delivered one via is_configured().
"""
import sms


def test_dev_mode_when_unconfigured(capsys):
    assert sms.is_configured("sms") is False
    assert sms.is_configured("whatsapp") is False
    assert sms.send_sms("+14155550100", "hello there") is True
    err = capsys.readouterr().err
    assert "[SMS:dev]" in err and "hello there" in err


def test_whatsapp_dev_mode(capsys):
    assert sms.send_whatsapp("+14155550100", "ping") is True
    assert "[WA:dev]" in capsys.readouterr().err


def test_twilio_payload_sms(monkeypatch):
    monkeypatch.setattr(sms, "SMS_FROM", "+15005550006")
    p = sms._twilio_payload("+14155550100", "body", "sms")
    assert p == {"To": "+14155550100", "From": "+15005550006", "Body": "body"}


def test_twilio_payload_whatsapp(monkeypatch):
    monkeypatch.setattr(sms, "WHATSAPP_FROM", "+15005550006")
    p = sms._twilio_payload("+14155550100", "body", "whatsapp")
    assert p["To"] == "whatsapp:+14155550100"
    assert p["From"] == "whatsapp:+15005550006"


def test_is_configured_needs_sid_token_and_from(monkeypatch):
    monkeypatch.setattr(sms, "TWILIO_SID", "AC123")
    monkeypatch.setattr(sms, "TWILIO_TOKEN", "tok")
    monkeypatch.setattr(sms, "SMS_FROM", "")
    assert sms.is_configured("sms") is False
    monkeypatch.setattr(sms, "SMS_FROM", "+15005550006")
    assert sms.is_configured("sms") is True


def test_notify_contact_routes_by_channel(monkeypatch):
    calls = []
    monkeypatch.setattr(sms, "send_sms", lambda to, t: calls.append(("sms", to)) or True)
    monkeypatch.setattr(sms, "send_whatsapp", lambda to, t: calls.append(("wa", to)) or True)
    sms.notify_contact({"phone": "+14155550100", "channel": "sms"}, "x")
    sms.notify_contact({"phone": "+14155550100", "channel": "whatsapp"}, "x")
    assert calls == [("sms", "+14155550100"), ("wa", "+14155550100")]
    # no phone → nothing sent
    assert sms.notify_contact({"phone": "", "channel": "sms"}, "x") is False
