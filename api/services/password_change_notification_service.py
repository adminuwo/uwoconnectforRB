"""
Password Change Notification Service
Centralized service for dispatching security confirmation emails whenever
a user's password is changed or reset across any flow (web, android, ios, admin).
"""
import logging
import threading
from datetime import datetime, timezone
from django.conf import settings
from django.core.mail import send_mail
from django.core.cache import cache

logger = logging.getLogger(__name__)

class PasswordChangeNotificationService:
    DEDUPLICATION_WINDOW_SECONDS = 10

    @classmethod
    def send_password_change_confirmation(cls, user, change_time=None, ip_address=None, user_agent=None, wait_sync=False):
        """
        Triggers a password change confirmation email to the user.
        Must only be called AFTER user.set_password() and user.save() have successfully completed.

        Args:
            user: User model instance
            change_time: Optional datetime object representing when the password changed
            ip_address: Optional IP address where change originated
            user_agent: Optional user agent string
            wait_sync: If True, executes synchronously (useful for tests); otherwise runs in daemon thread.
        """
        if not user or not getattr(user, 'email', None):
            logger.warning("[PasswordChangeEmail] Cannot send email: User has no valid email address.")
            return False

        email = user.email.strip().lower()
        if not email or '@' not in email:
            logger.warning(f"[PasswordChangeEmail] Invalid email address: {email}")
            return False

        # Deduplication check: prevent multiple duplicate emails for the same user within window
        dedup_key = f"pwd_change_notif_{user.id}"
        if cache.get(dedup_key):
            logger.info(f"[PasswordChangeEmail] Deduplicated email for user {user.id} ({email}) within {cls.DEDUPLICATION_WINDOW_SECONDS}s window.")
            return True

        # Set deduplication flag in cache
        cache.set(dedup_key, True, timeout=cls.DEDUPLICATION_WINDOW_SECONDS)

        # Ensure timestamp is set
        if not change_time:
            change_time = datetime.now(timezone.utc)

        formatted_time = change_time.strftime("%A, %B %d, %Y at %H:%M:%S UTC")

        # Determine user display name
        display_name = (
            f"{user.first_name} {user.last_name}".strip()
            if (getattr(user, 'first_name', None) or getattr(user, 'last_name', None))
            else (getattr(user, 'username', '') or 'Valued User')
        )

        def _send():
            try:
                subject = "Your UWOConnect Password Has Been Changed Successfully"
                plain_body = cls._build_plain_text(
                    display_name=display_name,
                    formatted_time=formatted_time,
                    email=email,
                    ip_address=ip_address
                )
                html_body = cls._build_html_email(
                    display_name=display_name,
                    formatted_time=formatted_time,
                    email=email,
                    ip_address=ip_address
                )

                from_email = (
                    f"UWOConnect Security <{settings.EMAIL_HOST_USER}>"
                    if getattr(settings, 'EMAIL_HOST_USER', None)
                    else getattr(settings, 'DEFAULT_FROM_EMAIL', 'security@uwoconnect.app')
                )

                send_mail(
                    subject=subject,
                    message=plain_body,
                    from_email=from_email,
                    recipient_list=[email],
                    html_message=html_body,
                    fail_silently=False
                )
                logger.info(f"[PasswordChangeEmail] Confirmation email successfully sent to {email}")
                print(f"[PasswordChangeEmail] Successfully dispatched confirmation email to {email}")
                return True
            except Exception as e:
                # Log failure securely without breaking the password change flow
                logger.error(f"[PasswordChangeEmail ERROR] Failed to deliver password change email to {email}: {e}")
                print(f"[PasswordChangeEmail ERROR] Failed to deliver password change email to {email}: {e}")
                return False

        if wait_sync:
            return _send()

        # Dispatch in background daemon thread for fast, non-blocking API response
        thread = threading.Thread(target=_send, daemon=True, name=f"PwdChangeEmail-{user.id}")
        thread.start()
        return True

    @classmethod
    def _build_plain_text(cls, display_name: str, formatted_time: str, email: str, ip_address: str = None) -> str:
        """Constructs plain text email adhering strictly to security requirements."""
        lines = [
            f"Hello {display_name},",
            "",
            "This is a confirmation that your UWOConnect account password was changed successfully.",
            "",
            "If you made this change, no further action is required.",
            "",
            "If you did not change your password, please secure your account immediately by resetting your password and contacting support.",
            "",
            f"Account: {email}",
            f"Date and Time: {formatted_time}",
        ]
        if ip_address:
            lines.append(f"IP Address: {ip_address}")

        lines.extend([
            "",
            "Regards,",
            "UWOConnect Security Team",
            "https://uwoconnect.aisa24.com"
        ])
        return "\n".join(lines)

    @classmethod
    def _build_html_email(cls, display_name: str, formatted_time: str, email: str, ip_address: str = None) -> str:
        """Constructs professional HTML email without exposing any sensitive credentials."""
        ip_row = ""
        if ip_address:
            ip_row = f"""
            <tr>
              <td style="padding: 6px 0; color: #64748b; font-size: 13px; font-weight: 500;">Originating IP:</td>
              <td style="padding: 6px 0; color: #1e293b; font-size: 13px; font-weight: 600; text-align: right;">{ip_address}</td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Password Changed Successfully</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f8fafc; padding: 30px 15px;">
    <tr>
      <td align="center">
        <!-- Container -->
        <table role="presentation" width="100%" style="max-width: 540px; background-color: #ffffff; border-radius: 14px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.04);">
          <!-- Header -->
          <tr>
            <td style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 30px 32px; text-align: center;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <div style="display: inline-block; width: 48px; height: 48px; border-radius: 50%; background-color: #10b981; line-height: 48px; text-align: center; color: #ffffff; font-size: 24px; font-weight: bold;">
                      &#10003;
                    </div>
                    <h1 style="color: #ffffff; margin: 16px 0 4px 0; font-size: 20px; font-weight: 700; letter-spacing: -0.3px;">Password Changed Successfully</h1>
                    <p style="color: #94a3b8; margin: 0; font-size: 13px;">UWOConnect Security Notification</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding: 32px 32px 24px 32px;">
              <p style="font-size: 15px; color: #334155; line-height: 1.6; margin: 0 0 16px 0;">
                Hello <strong>{display_name}</strong>,
              </p>
              <p style="font-size: 14px; color: #475569; line-height: 1.6; margin: 0 0 20px 0;">
                This is a confirmation that your <strong>UWOConnect</strong> account password was changed successfully.
              </p>

              <!-- Details Box -->
              <table role="presentation" width="100%" style="background-color: #f1f5f9; border-radius: 8px; padding: 14px 18px; margin: 0 0 24px 0;" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding: 6px 0; color: #64748b; font-size: 13px; font-weight: 500;">Account:</td>
                  <td style="padding: 6px 0; color: #1e293b; font-size: 13px; font-weight: 600; text-align: right;">{email}</td>
                </tr>
                <tr>
                  <td style="padding: 6px 0; color: #64748b; font-size: 13px; font-weight: 500;">Date & Time:</td>
                  <td style="padding: 6px 0; color: #1e293b; font-size: 13px; font-weight: 600; text-align: right;">{formatted_time}</td>
                </tr>
                <tr>
                  <td style="padding: 6px 0; color: #64748b; font-size: 13px; font-weight: 500;">Status:</td>
                  <td style="padding: 6px 0; color: #10b981; font-size: 13px; font-weight: 700; text-align: right;">Updated Successfully</td>
                </tr>
                {ip_row}
              </table>

              <!-- Notice Box -->
              <div style="background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 14px 16px; border-radius: 4px; margin: 0 0 20px 0;">
                <p style="font-size: 13px; color: #065f46; margin: 0; line-height: 1.5;">
                  <strong>If you made this change</strong>, no further action is required.
                </p>
              </div>

              <!-- Warning Box -->
              <div style="background-color: #fff1f2; border-left: 4px solid #f43f5e; padding: 14px 16px; border-radius: 4px; margin: 0 0 24px 0;">
                <p style="font-size: 13px; color: #9f1239; margin: 0; line-height: 1.5;">
                  <strong>If you did not change your password</strong>, please secure your account immediately by resetting your password and contacting support.
                </p>
              </div>

              <p style="font-size: 14px; color: #475569; line-height: 1.6; margin: 0;">
                Regards,<br>
                <strong>UWOConnect Security Team</strong>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 32px; text-align: center;">
              <p style="font-size: 12px; color: #94a3b8; margin: 0 0 4px 0;">
                This is an automated security notification sent to {email}.
              </p>
              <p style="font-size: 12px; color: #94a3b8; margin: 0;">
                UWOConnect &bull; Unified Business Automation
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
