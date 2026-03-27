"""Tests for treesight.email module."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

from treesight.email import send_contact_notification, send_email


class TestSendEmail:
    """Low-level send_email tests."""

    def test_returns_false_when_not_configured(self):
        """Gracefully degrades when env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            assert send_email("a@b.com", "Hi", "<p>body</p>") is False

    def test_returns_false_when_connection_string_missing(self):
        with patch.dict(
            os.environ,
            {"EMAIL_SENDER_ADDRESS": "noreply@example.com"},
            clear=True,
        ):
            assert send_email("a@b.com", "Hi", "<p>body</p>") is False

    def test_returns_false_when_sender_missing(self):
        with patch.dict(
            os.environ,
            {"COMMUNICATION_SERVICES_CONNECTION_STRING": "endpoint=https://x;key=y"},
            clear=True,
        ):
            assert send_email("a@b.com", "Hi", "<p>body</p>") is False

    def test_sends_email_successfully(self):
        """Verifies SDK is called correctly when configured."""
        mock_client = MagicMock()
        mock_poller = MagicMock()
        mock_poller.result.return_value = {"id": "msg-1", "status": "Succeeded"}
        mock_client.begin_send.return_value = mock_poller

        mock_module = MagicMock()
        mock_module.EmailClient.from_connection_string.return_value = mock_client

        with patch.dict(
            os.environ,
            {
                "COMMUNICATION_SERVICES_CONNECTION_STRING": "endpoint=https://x;accesskey=y",
                "EMAIL_SENDER_ADDRESS": "DoNotReply@abc.azurecomm.net",
            },
        ):
            with patch.dict(sys.modules, {"azure.communication.email": mock_module}):
                result = send_email("user@example.com", "Subject", "<p>Hi</p>", "Hi")

        assert result is True
        mock_client.begin_send.assert_called_once()
        msg = mock_client.begin_send.call_args[0][0]
        assert msg["recipients"]["to"][0]["address"] == "user@example.com"
        assert msg["content"]["subject"] == "Subject"
        assert msg["content"]["html"] == "<p>Hi</p>"
        assert msg["content"]["plainText"] == "Hi"

    def test_returns_false_on_sdk_exception(self):
        """Graceful failure when SDK raises."""
        mock_module = MagicMock()
        mock_module.EmailClient.from_connection_string.side_effect = RuntimeError("fail")

        with patch.dict(
            os.environ,
            {
                "COMMUNICATION_SERVICES_CONNECTION_STRING": "endpoint=https://x;accesskey=y",
                "EMAIL_SENDER_ADDRESS": "DoNotReply@abc.azurecomm.net",
            },
        ):
            with patch.dict(sys.modules, {"azure.communication.email": mock_module}):
                result = send_email("a@b.com", "Hi", "<p>body</p>")

        assert result is False


class TestSendContactNotification:
    """Tests for the contact-form forwarding helper."""

    def test_returns_false_when_notification_email_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            record = {"email": "user@example.com", "organization": "Org"}
            assert send_contact_notification(record) is False

    @patch("treesight.email.send_email", return_value=True)
    def test_calls_send_email_with_correct_args(self, mock_send):
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL": "admin@example.com"}):
            record = {
                "email": "user@example.com",
                "organization": "ACME",
                "use_case": "Deforestation monitoring",
                "submitted_at": "2025-01-15T10:00:00+00:00",
                "submission_id": "abc-123",
            }
            result = send_contact_notification(record)

        assert result is True
        mock_send.assert_called_once()
        to, subject, body_html, body_text = mock_send.call_args[0]
        assert to == "admin@example.com"
        assert "ACME" in subject
        assert "user@example.com" in body_html
        assert "ACME" in body_html
        assert "Deforestation monitoring" in body_html
        assert "abc-123" in body_html
        assert "user@example.com" in body_text

    @patch("treesight.email.send_email", return_value=True)
    def test_html_escapes_user_values(self, mock_send):
        """Ensure XSS-safe HTML output."""
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL": "admin@example.com"}):
            record = {
                "email": "user@example.com",
                "organization": '<script>alert("xss")</script>',
                "use_case": "normal",
                "submitted_at": "2025-01-15T10:00:00+00:00",
                "submission_id": "abc",
            }
            send_contact_notification(record)

        _, _, body_html, _ = mock_send.call_args[0]
        assert "<script>" not in body_html
        assert "&lt;script&gt;" in body_html
