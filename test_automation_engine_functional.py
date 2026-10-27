import os
import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'api',
        ],
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        SECRET_KEY='test-secret-key-12345',
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
        USE_TZ=True,
    )
    django.setup()

import unittest
from unittest.mock import MagicMock, patch
from api.services.email_classifier import EmailClassifier
from api.services import email_automation_engine


class MockModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, 'id'):
            self.id = "mock_id_1"

    def save(self):
        pass


class TestEmailAutomationEngineFunctional(unittest.TestCase):

    def setUp(self):
        self.mock_client = MockModel(
            id="client_123",
            name="Acme Corp",
            business_name="Acme Solutions",
            email="support@acme.com"
        )
        self.mock_account = MockModel(
            id="account_456",
            email_address="support@acme.com",
            display_name="Acme Support"
        )
        self.mock_rule = MockModel(
            id="rule_789",
            name="General Inquiry Auto-Responder",
            subject_pattern="",
            sender_pattern="",
            keyword_match="",
            reply_subject="Thanks for reaching out, {{first_name}}!",
            reply_body="Hi {{first_name}}, we got your email regarding {{company}} and will reply shortly.",
            is_active=True
        )
        self.mock_settings = MockModel(
            id="settings_001",
            client=self.mock_client,
            account=self.mock_account,
            is_enabled=True,
            allowed_senders=[],
            excluded_senders=['spammer@badsource.com'],
            allowed_domains=['trustedpartner.com'],
            excluded_domains=['marketingvendor.com'],
            auto_reply_business_inquiry=True,
            auto_reply_customer_support=True,
            auto_reply_sales_inquiry=True,
            auto_reply_advertisement=False,
            auto_reply_newsletter=False,
            auto_reply_promotion=False,
            auto_reply_notification=False,
            auto_reply_spam=False,
            include_keywords=[],
            exclude_keywords=['unsubscribe', 'blast'],
            allowlist_mode=False,
            uncertain_fallback='skip',
            reply_to_threads=True
        )
        self.logs_db = {}
        self.sent_emails = []

    def _mock_get_settings(self, client, account=None):
        return self.mock_settings

    def _mock_log_create(self, **kwargs):
        log_obj = MockModel(**kwargs)
        self.logs_db[kwargs['idempotency_key']] = log_obj
        return log_obj

    def _mock_send_gmail(self, client, to_email, body, subject):
        self.sent_emails.append({'to': to_email, 'subject': subject, 'body': body})

    def _mock_email_message_create(self, **kwargs):
        return MockModel(**kwargs)

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_01_legitimate_customer_inquiry_triggers_single_reply(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_email_msg_objects.create.side_effect = self._mock_email_message_create
        mock_send_gmail.side_effect = self._mock_send_gmail

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_legit_001",
            sender_email="alice@company.org",
            sender_name="Alice Wonder",
            subject="Pricing inquiry for 50 users",
            body_text="Hi team, we would like to know your enterprise pricing for 50 team members.",
            headers=[{'name': 'From', 'value': 'Alice Wonder <alice@company.org>'}],
            provider='gmail'
        )

        self.assertEqual(res['status'], 'replied')
        self.assertEqual(len(self.sent_emails), 1)
        self.assertEqual(self.sent_emails[0]['to'], 'alice@company.org')
        self.assertIn("Alice", self.sent_emails[0]['subject'])
        print("✔ Test 1 Passed: Legitimate customer inquiry sent exactly one automated reply.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_02_advertisement_is_skipped(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_send_gmail.side_effect = self._mock_send_gmail

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_ad_002",
            sender_email="outreach@coldleads.biz",
            sender_name="Bob Sales",
            subject="B2B leads and SEO services to boost your sales",
            body_text="Hi, I came across your website and we specialize in SEO services to boost your sales. Exclusive discount available.",
            headers=[],
            provider='gmail'
        )

        self.assertEqual(res['status'], 'skipped')
        self.assertEqual(len(self.sent_emails), 0)
        log = self.logs_db.get(f"{self.mock_client.id}:gmail:msg_ad_002")
        self.assertIsNotNone(log)
        self.assertEqual(log.decision, 'skipped')
        self.assertIn(log.category, ['advertisement', 'promotion'])
        print("✔ Test 2 Passed: Advertisement skipped without sending reply, logged accurately.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_03_newsletter_with_list_unsubscribe_skipped(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_send_gmail.side_effect = self._mock_send_gmail

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_news_003",
            sender_email="newsletter@cloudupdates.com",
            sender_name="Cloud Digest",
            subject="Monthly Cloud Architecture Newsletter",
            body_text="Check out new Kubernetes releases. To unsubscribe click here.",
            headers=[
                {'name': 'List-Unsubscribe', 'value': '<https://cloudupdates.com/unsub>'},
                {'name': 'Precedence', 'value': 'bulk'}
            ],
            provider='gmail'
        )

        self.assertEqual(res['status'], 'skipped')
        self.assertEqual(len(self.sent_emails), 0)
        log = self.logs_db.get(f"{self.mock_client.id}:gmail:msg_news_003")
        self.assertEqual(log.category, 'newsletter')
        self.assertEqual(log.decision, 'skipped')
        print("✔ Test 3 Passed: Newsletter with List-Unsubscribe skipped automatically.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_04_excluded_sender_and_domain(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_send_gmail.side_effect = self._mock_send_gmail

        # Excluded sender: spammer@badsource.com
        res1 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_excl_004",
            sender_email="spammer@badsource.com",
            sender_name="Spammer",
            subject="Hey there",
            body_text="Want to buy something?",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res1['status'], 'skipped')
        self.assertIn("excluded", res1['reason'])

        # Excluded domain: info@marketingvendor.com
        res2 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_excl_005",
            sender_email="info@marketingvendor.com",
            sender_name="Vendor Info",
            subject="Important business update",
            body_text="Check out our catalog",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res2['status'], 'skipped')
        self.assertIn("excluded", res2['reason'])
        self.assertEqual(len(self.sent_emails), 0)
        print("✔ Test 4 Passed: Excluded sender and excluded domain correctly skipped.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_05_master_toggle_disabled(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        disabled_settings = MockModel(**vars(self.mock_settings))
        disabled_settings.is_enabled = False
        mock_get_settings.return_value = disabled_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_disabled_006",
            sender_email="client@goodpartner.com",
            sender_name="Good Partner",
            subject="Need quotation",
            body_text="Please send me a quote.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res['status'], 'skipped')
        self.assertEqual(len(self.sent_emails), 0)
        print("✔ Test 5 Passed: Master toggle disabled skips all auto-replies.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_06_category_filters_enforced(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        custom_settings = MockModel(**vars(self.mock_settings))
        custom_settings.auto_reply_business_inquiry = False  # Disabled
        custom_settings.auto_reply_customer_support = True   # Enabled
        mock_get_settings.return_value = custom_settings
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_email_msg_objects.create.side_effect = self._mock_email_message_create
        mock_send_gmail.side_effect = self._mock_send_gmail

        # Business Inquiry should now be skipped
        res1 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_cat_007",
            sender_email="prospect@buyer.com",
            subject="Interested in your service",
            body_text="Hi, I am interested in your pricing proposal.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res1['status'], 'skipped')

        # Customer Support should be replied
        res2 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_cat_008",
            sender_email="user@trouble.com",
            sender_name="Stuck User",
            subject="Urgent help: cannot login to dashboard error",
            body_text="Please help, seeing error during login.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res2['status'], 'replied')
        print("✔ Test 6 Passed: Selective category toggles correctly enforced.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_07_duplicate_webhook_events_idempotency(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_email_msg_objects.create.side_effect = self._mock_email_message_create
        mock_send_gmail.side_effect = self._mock_send_gmail

        # First call: not existing yet
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create

        res1 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_dup_009",
            sender_email="clara@partner.com",
            sender_name="Clara",
            subject="Need quotation for product demo",
            body_text="Please quote us for demo.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res1['status'], 'replied')
        self.assertEqual(len(self.sent_emails), 1)

        # Second call with SAME provider_message_id (repeated webhook / sync retry)
        existing = self.logs_db[f"{self.mock_client.id}:gmail:msg_dup_009"]
        mock_log_objects.filter.return_value.first.return_value = existing

        res2 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_dup_009",
            sender_email="clara@partner.com",
            sender_name="Clara",
            subject="Need quotation for product demo",
            body_text="Please quote us for demo.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res2['status'], 'skipped')
        self.assertIn("Duplicate", res2['reason'])
        self.assertEqual(len(self.sent_emails), 1)  # Still exactly 1! No second reply sent!
        print("✔ Test 7 Passed: Duplicate webhook/event prevented; exactly 1 reply sent.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_08_concurrent_worker_overlap_idempotency(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]

        # Simulate Worker 1 already marked state as 'processing'
        in_flight_log = MockModel(
            decision='processing',
            idempotency_key=f"{self.mock_client.id}:gmail:msg_concurrent_010"
        )
        mock_log_objects.filter.return_value.first.return_value = in_flight_log

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_concurrent_010",
            sender_email="dave@client.com",
            subject="Inquiry demo",
            body_text="Need demo info",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res['status'], 'skipped')
        self.assertEqual(len(self.sent_emails), 0)
        print("✔ Test 8 Passed: Overlapping concurrent worker blocked by in-flight lock.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_09_temporary_failure_handled_safely(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        mock_send_gmail.side_effect = Exception("API Timeout 504 Gateway Timeout")

        res = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_fail_011",
            sender_email="elena@enterprise.com",
            sender_name="Elena",
            subject="Partnership inquiry proposal",
            body_text="Proposal attached for enterprise partnership.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res['status'], 'failed')
        log = self.logs_db.get(f"{self.mock_client.id}:gmail:msg_fail_011")
        self.assertEqual(log.decision, 'failed')
        self.assertIn("API Timeout", log.error_message)
        print("✔ Test 9 Passed: Provider API timeout recorded as failed state safely.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_10_new_message_in_existing_thread_handled(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        # A thread can have multiple message IDs (msg_thread_01, msg_thread_02)
        mock_get_settings.return_value = self.mock_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_email_msg_objects.create.side_effect = self._mock_email_message_create
        mock_send_gmail.side_effect = self._mock_send_gmail

        # First message in thread
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create
        res1 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_thread_part_1",
            sender_email="frank@org.com",
            sender_name="Frank",
            subject="Inquiry regarding licensing",
            body_text="Need licensing quote.",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res1['status'], 'replied')

        # Genuinely new follow-up message in same thread (new message ID)
        mock_log_objects.filter.return_value.first.return_value = None
        res2 = email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_thread_part_2",
            sender_email="frank@org.com",
            sender_name="Frank",
            subject="Re: Inquiry regarding licensing - additional questions",
            body_text="Also, does the pricing include 24/7 support?",
            headers=[],
            provider='gmail'
        )
        self.assertEqual(res2['status'], 'replied')
        self.assertEqual(len(self.sent_emails), 2)
        print("✔ Test 10 Passed: Genuinely new message in conversation handled according to rules.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_11_uncertain_classification_fallback(
        self, mock_send_gmail, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        review_settings = MockModel(**vars(self.mock_settings))
        review_settings.uncertain_fallback = 'require_review'
        mock_get_settings.return_value = review_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create

        # Ambiguous message with minimal text
        with patch.object(EmailClassifier, 'classify') as mock_classify:
            from api.services.email_classifier import ClassificationResult
            mock_classify.return_value = ClassificationResult(
                category='uncertain',
                confidence=0.35,
                is_unwanted=False,
                primary_reason="Borderline content"
            )

            res = email_automation_engine.process_incoming_email_automation(
                client=self.mock_client,
                account=self.mock_account,
                provider_message_id="msg_unc_012",
                sender_email="stranger@somewhere.com",
                subject="Hi",
                body_text="Hello",
                headers=[],
                provider='gmail'
            )
            self.assertEqual(res['status'], 'pending_review')
            log = self.logs_db.get(f"{self.mock_client.id}:gmail:msg_unc_012")
            self.assertEqual(log.decision, 'pending_review')
            self.assertEqual(len(self.sent_emails), 0)
        print("✔ Test 11 Passed: Uncertain classification safely routed to Pending Review.")

    @patch('api.services.email_automation_engine.get_or_create_client_settings')
    @patch('api.services.email_automation_engine.EmailAutomationLog.objects')
    @patch('api.services.email_automation_engine.EmailAutoReplyRule.objects')
    @patch('api.services.email_automation_engine.EmailMessage.objects')
    @patch('api.services.gmail_service.send_gmail_message')
    def test_12_decision_log_audit_records(
        self, mock_send_gmail, mock_email_msg_objects, mock_rule_objects, mock_log_objects, mock_get_settings
    ):
        mock_get_settings.return_value = self.mock_settings
        mock_rule_objects.filter.return_value.order_by.return_value = [self.mock_rule]
        mock_email_msg_objects.create.side_effect = self._mock_email_message_create
        mock_send_gmail.side_effect = self._mock_send_gmail
        mock_log_objects.filter.return_value.first.return_value = None
        mock_log_objects.create.side_effect = self._mock_log_create

        email_automation_engine.process_incoming_email_automation(
            client=self.mock_client,
            account=self.mock_account,
            provider_message_id="msg_log_013",
            sender_email="audit.client@partner.com",
            sender_name="Audit Tester",
            subject="Inquiry about compliance and security audit",
            body_text="Please send your security audit documentation and quotation.",
            headers=[],
            provider='gmail'
        )

        log = self.logs_db.get(f"{self.mock_client.id}:gmail:msg_log_013")
        self.assertIsNotNone(log)
        self.assertEqual(log.sender_email, "audit.client@partner.com")
        self.assertEqual(log.decision, "replied")
        self.assertEqual(log.reply_status, "delivered")
        self.assertEqual(log.rule_applied, self.mock_rule)
        self.assertIn("Automated reply sent", log.reason)
        print("✔ Test 12 Passed: Decision log audit record contains complete diagnostic fields.")


if __name__ == '__main__':
    unittest.main()
