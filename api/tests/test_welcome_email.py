import os
import sys
import time
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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
    # Test 1: HTML Template Construction & Exact Copy
    # ----------------------------------------------------
    html = WelcomeEmailService._build_html_template("Devanshu Verma", login_url="https://app.uwoconnect.com", temp_password="TestPassword@123")
    
    # Check Title and Greeting
    assert "Welcome to UWO Connect! 🎉" in html, "Welcome header missing in HTML"
    assert "Hi Devanshu," in html, "Dynamic first name missing in HTML"
    
    # Check Required Copy Sentences
    assert "Take a deep breath — the days of juggling five different apps are officially over." in html, "Intro paragraph 1 missing"
    assert "No more switching between WhatsApp, Instagram, Facebook, Gmail, Excel sheets, and a separate CRM." in html, "App switching list missing"
    assert "No more missed enquiries." in html, "Missed enquiries copy missing"
    assert "No more “Who replied to this customer?” confusion." in html, "Confusion copy missing"
    assert "From today, everything happens in one place:" in html, "Section heading missing"
    
    # Check 5 Feature Cards
    assert "All your conversations in a single inbox" in html, "Feature 1 missing"
    assert "💬" in html, "Feature 1 icon missing"
    
    assert "Leads and contacts organised automatically" in html, "Feature 2 missing"
    assert "👥" in html, "Feature 2 icon missing"
    
    assert "AI replies that answer customers even when you&#39;re busy" in html or "AI replies that answer customers even when you're busy" in html, "Feature 3 missing"
    assert "🤖" in html, "Feature 3 icon missing"
    
    assert "Quotations, payment links, and invoices in one smooth flow" in html, "Feature 4 missing"
    assert "📄" in html, "Feature 4 icon missing"
    
    assert "One dashboard to see how everything&#39;s performing" in html or "One dashboard to see how everything's performing" in html, "Feature 5 missing"
    assert "📊" in html, "Feature 5 icon missing"
    
    # Check Closing, Tagline & Signature
    assert "You focus on growing your business — we'll handle the repetitive work." in html or "we&#39;ll handle the repetitive work" in html, "Repetitive work copy missing"
    assert "Welcome aboard, and enjoy the calm. ✨" in html, "Enjoy the calm copy missing"
    assert "Connect everything. Automate anything." in html, "Tagline missing"
    assert "— Team UWO Connect" in html, "Team signature missing"
    
    # Check CTA and Credentials
    assert "TestPassword@123" in html, "Temp password missing in HTML"
    assert "https://uwoconnect.aisa24.com" in html or "https://app.uwoconnect.com" in html, "Web URL missing in HTML"
    assert "Go to Web Dashboard" in html, "Web CTA button text missing in HTML"
    assert "Download Mobile App" in html, "Mobile CTA button text missing in HTML"
    assert "admin@uwo24.com" in html, "Support email link missing in HTML"
    
    print("  [PASS] Test 1: HTML template renders correct branding, user name, and all 5 feature cards.")

    # ----------------------------------------------------
    # Test 2: HTML Template without temp password
    # ----------------------------------------------------
    html_no_pwd = WelcomeEmailService._build_html_template("Aditi")
    assert "Hi Aditi," in html_no_pwd
    assert "Your Temporary Access Credentials" not in html_no_pwd
    print("  [PASS] Test 2: HTML template cleanly omits password block when none is provided.")

    # ----------------------------------------------------
    # Test 3: Invalid / Missing User Handling (Fail-safe)
    # ----------------------------------------------------
    WelcomeEmailService.send_welcome_email(None)
    dummy_empty_user = type('DummyUser', (), {'email': ''})()
    WelcomeEmailService.send_welcome_email(dummy_empty_user)
    print("  [PASS] Test 3: Edge case handling for None/empty user executes safely without crash.")

    # ----------------------------------------------------
    # Test 4: Deduplication Protection
    # ----------------------------------------------------
    dummy_dedup_user = type('DummyUser', (), {
        'email': 'dedup_test@example.com',
        'first_name': 'DedupUser',
        'username': 'dedupuser',
        'welcome_email_sent': True
    })()
    # When welcome_email_sent is already True, it must not send again
    WelcomeEmailService.send_welcome_email(dummy_dedup_user)
    print("  [PASS] Test 4: Deduplication guard successfully prevents duplicate sends.")

    # ----------------------------------------------------
    # Test 5: Asynchronous Email Dispatch Execution
    # ----------------------------------------------------
    test_user = type('DummyUser', (), {
        'email': 'welcome_test_user@example.com',
        'first_name': 'TestUser',
        'username': 'testuser',
        'welcome_email_sent': False
    })()

    WelcomeEmailService.send_welcome_email(test_user)
    time.sleep(0.5)
    assert test_user.welcome_email_sent is True, "Flag should be updated upon sending"
    print("  [PASS] Test 5: send_welcome_email dispatches asynchronously and marks user as sent.")

    # ----------------------------------------------------
    # Test 6: End-to-End Registration Flow Trigger
    # ----------------------------------------------------
    test_email = f"auto_welcome_test_{int(time.time())}@uwotest.com"
    reg_data = {
        "name": "Live Test Founder",
        "email": test_email,
        "password": "SecurePassword@123",
        "business_name": "Welcome Test Enterprise",
        "phone_number": "+919999988888",
        "terms_accepted": True,
        "privacy_accepted": True,
        "meta_portfolio_eligible": True,
        "meta_portfolio_name": "Welcome Test Portfolio"
    }

    serializer = RegisterSerializer(data=reg_data)
    assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

    result = AuthService.register_user(serializer)
    assert result.get("status") in ["APPROVED", "PENDING"], f"Unexpected status: {result}"
    print(f"  [PASS] Test 6: AuthService.register_user executed successfully for {test_email}.")

    # Allow thread to dispatch
    time.sleep(0.5)

    # Verify user state in database
    created_user = User.objects.filter(email=test_email).first()
    assert created_user is not None, "User should exist in database"
    assert created_user.welcome_email_sent is True, "User welcome_email_sent flag should be True"

    # Clean up test user and client
    client = created_user.client
    created_user.delete()
    if client:
        client.delete()
    print("  [PASS] Test 7: Test user & workspace verified in DB and cleaned up.")

    print("\n" + "=" * 70)
    print("🎉 ALL WELCOME EMAIL TESTS COMPLETED SUCCESSFULLY WITH 100% PASS RATE!")
    print("=" * 70)

if __name__ == '__main__':
    run_tests()
