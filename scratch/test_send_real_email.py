import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.conf import settings
from django.core.mail import send_mail
from api.services.welcome_email_service import WelcomeEmailService

def test_email(target_email):
    print("=" * 65)
    print("📧 UWO-CONNECT EMAIL CONFIGURATION & DISPATCH DIAGNOSTIC")
    print("=" * 65)
    print(f"EMAIL_BACKEND       : {settings.EMAIL_BACKEND}")
    print(f"EMAIL_HOST          : {settings.EMAIL_HOST}")
    print(f"EMAIL_PORT          : {settings.EMAIL_PORT}")
    print(f"EMAIL_USE_TLS       : {settings.EMAIL_USE_TLS}")
    print(f"EMAIL_HOST_USER     : {settings.EMAIL_HOST_USER or '[EMPTY / NOT CONFIGURED]'}")
    print(f"DEFAULT_FROM_EMAIL  : {settings.DEFAULT_FROM_EMAIL}")
    print("-" * 65)

    if not settings.EMAIL_HOST_USER:
        print("⚠️  WARNING: EMAIL_HOST_USER is empty!")
        print("   Django is running in Console mode.")
        print("   Emails will only be printed to the terminal console,")
        print("   and will NOT reach the recipient's actual inbox.")
        print("   Please configure EMAIL_HOST_USER & EMAIL_HOST_PASSWORD in UWO-CONNECT_B/.env")
    else:
        print(f"✅ EMAIL_HOST_USER configured ({settings.EMAIL_HOST_USER}).")
        print(f"   Connecting via SMTP to deliver email to {target_email}...")

    class DummyUser:
        first_name = "Guru"
        username = "gurumukh"
        email = target_email

    import time
    WelcomeEmailService.send_welcome_email(DummyUser(), login_url="https://app.uwoconnect.com")
    time.sleep(1)
    print("\n[INFO] WelcomeEmailService.send_welcome_email completed.")
    print("=" * 65)

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else "test@example.com"
    test_email(target)
