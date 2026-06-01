"""
Email Service for Request Notifications

Sends email notifications for request lifecycle events (created, approved, rejected, forwarded, sla_skipped).
Uses SMTP when configured. Test mode logs to console instead of sending.
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

REQUEST_EMAIL_ENABLED = os.environ.get("REQUEST_EMAIL_NOTIFICATIONS", "false").lower() == "true"
REQUEST_EMAIL_TEST_MODE = os.environ.get("REQUEST_EMAIL_TEST_MODE", "true").lower() == "true"
REQUEST_EMAIL_TEST_RECIPIENT = os.environ.get("REQUEST_EMAIL_TEST_RECIPIENT", "test@example.com")
# Support SMTP_HOST or SMTP_SERVER; SMTP_FROM or EMAIL_FROM (Resend uses SMTP_SERVER, EMAIL_FROM)
SMTP_HOST = os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM") or os.environ.get("EMAIL_FROM") or SMTP_USER or "noreply@example.com"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://app.zoft.ai").rstrip("/")


def _send_smtp_sync(to_emails: List[str], subject: str, body_html: str) -> bool:
    """Sync SMTP send. Called via asyncio.to_thread. Port 465 uses SSL (Resend)."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP not configured. Skipping email send.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(to_emails)
        msg.attach(MIMEText(body_html, "html"))
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, to_emails, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, to_emails, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")
        return False


async def send_test_email(to_email: Optional[str] = None) -> Tuple[bool, str]:
    """
    Send a dummy test email. Bypasses REQUEST_EMAIL_ENABLED and REQUEST_EMAIL_TEST_MODE.
    Returns (success, message).
    """
    recipient = (to_email or REQUEST_EMAIL_TEST_RECIPIENT).strip()
    if not recipient or "@" not in recipient:
        return False, "Invalid recipient email"
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        return False, "SMTP not configured (SMTP_SERVER, SMTP_USER, SMTP_PASSWORD)"
    body = "<html><body><h3>Test Email</h3><p>This is a dummy test from the request notification system.</p></body></html>"
    try:
        await asyncio.to_thread(_send_smtp_sync, [recipient], "Request System - Test Email", body)
        return True, f"Test email sent to {recipient}"
    except Exception as e:
        logger.error(f"Test email failed: {e}")
        return False, str(e)


async def send_request_notification(
    event_type: str,
    recipient_emails: List[str],
    subject: str,
    body_html: str,
    request_number: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """
    Send request notification email. Fire-and-forget (non-blocking).
    When REQUEST_EMAIL_TEST_MODE=true, logs to console only (no SMTP needed).
    """
    if not REQUEST_EMAIL_ENABLED:
        return
    recipients = [e for e in recipient_emails if e and isinstance(e, str) and "@" in e]
    if not recipients:
        logger.debug(f"Email skipped: no valid recipients for event {event_type}")
        return
    if REQUEST_EMAIL_TEST_MODE:
        logger.info(
            f"[EMAIL TEST] event={event_type} request={request_number or request_id} "
            f"to={recipients} subject={subject}"
        )
        return
    try:
        await asyncio.to_thread(_send_smtp_sync, recipients, subject, body_html)
    except Exception as e:
        logger.error(f"Email notification failed ({event_type}): {e}")


_EVENT_COLORS = {
    "created": "#2D3377",
    "approved": "#16a34a",
    "rejected": "#dc2626",
    "forwarded": "#2D3377",
    "sla_auto_skipped": "#ea580c",
}

_EVENT_LABELS = {
    "created": "Request Created",
    "approved": "Request Approved",
    "rejected": "Request Rejected",
    "forwarded": "Request Forwarded",
    "sla_auto_skipped": "SLA Auto-Skipped",
}


def _build_email_body(event_type: str, request_number: str, subject: str, extra: str) -> str:
    accent = _EVENT_COLORS.get(event_type, "#2D3377")
    label = _EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
    inbox_url = f"{FRONTEND_URL}/inbox"

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr><td style="background-color:#2D3377;padding:20px 28px;">
          <span style="color:#ffffff;font-size:18px;font-weight:600;letter-spacing:0.3px;">MGM Request Management</span>
        </td></tr>

        <!-- Status badge -->
        <tr><td style="padding:24px 28px 0 28px;">
          <span style="display:inline-block;background-color:{accent};color:#ffffff;font-size:13px;font-weight:600;padding:5px 14px;border-radius:4px;letter-spacing:0.3px;">{label}</span>
        </td></tr>

        <!-- Request details -->
        <tr><td style="padding:20px 28px 0 28px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding:6px 0;color:#6b7280;font-size:13px;width:100px;vertical-align:top;">Request #</td>
              <td style="padding:6px 0;color:#111827;font-size:14px;font-weight:600;">{request_number}</td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#6b7280;font-size:13px;vertical-align:top;">Subject</td>
              <td style="padding:6px 0;color:#111827;font-size:14px;">{subject}</td>
            </tr>
          </table>
        </td></tr>

        <!-- Event-specific content -->
        <tr><td style="padding:16px 28px 0 28px;color:#374151;font-size:14px;line-height:1.6;">
          {extra}
        </td></tr>

        <!-- CTA button -->
        <tr><td style="padding:24px 28px 0 28px;" align="center">
          <a href="{inbox_url}" target="_blank"
             style="display:inline-block;padding:12px 32px;background-color:{accent};color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;border-radius:6px;letter-spacing:0.3px;">
            View Request
          </a>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:28px 28px 24px 28px;border-top:1px solid #e5e7eb;margin-top:24px;">
          <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.5;text-align:center;">
            This is an automated notification from MGM Request Management.<br>
            Please do not reply to this email.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def notify_request_created(
    requester_email: Optional[str],
    approver_email: Optional[str],
    request_number: str,
    subject: str,
    raised_by_name: str,
) -> None:
    """Notify requester and approver when request is created."""
    if not REQUEST_EMAIL_ENABLED:
        return
    recipients = [e for e in [requester_email, approver_email] if e]
    if not recipients:
        return
    extra = (
        f'<p style="margin:0 0 6px 0;"><strong>Raised by:</strong> {raised_by_name}</p>'
        f'<p style="margin:0;">Your request has been submitted and assigned for approval.</p>'
    )
    body = _build_email_body("created", request_number, subject, extra)
    subj = f"[Request #{request_number}] Created: {subject}"
    asyncio.create_task(
        send_request_notification("created", recipients, subj, body, request_number=request_number)
    )


async def notify_request_approved(
    requester_email: Optional[str],
    request_number: str,
    subject: str,
    approver_name: str,
) -> None:
    """Notify requester when request is fully approved."""
    if not REQUEST_EMAIL_ENABLED:
        return
    if not requester_email:
        return
    extra = (
        f'<p style="margin:0 0 6px 0;"><strong>Approved by:</strong> {approver_name}</p>'
        f'<p style="margin:0;">Your request has been fully approved.</p>'
    )
    body = _build_email_body("approved", request_number, subject, extra)
    subj = f"[Request #{request_number}] Approved: {subject}"
    asyncio.create_task(
        send_request_notification("approved", [requester_email], subj, body, request_number=request_number)
    )


async def notify_request_rejected(
    requester_email: Optional[str],
    request_number: str,
    subject: str,
    approver_name: str,
    reason: str,
) -> None:
    """Notify requester when request is rejected."""
    if not REQUEST_EMAIL_ENABLED:
        return
    if not requester_email:
        return
    extra = (
        f'<p style="margin:0 0 6px 0;"><strong>Rejected by:</strong> {approver_name}</p>'
        f'<p style="margin:0;"><strong>Reason:</strong> {reason}</p>'
    )
    body = _build_email_body("rejected", request_number, subject, extra)
    subj = f"[Request #{request_number}] Rejected: {subject}"
    asyncio.create_task(
        send_request_notification("rejected", [requester_email], subj, body, request_number=request_number)
    )


async def notify_request_forwarded(
    requester_email: Optional[str],
    next_approver_email: Optional[str],
    request_number: str,
    subject: str,
    from_name: str,
    to_name: str,
) -> None:
    """Notify requester and next approver when request is forwarded."""
    if not REQUEST_EMAIL_ENABLED:
        return
    recipients = [e for e in [requester_email, next_approver_email] if e]
    if not recipients:
        return
    extra = (
        f'<p style="margin:0 0 6px 0;">Forwarded from <strong>{from_name}</strong> to <strong>{to_name}</strong>.</p>'
        f'<p style="margin:0;">Pending approval from {to_name}.</p>'
    )
    body = _build_email_body("forwarded", request_number, subject, extra)
    subj = f"[Request #{request_number}] Forwarded for approval: {subject}"
    asyncio.create_task(
        send_request_notification("forwarded", recipients, subj, body, request_number=request_number)
    )


async def notify_sla_auto_skipped(
    requester_email: Optional[str],
    next_approver_email: Optional[str],
    request_number: str,
    subject: str,
    skipped_name: str,
    next_name: str,
) -> None:
    """Notify requester and next approver when SLA auto-skipped to next level."""
    if not REQUEST_EMAIL_ENABLED:
        return
    recipients = [e for e in [requester_email, next_approver_email] if e]
    if not recipients:
        return
    extra = (
        f'<p style="margin:0 0 6px 0;">SLA deadline exceeded. Auto-skipped from <strong>{skipped_name}</strong> to <strong>{next_name}</strong>.</p>'
        f'<p style="margin:0;">Pending approval from {next_name}.</p>'
    )
    body = _build_email_body("sla_auto_skipped", request_number, subject, extra)
    subj = f"[Request #{request_number}] SLA auto-skipped: {subject}"
    asyncio.create_task(
        send_request_notification("sla_auto_skipped", recipients, subj, body, request_number=request_number)
    )


# ============================================================================
# Team Invite Email
# ============================================================================


async def notify_member_invited(
    invitee_email: str,
    workspace_name: str,
    inviter_name: str,
    role: Optional[str] = None,
    designation: Optional[str] = None,
    invitation_token: Optional[str] = None,
) -> None:
    """Send invite email to new team member. Fire-and-forget.
    If invitation_token is provided, link goes to accept-invitation page.
    Otherwise falls back to generic register link (existing user case).
    """
    if not REQUEST_EMAIL_ENABLED:
        return
    if not invitee_email or "@" not in invitee_email:
        return

    role_line = f"<p><b>Role:</b> {designation or role or 'Team Member'}</p>" if (designation or role) else ""

    if invitation_token:
        accept_link = f"{FRONTEND_URL}/accept-invitation?token={invitation_token}"
        body_html = f"""
        <html><body style="font-family:sans-serif;">
        <h3>You've been invited to join a workspace</h3>
        <p><b>{inviter_name}</b> has invited you to <b>{workspace_name}</b>.</p>
        {role_line}
        <p>Click below to get started:</p>
        <p><a href="{accept_link}" style="display:inline-block;padding:10px 24px;background:#4f46e5;color:#fff;text-decoration:none;border-radius:6px;">Accept Invite</a></p>
        <p style="color:#888;font-size:12px;">This invitation expires in 7 days. If you already have an account, simply log in to accept.</p>
        </body></html>
        """
        subj = f"{inviter_name} invited you to {workspace_name}"
    else:
        dashboard_link = f"{FRONTEND_URL}/dashboard"
        body_html = f"""
        <html><body style="font-family:sans-serif;">
        <h3>You've been added to {workspace_name}</h3>
        <p><b>{inviter_name}</b> has added you to <b>{workspace_name}</b>.</p>
        {role_line}
        <p>You can access this workspace right away from your dashboard.</p>
        <p><a href="{dashboard_link}" style="display:inline-block;padding:10px 24px;background:#4f46e5;color:#fff;text-decoration:none;border-radius:6px;">Open Dashboard</a></p>
        </body></html>
        """
        subj = f"You've been added to {workspace_name}"

    asyncio.create_task(
        send_request_notification("invite", [invitee_email], subj, body_html)
    )
