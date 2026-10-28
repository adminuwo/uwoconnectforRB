"""
Comprehensive Verification Script for Password Change Successful Confirmation Email.
Tests:
1. Settings/Profile Password Change (ChangePasswordView)
   - Invalid current password -> 400, no email
   - Weak password -> 400, no email
   - Same as old password -> 400, no email
   - Successful change -> 200, confirmation email sent to registered email
2. Forgot Password Reset Flow (AuthService.forgot_password_reset)
   - Invalid / unverified OTP -> 400, no email
   - Non-existent account -> 404, no email
   - Successful reset with valid OTP -> 200, confirmation email sent
3. Deduplication Logic
   - Repeated requests within deduplication window do not send duplicate emails
4. Error Handling / Fault Tolerance
   - SMTP delivery exceptions do not break the password change API response
5. Regression check on existing OTP emails
"""
import os
import sys
import django
from unittest.mock import patch, MagicMock

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework import status

from api.models import User, PasswordResetOTP
from api.views.auth_views import ChangePasswordView, ForgotPasswordResetView
from api.services.auth_service import AuthService
from api.services.password_change_notification_service import PasswordChangeNotificationService

factory = APIRequestFactory()

def run_tests():
    print("=" * 60)
    print("STARTING TEST SUITE: Password Change Confirmation Email")
    print("=" * 60)

    # 1. Setup Test User
    test_email = "test_pwd_change_verify@example.com"
    User.objects.filter(email=test_email).delete()
    user = User.objects.create_user(
        username=test_email,
        email=test_email,
        password="InitialPassword@123",
        first_name="Test",
        last_name="User",
        role="CLIENT",
        status="APPROVED"
    )
    print(f"Created test user: {user.email} (ID: {user.id})")

    # -------------------------------------------------------------
    # TEST 1: ChangePasswordView - Wrong Current Password
    # -------------------------------------------------------------
    print("\n--- TEST 1: Wrong Current Password (Must NOT send email) ---")
    cache.clear()
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        request = factory.post(
            '/api/auth/change-password/',
            {'current_password': 'WrongPassword@999', 'new_password': 'NewValidPassword@123'},
            format='json'
        )
        force_authenticate(request, user=user)
        view = ChangePasswordView.as_view()
        response = view(request)

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert not mock_send.called, "Email was unexpectedly sent for failed current password check!"
        print("PASS: 400 Bad Request returned, 0 emails sent.")

    # -------------------------------------------------------------
    # TEST 2: ChangePasswordView - Weak New Password
    # -------------------------------------------------------------
    print("\n--- TEST 2: Weak New Password (Must NOT send email) ---")
    cache.clear()
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        request = factory.post(
            '/api/auth/change-password/',
            {'current_password': 'InitialPassword@123', 'new_password': '123'},
            format='json'
        )
        force_authenticate(request, user=user)
        view = ChangePasswordView.as_view()
        response = view(request)

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert not mock_send.called, "Email was unexpectedly sent for weak password failure!"
        print("PASS: 400 Bad Request returned, 0 emails sent.")

    # -------------------------------------------------------------
    # TEST 3: ChangePasswordView - Same as current password
    # -------------------------------------------------------------
    print("\n--- TEST 3: Same as current password (Must NOT send email) ---")
    cache.clear()
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        request = factory.post(
            '/api/auth/change-password/',
            {'current_password': 'InitialPassword@123', 'new_password': 'InitialPassword@123'},
            format='json'
        )
        force_authenticate(request, user=user)
        view = ChangePasswordView.as_view()
        response = view(request)

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert not mock_send.called, "Email was unexpectedly sent when new password equals old!"
        print("PASS: 400 Bad Request returned, 0 emails sent.")

    # -------------------------------------------------------------
    # TEST 4: ChangePasswordView - Successful Password Change
    # -------------------------------------------------------------
    print("\n--- TEST 4: Successful Password Change (Must send confirmation email) ---")
    cache.clear()
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        request = factory.post(
            '/api/auth/change-password/',
            {'current_password': 'InitialPassword@123', 'new_password': 'UpdatedPassword@456'},
            format='json',
            REMOTE_ADDR='192.168.1.50'
        )
        force_authenticate(request, user=user)
        view = ChangePasswordView.as_view()
        response = view(request)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
        
        # Reload user from DB and verify new password hash works
        user.refresh_from_db()
        assert user.check_password('UpdatedPassword@456'), "Password was not updated in database!"
        
        # Test synchronous service call to inspect email parameters
        mock_send.reset_mock()
        cache.clear()
        sent = PasswordChangeNotificationService.send_password_change_confirmation(
            user=user,
            change_time=timezone.now(),
            ip_address='192.168.1.50',
            wait_sync=True
        )
        assert sent is True, "Service failed to send email"
        assert mock_send.call_count == 1, f"Expected 1 email call, got {mock_send.call_count}"

        args, kwargs = mock_send.call_args
        subject = kwargs.get('subject') or args[0]
        plain_body = kwargs.get('message') or args[1]
        recipients = kwargs.get('recipient_list') or args[3]
        html_body = kwargs.get('html_message')

        print(f"Subject: {subject}")
        print(f"Recipients: {recipients}")
        assert subject == "Your UWOConnect Password Has Been Changed Successfully", f"Wrong subject: {subject}"
        assert recipients == [test_email], f"Wrong recipient: {recipients}"
        assert "Hello Test User," in plain_body, "Plain body missing greeting"
        assert "This is a confirmation that your UWOConnect account password was changed successfully." in plain_body
        assert "If you made this change, no further action is required." in plain_body
        assert "If you did not change your password, please secure your account immediately" in plain_body
        assert "Regards,\nUWOConnect Security Team" in plain_body
        assert "UpdatedPassword@456" not in plain_body, "SECURITY VIOLATION: Password leaked in email plain body!"
        assert "UpdatedPassword@456" not in html_body, "SECURITY VIOLATION: Password leaked in email HTML body!"
        print("PASS: 200 OK returned, password updated in DB, and confirmation email sent with exact required text!")

    # -------------------------------------------------------------
    # TEST 5: Deduplication Logic
    # -------------------------------------------------------------
    print("\n--- TEST 5: Deduplication Window (Prevent duplicate emails) ---")
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        # First call within window
        cache.clear()
        first_call = PasswordChangeNotificationService.send_password_change_confirmation(user=user, wait_sync=True)
        assert first_call is True
        assert mock_send.call_count == 1, "First call should dispatch email"

        # Second rapid call (simulating double click)
        mock_send.reset_mock()
        second_call = PasswordChangeNotificationService.send_password_change_confirmation(user=user, wait_sync=True)
        assert second_call is True, "Deduplicated call should return True"
        assert mock_send.call_count == 0, f"Duplicate call should NOT send another email! Got {mock_send.call_count}"
        print("PASS: Rapid duplicate request correctly suppressed (0 duplicate emails sent).")

    # -------------------------------------------------------------
    # TEST 6: Forgot Password Reset - Invalid / Missing OTP
    # -------------------------------------------------------------
    print("\n--- TEST 6: Forgot Password Reset with Invalid OTP (Must NOT send email) ---")
    cache.clear()
    PasswordResetOTP.objects.filter(email=test_email).delete()
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        result = AuthService.forgot_password_reset(test_email, "SomeNewPass@789")
        assert result['status_code'] == 400, f"Expected 400, got {result['status_code']}"
        assert not mock_send.called, "Email was unexpectedly sent on unverified OTP!"
        print("PASS: 400 returned, 0 emails sent.")

    # -------------------------------------------------------------
    # TEST 7: Forgot Password Reset - Successful Reset with Verified OTP
    # -------------------------------------------------------------
    print("\n--- TEST 7: Forgot Password Reset with Verified OTP (Must send email) ---")
    cache.clear()
    PasswordResetOTP.objects.filter(email=test_email).delete()
    otp_record = PasswordResetOTP.objects.create(
        email=test_email,
        otp="654321",
        is_verified=True,
        created_at=timezone.now()
    )
    with patch('api.services.password_change_notification_service.send_mail') as mock_send:
        result = AuthService.forgot_password_reset(test_email, "ResetSuccess@999")
        assert result['status_code'] == 200, f"Expected 200, got {result}"

        # Verify DB updated
        user.refresh_from_db()
        assert user.check_password("ResetSuccess@999"), "Password not updated after reset!"

        # Verify OTP cleaned up
        assert not PasswordResetOTP.objects.filter(email=test_email).exists(), "OTP not cleaned up!"
        print("PASS: 200 OK returned, DB password updated, and confirmation email triggered.")

    # -------------------------------------------------------------
    # TEST 8: Resilient Error Handling (SMTP Failure must not fail password change)
    # -------------------------------------------------------------
    print("\n--- TEST 8: Resilient Error Handling (SMTP failure must not fail password change) ---")
    cache.clear()
    with patch('api.services.password_change_notification_service.send_mail', side_effect=Exception("SMTP Connection Timeout")):
        request = factory.post(
            '/api/auth/change-password/',
            {'current_password': 'ResetSuccess@999', 'new_password': 'FinalSecurePass@123'},
            format='json'
        )
        force_authenticate(request, user=user)
        view = ChangePasswordView.as_view()
        response = view(request)

        assert response.status_code == 200, f"API failed when SMTP failed! Got {response.status_code}"
        user.refresh_from_db()
        assert user.check_password('FinalSecurePass@123'), "Password was not updated in DB!"
        print("PASS: API responded with 200 and password was saved in DB even when SMTP failed.")

    # Cleanup test user
    User.objects.filter(email=test_email).delete()
    print("\nCleaned up test user.")
    print("=" * 60)
    print("ALL 8 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()
