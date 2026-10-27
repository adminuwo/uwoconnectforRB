import unittest
from unittest.mock import MagicMock, patch

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'rest_framework',
            'api',
        ],
        ROOT_URLCONF='api.urls',
        SECRET_KEY='test-secret-key-12345',
        MIDDLEWARE=[],
    )
    django.setup()

from rest_framework.test import APIRequestFactory
from api.models import EmailAutomationLog
from api.serializers import EmailAutomationSettingsSerializer, EmailAutomationLogSerializer
from api.views.email_center_views import EmailAutomationSettingsViewSet

class TestAutomationAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.mock_user = MagicMock()
        self.mock_user.is_authenticated = True
        self.mock_user.id = 1

        self.mock_client = MagicMock()
        self.mock_client.id = 1
        self.mock_client.pk = 1
        self.mock_user.client = self.mock_client

    def test_settings_serializer_validation(self):
        payload = {
            "is_enabled": True,
            "auto_reply_business_inquiry": True,
            "auto_reply_customer_support": True,
            "auto_reply_advertisement": False,
            "auto_reply_newsletter": False,
            "auto_reply_promotion": False,
            "auto_reply_notification": False,
            "excluded_domains": ["spam.com", "ads.org"],
            "excluded_senders": ["bot@marketing.com"],
            "allowlist_mode": False,
            "uncertain_fallback": "require_review"
        }
        serializer = EmailAutomationSettingsSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), f"Serializer errors: {serializer.errors}")
        data = serializer.validated_data
        self.assertEqual(data["uncertain_fallback"], "require_review")
        self.assertEqual(len(data["excluded_domains"]), 2)
        print("✔ API Test 1 Passed: Settings serializer successfully validates and cleans input payload.")

    def test_log_serializer_fields(self):
        log = EmailAutomationLog(
            client_id=1,
            mailbox="gmail",
            idempotency_key="key_123",
            sender_email="buyer@acme.com",
            sender_name="Buyer",
            subject="RFQ Inquiry",
            category="business_inquiry",
            confidence_score=0.95,
            decision="replied",
            reason="Customer inquiry classified with high confidence",
            reply_status="sent"
        )
        log._state.fields_cache['client'] = self.mock_client
        serializer = EmailAutomationLogSerializer(log)
        data = serializer.data
        self.assertEqual(data["sender_email"], "buyer@acme.com")
        self.assertEqual(data["decision"], "replied")
        self.assertEqual(data["category"], "business_inquiry")
        print("✔ API Test 2 Passed: Automation Log serializer includes all audit fields.")

    @patch('api.models.EmailAccount.objects.filter')
    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    def test_settings_viewset_current_get(self, mock_get_settings, mock_acc_filter):
        mock_acc_filter.return_value.first.return_value = None

        mock_obj = MagicMock()
        mock_obj.is_enabled = True
        mock_obj.auto_reply_business_inquiry = True
        mock_obj.auto_reply_customer_support = True
        mock_obj.auto_reply_sales_inquiry = True
        mock_obj.auto_reply_advertisement = False
        mock_obj.auto_reply_newsletter = False
        mock_obj.auto_reply_promotion = False
        mock_obj.auto_reply_notification = False
        mock_obj.auto_reply_spam = False
        mock_obj.allowed_senders = []
        mock_obj.excluded_senders = []
        mock_obj.allowed_domains = []
        mock_obj.excluded_domains = []
        mock_obj.include_keywords = []
        mock_obj.exclude_keywords = []
        mock_obj.allowlist_mode = False
        mock_obj.uncertain_fallback = 'skip'
        mock_obj.reply_to_threads = True

        mock_get_settings.return_value = mock_obj

        view = EmailAutomationSettingsViewSet.as_view({'get': 'current'})
        request = self.factory.get('/api/email/automation-settings/current/?account_id=gmail')
        request.user = self.mock_user

        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_enabled"])
        self.assertFalse(response.data["auto_reply_advertisement"])
        print("✔ API Test 3 Passed: Settings current endpoint retrieves mailbox policy.")

if __name__ == '__main__':
    unittest.main()
