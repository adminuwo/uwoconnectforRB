import logging
import secrets
import threading
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from ..models import EmailVerificationOTP, User
from .welcome_email_service import DEFAULT_SUPPORT_EMAIL

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
RESEND_COOLDOWN_SECONDS = 30
MAX_VERIFICATION_ATTEMPTS = 5

class EmailVerificationService:
    @staticmethod
    def generate_otp() -> str:
        """Generates a cryptographically secure 6-digit numeric OTP."""
        return f"{secrets.randbelow(900000) + 100000}"

    @classmethod
    def create_and_send_otp(cls, email: str, name: str = None) -> dict:
        """
        Creates a new verification OTP record and sends it to the user's registered email.
        Enforces a 30-second resend cooldown.
        """
        email = email.lower().strip()

        # Check resend cooldown
        recent_otp = EmailVerificationOTP.objects.filter(
            email=email,
            is_verified=False
        ).order_by('-created_at').first()

        now = timezone.now()
        if recent_otp and (now - recent_otp.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
            remaining = int(RESEND_COOLDOWN_SECONDS - (now - recent_otp.created_at).total_seconds())
            return {
                "success": False,
                "cooldown": True,
                "remaining_seconds": remaining,
                "message": f"Please wait {remaining} seconds before requesting a new code."
            }

        # Invalidate/delete any previous unverified OTPs
        EmailVerificationOTP.objects.filter(email=email, is_verified=False).delete()

        # Generate fresh OTP
        otp = cls.generate_otp()
        expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

        otp_record = EmailVerificationOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at,
            is_verified=False,
            attempts=0
        )

        # Dispatch email asynchronously
        cls._dispatch_email_async(email=email, otp=otp, name=name)

        resp = {
            "success": True,
            "message": f"Verification code has been sent to {email}.",
            "email": email,
            "expires_in_minutes": OTP_EXPIRY_MINUTES
        }

        # Development helper: if in DEBUG mode or console backend, include otp_debug for smooth testing
        if getattr(settings, 'DEBUG', False) or not getattr(settings, 'EMAIL_HOST_USER', None):
            resp["otp_debug"] = otp

        return resp

    @classmethod
    def verify_otp(cls, email: str, otp: str) -> dict:
        """
        Verifies the user's provided OTP code.
        Checks expiry, attempts limit, and validity.
        """
        if not email or not otp:
            return {"success": False, "message": "Email and OTP code are required."}

        email = email.lower().strip()
        otp = str(otp).strip()

        otp_record = EmailVerificationOTP.objects.filter(
            email=email,
            is_verified=False
        ).order_by('-created_at').first()

        if not otp_record:
            return {"success": False, "message": "No active verification code found for this email. Please request a new one."}

        # Check maximum attempts to prevent brute-force attacks
        if otp_record.attempts >= MAX_VERIFICATION_ATTEMPTS:
            otp_record.delete()
            return {"success": False, "message": "Too many invalid attempts. Please request a fresh verification code."}

        # Check expiration
        now = timezone.now()
        expiry_limit = otp_record.expires_at or (otp_record.created_at + timedelta(minutes=OTP_EXPIRY_MINUTES))
        if now > expiry_limit:
            otp_record.delete()
            return {"success": False, "message": "Verification code has expired. Please request a new one."}

        # Validate code match
        if otp_record.otp != otp:
            otp_record.attempts += 1
            otp_record.save(update_fields=['attempts'])
            remaining = MAX_VERIFICATION_ATTEMPTS - otp_record.attempts
            return {
                "success": False,
                "message": f"Invalid verification code. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
            }

        # Atomically mark OTP as verified to prevent concurrency race conditions
        updated_count = EmailVerificationOTP.objects.filter(
            id=otp_record.id,
            is_verified=False,
            otp=otp
        ).update(is_verified=True)

        if updated_count == 0:
            return {
                "success": False,
                "message": "Verification code has already been verified or invalidated."
            }

        # Activate user email verification
        user = User.objects.filter(email=email).first()
        if user:
            user.email_verified = True
            user.email_verified_at = now
            if user.status == 'PENDING':
                user.status = 'APPROVED'
            user.save(update_fields=['email_verified', 'email_verified_at', 'status'])

        return {"success": True, "message": "Email verified successfully.", "user": user}

    @classmethod
    def _dispatch_email_async(cls, email: str, otp: str, name: str = None):
        """Dispatches the verification email in a background daemon thread."""
        def _send():
            try:
                subject = f"Your UWO Connect Verification Code: {otp}"
                plain_text = (
                    f"Welcome to UWO Connect!\n\n"
                    f"Your 6-digit verification code is: {otp}\n\n"
                    f"This code will expire in {OTP_EXPIRY_MINUTES} minutes.\n"
                    f"If you did not request this code, please ignore this email.\n\n"
                    f"Best regards,\nThe UWO Connect Team"
                )

                html_content = cls._build_html_email(otp=otp, name=name, email=email)

                from_email = (
                    f"UWO Connect <{settings.EMAIL_HOST_USER}>"
                    if getattr(settings, 'EMAIL_HOST_USER', None)
                    else f"UWO Connect <{DEFAULT_SUPPORT_EMAIL}>"
                )

                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=from_email,
                    recipient_list=[email],
                    html_message=html_content,
                    fail_silently=False
                )
                logger.info(f"[EmailVerification] Successfully sent OTP to {email}")
                print(f"\n[EmailVerification] Dispatched OTP [{otp}] to {email}\n")
            except Exception as e:
                logger.error(f"[EmailVerification Error] Failed to send OTP email to {email}: {e}")
                print(f"\n[EmailVerification ERROR] Failed to send OTP email to {email}: {e}\n")

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()
        return thread

    @classmethod
    def _build_html_email(cls, otp: str, name: str = None, email: str = "") -> str:
        raw_name = (name or "").strip()
        first_name = raw_name.split()[0].capitalize() if raw_name else "there"

        # Split 6-digit OTP into styled digits for maximum clarity
        otp_digits_html = "".join(
            f'<td style="padding:0 4px;"><div style="display:inline-block;width:44px;height:52px;line-height:52px;text-align:center;font-size:26px;font-weight:800;color:#065f46;background:#ecfdf5;border:1.5px solid #a7f3d0;border-radius:10px;font-family:\'Courier New\',Courier,monospace;">{d}</div></td>'
            for d in str(otp)
        )

        return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verify Your Email - UWO Connect</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f1f5f9;padding:32px 12px;">
    <tr>
      <td align="center">
        <!-- Container Card -->
        <table role="presentation" width="100%" style="max-width:540px;background:#ffffff;border-radius:24px;border:1px solid #e2e8f0;overflow:hidden;box-shadow:0 10px 25px -5px rgba(0,0,0,0.05);" cellspacing="0" cellpadding="0">
          <!-- Header Banner -->
          <tr>
            <td style="background:linear-gradient(135deg,#059669 0%,#047857 100%);padding:28px 32px;text-align:center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center" style="padding-bottom:10px;">
                    <div style="width:48px;height:48px;border-radius:14px;background:#ffffff;display:inline-block;line-height:48px;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,0.15);">
                      <span style="font-size:24px;">🔐</span>
                    </div>
                  </td>
                </tr>
                <tr>
                  <td align="center">
                    <h1 style="margin:0;font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">Verify Your Email Address</h1>
                    <p style="margin:6px 0 0 0;font-size:13px;color:#d1fae5;font-weight:500;">One-Time Password for UWO Connect</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding:32px 32px 24px 32px;">
              <p style="margin:0 0 16px 0;font-size:15px;color:#334155;line-height:1.5;">
                Hello <strong style="color:#0f172a;">{first_name}</strong>,
              </p>
              <p style="margin:0 0 24px 0;font-size:14px;color:#475569;line-height:1.6;">
                Thank you for creating your account with <strong>UWO Connect</strong>. To complete your registration and protect your business workspace, please enter the 6-digit verification code below:
              </p>

              <!-- OTP Digits Box -->
              <table role="presentation" align="center" cellspacing="0" cellpadding="0" style="margin:20px auto 26px auto;">
                <tr>
                  {otp_digits_html}
                </tr>
              </table>

              <!-- Notice Pill -->
              <div style="background:#fefce8;border:1px solid #fef08a;border-radius:12px;padding:12px 16px;margin-bottom:24px;text-align:center;">
                <p style="margin:0;font-size:13px;color:#854d0e;font-weight:600;">
                  ⏱ This code is valid for <strong>{OTP_EXPIRY_MINUTES} minutes</strong>. Do not share it with anyone.
                </p>
              </div>

              <p style="margin:0;font-size:13px;color:#64748b;line-height:1.5;">
                If you did not attempt to register on UWO Connect with this email (<em>{email}</em>), please disregard this message or contact <a href="mailto:{DEFAULT_SUPPORT_EMAIL}" style="color:#059669;text-decoration:none;font-weight:600;">{DEFAULT_SUPPORT_EMAIL}</a>.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8fafc;padding:20px 32px;border-top:1px solid #e2e8f0;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.5;">
                &copy; {timezone.now().year} UWO Connect (Unified Web Options Pvt Ltd). All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
