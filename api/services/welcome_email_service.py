import logging
import threading
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

DEFAULT_WEB_URL = "https://uwoconnect.aisa24.com"
DEFAULT_APP_URL = "https://play.google.com/store/apps/details?id=com.uwo.uwoconnect"
DEFAULT_SUPPORT_EMAIL = "connect@uwo24.com"

class WelcomeEmailService:
    @staticmethod
    def _build_html_template(
        name,
        login_url=DEFAULT_WEB_URL,
        app_url=DEFAULT_APP_URL,
        support_email=DEFAULT_SUPPORT_EMAIL,
        temp_password=None
    ):
        raw_name = (name or "").strip()
        first_name = raw_name.split()[0].capitalize() if raw_name else "there"
        login_url = login_url or DEFAULT_WEB_URL
        app_url = app_url or DEFAULT_APP_URL
        support_email = support_email or DEFAULT_SUPPORT_EMAIL

        credentials_block = ""
        if temp_password:
            credentials_block = f"""
            <!-- Temporary Password Card -->
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:22px 0;background:#f0fdf4;border:1.5px dashed #86efac;border-radius:14px;overflow:hidden;">
              <tr>
                <td style="padding:18px 22px;">
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                    <tr>
                      <td style="font-size:12px;font-weight:700;color:#166534;text-transform:uppercase;letter-spacing:1.2px;padding-bottom:6px;">
                        🔐 Your Temporary Access Credentials
                      </td>
                    </tr>
                    <tr>
                      <td style="font-family:'Courier New',Courier,monospace;font-size:19px;font-weight:700;color:#15803d;letter-spacing:1px;padding:4px 0 6px;">
                        {temp_password}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:12px;color:#166534;line-height:1.4;">
                        For your security, please update your password immediately after signing in.
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            """

        return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>Welcome to UWO Connect! 🎉</title>
  <!--[if mso]>
  <style type="text/css">
    table {{border-collapse:collapse;border-spacing:0;margin:0;}}
    div, td, a, span {{font-family:Arial, sans-serif !important;}}
  </style>
  <![endif]-->
  <style>
    :root {{
      color-scheme: light dark;
      supported-color-schemes: light dark;
    }}
    body {{
      margin: 0 !important;
      padding: 0 !important;
      -webkit-text-size-adjust: 100% !important;
      -ms-text-size-adjust: 100% !important;
      background-color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }}
    table {{
      border-collapse: collapse;
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
    }}
    img {{
      border: 0;
      line-height: 100%;
      outline: none;
      text-decoration: none;
      -ms-interpolation-mode: bicubic;
    }}
    .feature-card {{
      transition: transform 0.2s ease;
    }}
    @media only screen and (max-width: 620px) {{
      .wrapper-table {{
        width: 100% !important;
        padding: 10px !important;
      }}
      .main-container {{
        width: 100% !important;
        border-radius: 16px !important;
      }}
      .content-padding {{
        padding: 24px 20px !important;
      }}
      .hero-padding {{
        padding: 32px 20px 28px !important;
      }}
      .hero-title {{
        font-size: 24px !important;
      }}
      .feature-box {{
        padding: 14px 14px !important;
      }}
      .cta-button {{
        display: block !important;
        width: 100% !important;
        text-align: center !important;
        box-sizing: border-box !important;
      }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;color:#0f172a;">
  <!-- Email Wrapper -->
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="wrapper-table" style="background-color:#f1f5f9;padding:32px 12px;">
    <tr>
      <td align="center">
        <!--[if (gte mso 9)|(IE)]>
        <table align="center" border="0" cellspacing="0" cellpadding="0" width="600">
        <tr>
        <td align="center" valign="top" width="600">
        <![endif]-->
        <table role="presentation" width="100%" class="main-container" style="max-width:600px;background-color:#ffffff;border-radius:22px;overflow:hidden;box-shadow:0 12px 36px rgba(15,23,42,0.08);border:1px solid #e2e8f0;" cellspacing="0" cellpadding="0">
          
          <!-- Top Brand Bar -->
          <tr>
            <td style="padding:22px 32px 20px;background-color:#ffffff;border-bottom:1px solid #f1f5f9;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="left" valign="middle">
                    <table role="presentation" cellspacing="0" cellpadding="0">
                      <tr>
                        <td valign="middle" style="padding-right:12px;">
                          <!-- Official Logo Image / Fallback -->
                          <div style="width:42px;height:42px;border-radius:12px;background:#f0fdf4;border:1.5px solid #d1fae5;overflow:hidden;text-align:center;line-height:42px;">
                            <img src="https://uwoconnect.aisa24.com/download%20(3).gif" alt="UWO Connect Logo" width="42" height="42" style="display:block;width:42px;height:42px;object-fit:cover;border-radius:10px;" onerror="this.style.display='none';">
                          </div>
                        </td>
                        <td valign="middle">
                          <span style="font-size:20px;font-weight:800;color:#0f172a;letter-spacing:-0.5px;display:inline-block;line-height:1.1;">
                            UWO <span style="color:#059669;">Connect</span>
                          </span>
                          <br>
                          <span style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:1.4px;display:inline-block;margin-top:2px;">
                            AI Workspace &amp; CRM
                          </span>
                        </td>
                      </tr>
                    </table>
                  </td>
                  <td align="right" valign="middle">
                    <div style="display:inline-block;background:#ecfdf5;border:1px solid #a7f3d0;padding:5px 12px;border-radius:20px;">
                      <span style="color:#047857;font-size:11px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">● Live Workspace</span>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Gradient Hero Banner Section -->
          <tr>
            <td class="hero-padding" style="background:linear-gradient(135deg, #059669 0%, #047857 50%, #064e3b 100%);padding:42px 36px 36px;text-align:center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <div style="display:inline-block;background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.25);padding:8px 20px;border-radius:30px;margin-bottom:16px;">
                      <span style="color:#ffffff;font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">✨ Welcome Aboard</span>
                    </div>
                    <h1 class="hero-title" style="color:#ffffff;margin:0 0 10px;font-size:28px;font-weight:800;letter-spacing:-0.6px;line-height:1.25;">
                      Welcome to UWO Connect! 🎉
                    </h1>
                    <p style="color:#d1fae5;margin:0;font-size:15px;font-weight:500;line-height:1.5;max-width:460px;">
                      Connect everything. Automate anything.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Email Content -->
          <tr>
            <td class="content-padding" style="padding:36px 36px 30px;">
              <!-- Personalized Greeting -->
              <p style="margin:0 0 16px;font-size:17px;font-weight:700;color:#0f172a;">
                Hi {first_name},
              </p>

              <!-- Opening Copy -->
              <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#334155;">
                Take a deep breath — the days of juggling five different apps are officially over.
              </p>

              <p style="margin:0 0 24px;font-size:15px;line-height:1.7;color:#334155;">
                No more switching between WhatsApp, Instagram, Facebook, Gmail, Excel sheets, and a separate CRM. No more missed enquiries. No more “Who replied to this customer?” confusion.
              </p>

              {credentials_block}

              <!-- Section Subheading -->
              <div style="margin:28px 0 16px;border-top:1px solid #f1f5f9;padding-top:22px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td>
                      <h3 style="margin:0;font-size:16px;font-weight:800;color:#065f46;letter-spacing:-0.2px;text-transform:none;">
                        ⚡ From today, everything happens in one place:
                      </h3>
                    </td>
                  </tr>
                </table>
              </div>

              <!-- 5 Feature Cards -->
              <!-- Feature 1: Unified Inbox -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td class="feature-box" style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="42" valign="top" style="padding-right:14px;">
                          <div style="width:40px;height:40px;border-radius:10px;background:#ecfdf5;border:1px solid #a7f3d0;text-align:center;line-height:40px;font-size:20px;">
                            💬
                          </div>
                        </td>
                        <td valign="middle">
                          <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;">
                            All your conversations in a single inbox
                          </div>
                          <div style="font-size:13px;color:#64748b;margin-top:3px;line-height:1.45;">
                            WhatsApp, Instagram, Facebook, and Gmail synced seamlessly in real time.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Feature 2: Contact Organisation -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td class="feature-box" style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="42" valign="top" style="padding-right:14px;">
                          <div style="width:40px;height:40px;border-radius:10px;background:#eff6ff;border:1px solid #bfdbfe;text-align:center;line-height:40px;font-size:20px;">
                            👥
                          </div>
                        </td>
                        <td valign="middle">
                          <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;">
                            Leads and contacts organised automatically
                          </div>
                          <div style="font-size:13px;color:#64748b;margin-top:3px;line-height:1.45;">
                            Auto-capturing, smart tagging, customer profiles, and team routing.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Feature 3: AI Replies -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td class="feature-box" style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="42" valign="top" style="padding-right:14px;">
                          <div style="width:40px;height:40px;border-radius:10px;background:#faf5ff;border:1px solid #e9d5ff;text-align:center;line-height:40px;font-size:20px;">
                            🤖
                          </div>
                        </td>
                        <td valign="middle">
                          <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;">
                            AI replies that answer customers even when you're busy
                          </div>
                          <div style="font-size:13px;color:#64748b;margin-top:3px;line-height:1.45;">
                            Intelligent 24/7 AI assistants that answer questions and qualify prospective buyers.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Feature 4: Quotations & Payments -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td class="feature-box" style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="42" valign="top" style="padding-right:14px;">
                          <div style="width:40px;height:40px;border-radius:10px;background:#fefce8;border:1px solid #fef08a;text-align:center;line-height:40px;font-size:20px;">
                            📄
                          </div>
                        </td>
                        <td valign="middle">
                          <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;">
                            Quotations, payment links, and invoices in one smooth flow
                          </div>
                          <div style="font-size:13px;color:#64748b;margin-top:3px;line-height:1.45;">
                            Generate professional sales documents and collect payments directly inside chat.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Feature 5: Performance Dashboard -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:24px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td class="feature-box" style="padding:16px 18px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="42" valign="top" style="padding-right:14px;">
                          <div style="width:40px;height:40px;border-radius:10px;background:#fdf2f8;border:1px solid #fbcfe8;text-align:center;line-height:40px;font-size:20px;">
                            📊
                          </div>
                        </td>
                        <td valign="middle">
                          <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.35;">
                            One dashboard to see how everything's performing
                          </div>
                          <div style="font-size:13px;color:#64748b;margin-top:3px;line-height:1.45;">
                            Real-time metrics, response analytics, campaign ROI, and team performance.
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Transition Copy -->
              <p style="margin:20px 0 10px;font-size:15px;line-height:1.7;color:#334155;">
                You focus on growing your business — we'll handle the repetitive work.
              </p>

              <p style="margin:0 0 28px;font-size:16px;font-weight:600;line-height:1.6;color:#047857;">
                Welcome aboard, and enjoy the calm. ✨
              </p>

              <!-- Primary CTA Buttons (Web Dashboard & Mobile App) -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:28px 0 24px;">
                <tr>
                  <td align="center">
                    <!-- Web Dashboard Button -->
                    <table role="presentation" cellspacing="0" cellpadding="0" style="display:inline-table;margin:6px 6px;">
                      <tr>
                        <td align="center" style="border-radius:12px;background:linear-gradient(135deg, #10b981 0%, #059669 100%);box-shadow:0 6px 18px rgba(16,185,129,0.35);">
                          <a href="{login_url}" class="cta-button" style="display:inline-block;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 30px;letter-spacing:0.3px;text-align:center;" target="_blank">
                            🌐 Go to Web Dashboard &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>
                    
                    <!-- Mobile App Button -->
                    <table role="presentation" cellspacing="0" cellpadding="0" style="display:inline-table;margin:6px 6px;">
                      <tr>
                        <td align="center" style="border-radius:12px;background:#0f172a;box-shadow:0 6px 18px rgba(15,23,42,0.22);">
                          <a href="{app_url}" class="cta-button" style="display:inline-block;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 30px;letter-spacing:0.3px;text-align:center;" target="_blank">
                            📱 Download Mobile App &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:12px;">
                    <span style="font-size:12px;color:#64748b;">
                      Available on Web Browser &bull; Android (Google Play) &bull; iOS
                    </span>
                  </td>
                </tr>
              </table>

              <!-- Tagline & Team Signature Highlight Box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:26px 0 8px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td style="padding:18px 24px;text-align:center;">
                    <div style="font-size:16px;font-weight:800;color:#047857;letter-spacing:0.2px;margin-bottom:6px;">
                      Connect everything. Automate anything.
                    </div>
                    <div style="font-size:14px;font-weight:700;color:#059669;">
                      — Team UWO Connect
                    </div>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8fafc;padding:28px 36px 32px;border-top:1px solid #e2e8f0;text-align:center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <div style="font-size:14px;font-weight:800;color:#0f172a;letter-spacing:-0.3px;margin-bottom:4px;">
                      UWO <span style="color:#059669;">Connect</span>
                    </div>
                    <div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:14px;">
                      Unified Communication &amp; Business Automation Platform
                    </div>

                    <!-- Quick Support Links -->
                    <div style="font-size:12px;color:#94a3b8;line-height:1.6;margin-bottom:14px;">
                      Questions or need onboarding assistance? Reach our team at<br>
                      <a href="mailto:{support_email}" style="color:#059669;font-weight:700;text-decoration:none;">{support_email}</a>
                      &nbsp;&bull;&nbsp;
                      <a href="{login_url}" style="color:#059669;font-weight:600;text-decoration:none;">Web Dashboard</a>
                      &nbsp;&bull;&nbsp;
                      <a href="{app_url}" style="color:#059669;font-weight:600;text-decoration:none;">Mobile App</a>
                    </div>

                    <div style="font-size:11px;color:#94a3b8;line-height:1.5;border-top:1px solid #f1f5f9;padding-top:14px;margin-top:10px;">
                      &copy; 2026 UWO Connect. All rights reserved.
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
        <!--[if (gte mso 9)|(IE)]>
        </td>
        </tr>
        </table>
        <![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""

    @classmethod
    def send_welcome_email(cls, user, login_url=None, app_url=None, temp_password=None, force=False):
        """
        Asynchronously sends the branded welcome email to the newly registered user.
        Includes deduplication guard to ensure email is dispatched only once per user (unless force=True).
        Executed non-blocking in a background daemon thread. Returns the dispatched thread.
        """
        if not user or not getattr(user, 'email', None):
            return None

        recipient_email = str(user.email).lower().strip()
        if not recipient_email or "@" not in recipient_email:
            return None

        # Deduplication check: Do not resend if already marked sent (unless forced)
        if not force and getattr(user, 'welcome_email_sent', False):
            logger.info(f"[WelcomeEmail] Skipped duplicate dispatch for user: {recipient_email}")
            return None

        # Atomic/In-memory update of the flag to prevent race conditions
        if hasattr(user, 'welcome_email_sent'):
            user.welcome_email_sent = True
            if hasattr(user, 'save') and hasattr(user, 'pk') and user.pk:
                try:
                    user.save(update_fields=['welcome_email_sent'])
                except Exception as e:
                    logger.warning(f"[WelcomeEmail] Note: Could not update welcome_email_sent field: {e}")

        name = getattr(user, 'first_name', '') or getattr(user, 'username', '') or 'there'
        login_url = login_url or DEFAULT_WEB_URL
        app_url = app_url or DEFAULT_APP_URL

        def _dispatch():
            try:
                subject = "Welcome to UWO Connect! 🎉"
                
                # High-fidelity plain text alternative
                plain_text = (
                    f"Welcome to UWO Connect! 🎉\n\n"
                    f"Hi {name},\n\n"
                    f"Take a deep breath — the days of juggling five different apps are officially over.\n\n"
                    f"No more switching between WhatsApp, Instagram, Facebook, Gmail, Excel sheets, and a separate CRM. "
                    f"No more missed enquiries. No more “Who replied to this customer?” confusion.\n\n"
                    f"From today, everything happens in one place:\n"
                    f"💬 All your conversations in a single inbox\n"
                    f"👥 Leads and contacts organised automatically\n"
                    f"🤖 AI replies that answer customers even when you're busy\n"
                    f"📄 Quotations, payment links, and invoices in one smooth flow\n"
                    f"📊 One dashboard to see how everything's performing\n\n"
                    f"You focus on growing your business — we'll handle the repetitive work.\n\n"
                    f"Welcome aboard, and enjoy the calm. ✨\n\n"
                    f"{'Temporary Password: ' + temp_password + chr(10) + 'Please change your password after initial sign-in.' + chr(10) + chr(10) if temp_password else ''}"
                    f"🌐 Web Dashboard: {login_url}\n"
                    f"📱 Mobile App: {app_url}\n\n"
                    f"Connect everything. Automate anything.\n"
                    f"— Team UWO Connect\n\n"
                    f"Questions? Email us at {DEFAULT_SUPPORT_EMAIL}"
                )

                html_content = cls._build_html_template(
                    name,
                    login_url=login_url,
                    app_url=app_url,
                    support_email=DEFAULT_SUPPORT_EMAIL,
                    temp_password=temp_password
                )

                from_email = (
                    f"UWO Connect <{settings.EMAIL_HOST_USER}>"
                    if getattr(settings, 'EMAIL_HOST_USER', None)
                    else f"UWO Connect <{DEFAULT_SUPPORT_EMAIL}>"
                )

                send_mail(
                    subject=subject,
                    message=plain_text,
                    from_email=from_email,
                    recipient_list=[recipient_email],
                    html_message=html_content,
                    fail_silently=False
                )
                backend_type = "SMTP" if getattr(settings, 'EMAIL_HOST_USER', None) else "Console/Fallback"
                logger.info(f"[WelcomeEmail] Dispatched successfully via {backend_type} to {recipient_email}")
                print(f"\n[WelcomeEmail] Dispatched welcome email via {backend_type} to {recipient_email}\n")
            except Exception as exc:
                logger.warning(f"[WelcomeEmail] Could not send welcome email to {recipient_email}: {exc}")
                print(f"\n[WelcomeEmail ERROR] Could not send welcome email to {recipient_email}: {exc}\n")

        thread = threading.Thread(target=_dispatch, daemon=True)
        thread.start()
        return thread

    @classmethod
    def broadcast_to_all_users(cls, force=True):
        """
        Sends the welcome email to all active users in the system.
        Waits for all email dispatch threads to complete and returns delivery summary.
        """
        from api.models import User
        users = list(User.objects.filter(is_active=True))
        threads = []
        recipients = []

        logger.info(f"[WelcomeEmail] Broadcasting welcome email to {len(users)} users...")
        for user in users:
            if not getattr(user, 'email', None):
                continue
            recipients.append((user.email, getattr(user, 'first_name', '') or user.username))
            t = cls.send_welcome_email(user, force=force)
            if t:
                threads.append(t)

        for t in threads:
            t.join(timeout=15)

        logger.info(f"[WelcomeEmail] Broadcast complete. Total users targeted: {len(recipients)}")
        return recipients


