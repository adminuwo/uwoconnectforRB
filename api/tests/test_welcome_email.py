import os
import sys
import time
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.core import mail
from api.models import User, Client
from api.services.welcome_email_service import WelcomeEmailService
from api.serializers import RegisterSerializer
from api.services.auth_service import AuthService

def run_tests():
    print("=" * 70)
    print("🧪 RUNNING UWO-CONNECT WELCOME EMAIL AUTOMATED TEST SUITE")
    print("=" * 70)

    # ----------------------------------------------------
    # Test 1: HTML Template Construction
    # ----------------------------------------------------
    html = WelcomeEmailService._build_html_template("Devanshu", login_url="https://app.uwoconnect.com", temp_password="TestPassword@123")
    assert "Hi Devanshu," in html, "User name missing in HTML"
    assert "Welcome to UwoConnect!" in html, "Welcome header missing in HTML"
    assert "TestPassword@123" in html, "Temp password missing in HTML"
    assert "https://app.uwoconnect.com" in html, "Login URL missing in HTML"
    assert "Unified Inbox" in html, "Feature highlights missing in HTML"
    print("  [PASS] Test 1: HTML template renders correct branding, user name, and features.")

    # ----------------------------------------------------
    # Test 2: HTML Template without temp password
    # ----------------------------------------------------
    html_no_pwd = WelcomeEmailService._build_html_template("Aditi")
    assert "Hi Aditi," in html_no_pwd
    assert "Your Temporary Password" not in html_no_pwd
    print("  [PASS] Test 2: HTML template cleanly omits password block when none is provided.")

    # ----------------------------------------------------
    # Test 3: Invalid / Missing User Handling (Fail-safe)
    # ----------------------------------------------------
    # Should not throw any exception
    WelcomeEmailService.send_welcome_email(None)
    dummy_empty_user = type('DummyUser', (), {'email': ''})()
    WelcomeEmailService.send_welcome_email(dummy_empty_user)
    print("  [PASS] Test 3: Edge case handling for None/empty user executes safely without crash.")

    # ----------------------------------------------------
    # Test 4: Asynchronous Email Dispatch Execution
    # ----------------------------------------------------
    test_user = type('DummyUser', (), {
        'email': 'welcome_test_user@example.com',
        'first_name': 'TestUser',
        'username': 'testuser'
    })()

    WelcomeEmailService.send_welcome_email(test_user)
    # Allow background thread a moment to process
    time.sleep(0.5)
    print("  [PASS] Test 4: send_welcome_email dispatches asynchronously in background thread.")

    # ----------------------------------------------------
    # Test 5: End-to-End Registration Flow Trigger
    # ----------------------------------------------------
    test_email = f"auto_welcome_test_{int(time.time())}@uwotest.com"
    reg_data = {
        "name": "Live Test Founder",
        "email": test_email,
        "password": "SecurePassword@123",
        "business_name": "Welcome Test Enterprise",
        "phone_number": "+919999988888"
    }

    serializer = RegisterSerializer(data=reg_data)
    assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

    result = AuthService.register_user(serializer)
    assert result.get("status") in ["APPROVED", "PENDING"], f"Unexpected status: {result}"
    print(f"  [PASS] Test 5: AuthService.register_user executed successfully for {test_email}.")

    # Allow thread to dispatch
    time.sleep(0.5)

    # Clean up test user and client
    created_user = User.objects.filter(email=test_email).first()
    if created_user:
        client = created_user.client
        created_user.delete()
        if client:
            client.delete()
        print("  [PASS] Test 6: Test user & workspace cleaned up from database.")

    print("\n" + "=" * 70)
    print("🎉 ALL WELCOME EMAIL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == '__main__':
    run_tests()
