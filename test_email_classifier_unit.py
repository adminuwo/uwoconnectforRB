"""
Unit and Functional tests for EmailClassifier and Automation Rules
"""
import unittest
from api.services.email_classifier import EmailClassifier


class TestEmailClassifier(unittest.TestCase):

    def test_01_legitimate_customer_inquiry(self):
        result = EmailClassifier.classify(
            sender_email="john.smith@acmecorp.com",
            sender_name="John Smith",
            subject="Inquiry regarding enterprise pricing and demo",
            headers=[
                {'name': 'From', 'value': 'John Smith <john.smith@acmecorp.com>'},
                {'name': 'To', 'value': 'connect@uwo24.com'}
            ],
            body_text="Hi team, we are interested in getting a quotation and demo for your platform. Please let us know available times for a call."
        )
        self.assertEqual(result.category, 'business_inquiry')
        self.assertFalse(result.is_unwanted)
        self.assertGreater(result.confidence, 0.70)
        print("✔ Test 1 Passed: Legitimate customer inquiry classified correctly.")

    def test_02_advertisement_cold_pitch(self):
        result = EmailClassifier.classify(
            sender_email="outreach@growth-agency.io",
            sender_name="Alex Marketing",
            subject="Boost your sales with our B2B leads and SEO services",
            headers=[
                {'name': 'From', 'value': 'Alex <outreach@growth-agency.io>'}
            ],
            body_text="Hi, I came across your website and we specialize in SEO services to boost your sales and grow your revenue. Exclusive discount for you."
        )
        self.assertIn(result.category, ['advertisement', 'promotion'])
        self.assertTrue(result.is_unwanted)
        print("✔ Test 2 Passed: Advertisement / Cold pitch flagged as unwanted.")

    def test_03_newsletter_with_list_unsubscribe_header(self):
        result = EmailClassifier.classify(
            sender_email="digest@techinsider.com",
            sender_name="Tech Insider Weekly",
            subject="Weekly Developer Digest: Issue #142",
            headers=[
                {'name': 'List-Unsubscribe', 'value': '<mailto:unsubscribe@techinsider.com>, <https://techinsider.com/unsub>'},
                {'name': 'Precedence', 'value': 'bulk'},
                {'name': 'X-Campaign', 'value': 'weekly_digest_142'}
            ],
            body_text="Here is your weekly roundup of tech news. Click here to unsubscribe or manage preferences."
        )
        self.assertEqual(result.category, 'newsletter')
        self.assertTrue(result.is_unwanted)
        self.assertIn('header:list-unsubscribe', result.signals)
        print("✔ Test 3 Passed: Newsletter with List-Unsubscribe header classified as unwanted newsletter.")

    def test_04_promotional_email_with_gmail_label(self):
        result = EmailClassifier.classify(
            sender_email="offers@shoppinghub.com",
            sender_name="Shopping Deals",
            subject="50% OFF FLASH SALE - Limited Time Only!",
            headers=[],
            body_text="Grab our exclusive discount before it expires tonight. Use coupon code FLASH50 at checkout.",
            gmail_labels=['CATEGORY_PROMOTIONS', 'INBOX']
        )
        self.assertEqual(result.category, 'promotion')
        self.assertTrue(result.is_unwanted)
        print("✔ Test 4 Passed: Gmail CATEGORY_PROMOTIONS label classified as promotion.")

    def test_05_no_reply_system_email(self):
        result = EmailClassifier.classify(
            sender_email="no-reply@authprovider.com",
            sender_name="Security Team",
            subject="Your verification code is 849201",
            headers=[
                {'name': 'Auto-Submitted', 'value': 'auto-generated'}
            ],
            body_text="Your one-time passcode is 849201. Please do not reply to this email."
        )
        self.assertEqual(result.category, 'notification')
        self.assertTrue(result.is_unwanted)
        print("✔ Test 5 Passed: No-reply / Auto-Submitted notification classified as unwanted for auto-reply.")

    def test_06_bounce_and_delivery_failure(self):
        result = EmailClassifier.classify(
            sender_email="mailer-daemon@googlemail.com",
            sender_name="Mail Delivery Subsystem",
            subject="Delivery Status Notification (Failure)",
            headers=[],
            body_text="The recipient's mailbox is full and could not receive your message."
        )
        self.assertEqual(result.category, 'notification')
        self.assertTrue(result.is_unwanted)
        print("✔ Test 6 Passed: Delivery status notification / mailer-daemon rejected.")

    def test_07_customer_support_issue(self):
        result = EmailClassifier.classify(
            sender_email="sarah.connor@client.org",
            sender_name="Sarah Connor",
            subject="Urgent: Cannot access my account, seeing error 500",
            headers=[
                {'name': 'From', 'value': 'sarah.connor@client.org'}
            ],
            body_text="Hello, we are experiencing an issue with our login. It says error 500 and is not working. Please help as soon as possible."
        )
        self.assertEqual(result.category, 'customer_support')
        self.assertFalse(result.is_unwanted)
        print("✔ Test 7 Passed: Customer support issue classified as legitimate.")

    def test_08_self_sent_loop_prevention(self):
        result = EmailClassifier.classify(
            sender_email="support@mybusiness.com",
            sender_name="My Support Desk",
            subject="Internal Ticket Update",
            headers=[],
            body_text="Testing automated dispatch",
            client_email="support@mybusiness.com"
        )
        self.assertEqual(result.category, 'notification')
        self.assertTrue(result.is_unwanted)
        self.assertIn('self_sent_email', result.signals)
        print("✔ Test 8 Passed: Self-sent email loop prevented.")


if __name__ == '__main__':
    unittest.main()
