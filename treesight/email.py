"""Internal email notifications via Azure Communication Services.

Provides ``send_email`` for operator and verified-user messages, and
``send_contact_notification`` for forwarding contact-form submissions.
Both gracefully degrade (log + return False) when ACS is not configured.

SECURITY: ``send_email`` enforces a recipient allowlist to prevent the
system from being used as a spam relay.  The allowlist is the union of:

1. ``NOTIFICATION_EMAIL`` (operator inbox, set via env var)
2. An optional *verified_recipients* set passed by the caller — intended
   for addresses extracted from **verified JWT claims** (Azure Entra
   External ID validates the email before issuing tokens).

Never pass user-**supplied** (unverified) addresses.  Only pass
addresses that the IdP has already confirmed.
"""

from __future__ import annotations

import html
import logging
import os

logger = logging.getLogger(__name__)


def _allowed_recipients() -> set[str]:
    """Return the baseline set of email addresses we are permitted to send to.

    Currently this is just ``NOTIFICATION_EMAIL``.  Callers that hold
    verified user addresses (e.g. from JWT claims) extend the effective
    allowlist via the *verified_recipients* parameter on ``send_email``.
    """
    notify = os.environ.get("NOTIFICATION_EMAIL", "").strip().lower()
    if notify:
        return {notify}
    return set()


def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: str | None = None,
    *,
    verified_recipients: set[str] | None = None,
) -> bool:
    """Send an email via Azure Communication Services.

    The *to* address **must** appear in the effective allowlist, which is
    the union of:

    * ``NOTIFICATION_EMAIL`` (always checked)
    * *verified_recipients* — addresses the **caller** vouches for,
      typically extracted from a verified JWT ``email`` claim.

    Any other recipient is rejected to prevent accidental use as a spam
    relay.

    Returns True on success, False on failure.  Never raises — callers
    can treat email as best-effort.
    """
    conn_str = os.environ.get("COMMUNICATION_SERVICES_CONNECTION_STRING", "")
    sender = os.environ.get("EMAIL_SENDER_ADDRESS", "")

    if not conn_str or not sender:
        logger.warning(
            "Email not configured — set COMMUNICATION_SERVICES_CONNECTION_STRING "
            "and EMAIL_SENDER_ADDRESS"
        )
        return False

    effective_allowlist = _allowed_recipients()
    if verified_recipients:
        effective_allowlist = effective_allowlist | {v.strip().lower() for v in verified_recipients}

    if to.strip().lower() not in effective_allowlist:
        logger.warning("Recipient %r not in allowlist — email blocked", to)
        return False

    try:
        from azure.communication.email import EmailClient

        client = EmailClient.from_connection_string(conn_str)
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {
                "subject": subject,
                "html": body_html,
            },
        }
        if body_text:
            message["content"]["plainText"] = body_text

        poller = client.begin_send(message)
        result = poller.result()
        logger.info("Email sent: id=%s, status=%s", result.get("id"), result.get("status"))
        return True
    except Exception:
        logger.exception("Failed to send email")
        return False


def send_contact_notification(record: dict) -> bool:
    """Forward a contact-form submission to the configured notification address."""
    notify_to = os.environ.get("NOTIFICATION_EMAIL", "")
    if not notify_to:
        logger.info("NOTIFICATION_EMAIL not set — skipping contact notification")
        return False

    # Escape user-supplied values before embedding in HTML
    email_val = html.escape(record.get("email", "unknown"))
    org = html.escape(record.get("organization", "\u2014"))
    use_case = html.escape(record.get("use_case", "\u2014"))
    submitted = html.escape(record.get("submitted_at", "\u2014"))
    submission_id = html.escape(record.get("submission_id", "\u2014"))

    subject = f"TreeSight contact: {record.get('organization') or record.get('email', 'unknown')}"
    body_html = (
        "<h2>New Contact Form Submission</h2>"
        "<table>"
        f"<tr><td><strong>Email:</strong></td><td>{email_val}</td></tr>"
        f"<tr><td><strong>Organisation:</strong></td><td>{org}</td></tr>"
        f"<tr><td><strong>Use Case:</strong></td><td>{use_case}</td></tr>"
        f"<tr><td><strong>Submitted:</strong></td><td>{submitted}</td></tr>"
        f"<tr><td><strong>ID:</strong></td><td>{submission_id}</td></tr>"
        "</table>"
    )
    dash = "\u2014"
    body_text = (
        "New Contact Form Submission\n\n"
        f"Email: {record.get('email', 'unknown')}\n"
        f"Organisation: {record.get('organization', dash)}\n"
        f"Use Case: {record.get('use_case', dash)}\n"
        f"Submitted: {record.get('submitted_at', dash)}\n"
        f"ID: {record.get('submission_id', dash)}\n"
    )

    return send_email(notify_to, subject, body_html, body_text)
