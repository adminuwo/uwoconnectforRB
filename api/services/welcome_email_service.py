import logging
import threading
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

class WelcomeEmailService:
    @staticmethod
    def _build_html_template(name, login_url="https://app.uwoconnect.com", temp_password=None):
        first_name = (name or "there").strip().capitalize()
        credentials_block = ""
        if temp_password:
            credentials_block = f"""
            <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:16px 20px;margin:24px 0 8px;">
                <p style="margin:0 0 6px;color:#166534;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:1px;">Your Temporary Password</p>
                <p style="margin:0;font-family:monospace;font-size:18px;font-weight:700;color:#15803d;letter-spacing:1px;">{temp_password}</p>
                <p style="margin:8px 0 0;color:#166534;font-size:12px;">Please change your password after your initial sign-in.</p>
            </div>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to UwoConnect</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f4f5f7;padding:36px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:580px;background-color:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 10px 25px rgba(0,0,0,0.05);border:1px solid #e5e7eb;" cellspacing="0" cellpadding="0">
          <!-- Gradient Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#10b981 0%,#059669 50%,#047857 100%);padding:44px 36px 36px;text-align:center;">
              <div style="display:inline-block;background:rgba(255,255,255,0.18);padding:10px 22px;border-radius:30px;backdrop-filter:blur(4px);margin-bottom:14px;">
                <span style="color:#ffffff;font-size:14px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">⚡ Business Automation</span>
              </div>
              <h1 style="color:#ffffff;margin:0;font-size:30px;font-weight:800;letter-spacing:-0.5px;">Welcome to UwoConnect!</h1>
              <p style="color:rgba(255,255,255,0.9);margin:8px 0 0;font-size:15px;font-weight:400;">Your all-in-one customer communication powerhouse</p>
            </td>
          </tr>

          <!-- Main Body -->
          <tr>
            <td style="padding:36px 36px 28px;">
              <p style="margin:0 0 16px;font-size:17px;font-weight:600;color:#111827;">Hi {first_name},</p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.65;color:#4b5563;">
                We're absolutely thrilled to welcome you to <strong>UwoConnect</strong>! Your account is officially set up and ready to transform how you communicate with your customers, close deals, and automate day-to-day operations.
              </p>

              {credentials_block}

              <!-- Feature Highlights -->
              <div style="margin:28px 0;background:#f9fafb;border-radius:16px;padding:24px;border:1px solid #f3f4f6;">
                <p style="margin:0 0 16px;font-size:14px;font-weight:700;color:#111827;text-transform:uppercase;letter-spacing:0.8px;">Here's what you can do right away:</p>
                
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:14px;">
                  <tr>
                    <td width="36" valign="top" style="font-size:20px;">💬</td>
                    <td style="padding-left:12px;font-size:14px;line-height:1.5;color:#374151;">
                      <strong style="color:#111827;">Unified Inbox:</strong> Manage WhatsApp, Instagram, Facebook, and Email conversations in one unified feed.
                    </td>
                  </tr>
                </table>

                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:14px;">
                  <tr>
                    <td width="36" valign="top" style="font-size:20px;">🤖</td>
                    <td style="padding-left:12px;font-size:14px;line-height:1.5;color:#374151;">
                      <strong style="color:#111827;">AI Agents & Workflows:</strong> Deploy smart auto-replies, keyword triggers, and multi-step automated customer journeys.
                    </td>
                  </tr>
                </table>

                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td width="36" valign="top" style="font-size:20px;">📊</td>
                    <td style="padding-left:12px;font-size:14px;line-height:1.5;color:#374151;">
                      <strong style="color:#111827;">CRM & Team Inbox:</strong> Track deals, assign conversations to teammates, and gain instant visibility with live analytics.
                    </td>
                  </tr>
                </table>
              </div>

              <!-- CTA Button -->
              <div style="text-align:center;margin:32px 0 24px;">
                <a href="{login_url}" style="display:inline-block;background:linear-gradient(135deg,#10b981 0%,#059669 100%);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;padding:16px 40px;border-radius:12px;box-shadow:0 4px 14px rgba(16,185,129,0.35);letter-spacing:0.3px;" target="_blank">
                  Go to Your Dashboard &rarr;
                </a>
              </div>

              <p style="margin:24px 0 0;font-size:14px;line-height:1.6;color:#6b7280;text-align:center;">
                Have questions or need assistance setting up? Just reply to this email or reach our support team at <a href="mailto:support@uwoconnect.com" style="color:#10b981;text-decoration:none;font-weight:600;">support@uwoconnect.com</a>.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f9fafb;padding:24px 36px;border-top:1px solid #f3f4f6;text-align:center;">
              <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#111827;">UwoConnect</p>
              <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.5;">
                Unified Communication &amp; Business Automation Platform<br>
                &copy; 2026 UwoConnect. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    @classmethod
    def send_welcome_email(cls, user, login_url=None, temp_password=None):
        """
        Asynchronously sends a branded welcome email to the newly registered user.
        Non-blocking: executed in a background daemon thread.
        """
        if not user or not getattr(user, 'email', None):
            return

        recipient_email = str(user.email).lower().strip()
        if not recipient_email or "@" not in recipient_email:
            return

        name = getattr(user, 'first_name', '') or getattr(user, 'username', '') or 'there'
        login_url = login_url or "https://app.uwoconnect.com"

        def _dispatch():
            try:
                subject = "Welcome to UwoConnect! 🚀 Let's Automate Your Business"
                plain_text = (
                    f"Hi {name},\n\n"
                    f"Welcome to UwoConnect!\n\n"
                    f"Your account has been successfully created. UwoConnect is your all-in-one platform for "
                    f"Unified Customer Messaging (WhatsApp, Instagram, Facebook), AI Automation, and CRM.\n\n"
                    f"{'Temporary Password: ' + temp_password + chr(10) if temp_password else ''}"
                    f"Access your dashboard here: {login_url}\n\n"
                    f"If you have any questions, reach us at support@uwoconnect.com.\n\n"
                    f"Best regards,\nThe UwoConnect Team"
                )

                html_content = cls._build_html_template(name, login_url=login_url, temp_password=temp_password)

                from_email = (
                    f"UwoConnect <{settings.EMAIL_HOST_USER}>"
                    if getattr(settings, 'EMAIL_HOST_USER', None)
                    else getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@uwoconnect.app')
                )

                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=from_email,
                    recipient_list=[recipient_email],
                    html_message=html_content,
                    fail_silently=False
                )
                backend_type = "SMTP" if getattr(settings, 'EMAIL_HOST_USER', None) else "Console (Credentials missing in .env)"
                logger.info(f"[WelcomeEmail] Dispatched via {backend_type} to {recipient_email}")
                print(f"\n[WelcomeEmail] Dispatched welcome email via {backend_type} to {recipient_email}\n")
            except Exception as exc:
                logger.warning(f"[WelcomeEmail] Could not send welcome email to {recipient_email}: {exc}")
                print(f"\n[WelcomeEmail ERROR] Could not send welcome email to {recipient_email}: {exc}\n")

        thread = threading.Thread(target=_dispatch, daemon=True)
        thread.start()
