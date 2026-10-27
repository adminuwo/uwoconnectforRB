"""
Multi-Signal Email Classification Engine
Detects advertisements, promotional emails, newsletters, marketing campaigns,
automated notifications, system bounces, and legitimate customer inquiries.
Uses email headers, sender address patterns, mailing-list metadata, Gmail labels,
and content structure without relying solely on subject keywords.
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ClassificationResult:
    category: str  # business_inquiry, customer_support, sales_inquiry, advertisement, newsletter, promotion, notification, spam, uncertain
    confidence: float
    is_unwanted: bool  # True for ads, newsletters, promos, automated notifications, spam
    signals: List[str] = field(default_factory=list)
    primary_reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# Common bulk ESP headers (RFC & vendor-specific)
BULK_ESP_HEADERS = [
    'x-campaign', 'x-campaign-id', 'x-mc-user', 'x-mailgun-tag',
    'x-sendgrid-eid', 'x-sendgrid-template-id', 'x-marketo-id',
    'x-marketoid', 'x-hubspot-message-id', 'x-postmark-tag',
    'x-constantcontact-id', 'x-ses-outgoing', 'x-klaviyo-message-id',
    'x-mailer-type', 'x-report-abuse', 'x-emarsys-category'
]

# Senders indicating automated systems, bounces, or no-reply
NO_REPLY_KEYWORDS = [
    'mailer-daemon', 'postmaster', 'no-reply', 'noreply', 'donotreply',
    'do-not-reply', 'do_not_reply', 'nobody', 'bounce', 'system', 'daemon',
    'auto-confirm', 'automated', 'notification', 'notifications', 'alert',
    'alerts', 'billing', 'invoices', 'security', 'verify', 'account-security',
    'receipts', 'statement', 'downtime-alerts'
]

# Prefixes indicating marketing or broadcast newsletters
NEWSLETTER_PREFIXES = [
    'news@', 'newsletter@', 'newsletters@', 'digest@', 'bulletin@',
    'announce@', 'updates@', 'events@', 'jobs@', 'talent@', 'press@',
    'press-release@', 'insights@'
]

# Prefixes indicating commercial promotional campaigns
PROMOTIONAL_PREFIXES = [
    'promo@', 'promotions@', 'offers@', 'deals@', 'discounts@',
    'specials@', 'campaign@', 'marketing@', 'shop@', 'rewards@'
]

# Bulk / ESP domain fragments
BULK_DOMAIN_FRAGMENTS = [
    'sendgrid.net', 'mailchimpapp.net', 'mcsv.net', 'cmail19.com', 'cmail20.com',
    'klaviyomail.com', 'hubspotemail.net', 'constantcontact.com', 'em.linkedin.com',
    'bounce.', 'bounces.', 'trk.', 'clicks.', 'mailgun.org'
]

# Unsubscribe phrases typically found in footer of marketing / newsletters
UNSUBSCRIBE_PHRASES = [
    'unsubscribe', 'opt-out', 'opt out', 'manage your preferences',
    'manage preferences', 'email preferences', 'click here to unsubscribe',
    'view in browser', 'view email in browser', 'you received this email because',
    'to stop receiving these emails', 'if you prefer not to receive',
    'privacy policy | unsubscribe', 'update subscription preferences'
]

# High-intent customer support keywords
SUPPORT_KEYWORDS = [
    'help', 'issue', 'problem', 'not working', 'error', 'urgent',
    'bug', 'assistance', 'broken', 'ticket', 'trouble', 'failed to',
    'complaint', 'cannot access', 'unable to', 'need support', 'service request'
]

# High-intent sales / business inquiry keywords
INQUIRY_KEYWORDS = [
    'inquiry', 'quote', 'quotation', 'pricing', 'interested in',
    'demo', 'partnership', 'cost', 'proposal', 'services', 'requirements',
    'contract', 'purchase', 'buy', 'schedule a call', 'meeting', 'hire',
    'consultation', 'looking for a solution', 'collaboration'
]

# Cold prospecting advertisement and promotional phrases
AD_PHRASES = [
    'i came across your website', 'we specialize in', 'guest post',
    'b2b leads', 'boost your sales', 'grow your revenue', 'outsourcing services',
    'hire dedicated developers', 'free trial', 'exclusive discount',
    'limited time offer', 'coupon code', '% off', 'discount valid',
    'rank higher on google', 'seo services', 'web design services',
    'advertisement', 'advertise', 'advertising', 'sponsored post',
    'promo offer', 'special promotion', 'promotional discount',
    'deal of the day', 'exclusive deal', 'marketing campaign',
    'backlink', 'link building', 'sponsored content', 'commercial offer'
]

# Automated bounce / out-of-office subject keywords
BOUNCE_SUBJECT_KEYWORDS = [
    'delivery status notification', 'undelivered mail', 'failure notice',
    'returned to sender', 'auto-reply', 'automatic reply', 'out of office',
    'vacation', 'mail delivery failed', 'failed delivery', 'auto responder'
]


class EmailClassifier:
    """
    Evaluates incoming emails and provides deep multi-signal categorization.
    """

    @classmethod
    def classify(
        cls,
        sender_email: str,
        sender_name: str = "",
        subject: str = "",
        headers: Optional[List[Dict[str, str]]] = None,
        body_text: str = "",
        gmail_labels: Optional[List[str]] = None,
        client_email: str = ""
    ) -> ClassificationResult:
        s_email = (sender_email or "").strip().lower()
        s_name = (sender_name or "").strip()
        s_subj = (subject or "").strip().lower()
        body_lower = (body_text or "").lower()
        gmail_labels = [str(l).upper() for l in (gmail_labels or [])]

        # Normalize headers to {lowercase_name: value}
        headers_dict: Dict[str, str] = {}
        if headers:
            for h in headers:
                name = h.get('name', '').strip().lower()
                val = h.get('value', '').strip()
                if name:
                    headers_dict[name] = val

        signals: List[str] = []

        # ── 1. SELF-SENT / INTERNAL LOOP DETECTION ────────────────────────────
        if client_email and s_email == client_email.strip().lower():
            return ClassificationResult(
                category='notification',
                confidence=1.0,
                is_unwanted=True,
                signals=['self_sent_email'],
                primary_reason="Email sent by client mailbox to itself (loop prevention)",
                details={'sender': s_email, 'client_email': client_email}
            )

        # ── 2. SYSTEM BOUNCES & AUTOMATED NOTIFICATIONS IN SUBJECT ─────────────
        for b_word in BOUNCE_SUBJECT_KEYWORDS:
            if b_word in s_subj:
                signals.append(f"subject_bounce_pattern:{b_word}")
                return ClassificationResult(
                    category='notification',
                    confidence=0.99,
                    is_unwanted=True,
                    signals=signals,
                    primary_reason=f"System bounce or automated notice detected in subject ('{b_word}')",
                    details={'subject': subject}
                )

        # ── 3. RFC & PROVIDER AUTOMATION HEADERS ───────────────────────────────
        # List-Unsubscribe is the gold standard for bulk marketing / newsletters
        has_list_unsubscribe = (
            'list-unsubscribe' in headers_dict or
            'list-unsubscribe-post' in headers_dict
        )
        if has_list_unsubscribe:
            signals.append('header:list-unsubscribe')

        # List headers (RFC 2369)
        list_headers = [h for h in ['list-id', 'list-owner', 'list-help', 'list-archive'] if h in headers_dict]
        if list_headers:
            signals.append(f"header:mailing_list({','.join(list_headers)})")

        # Auto-Submitted (RFC 3834)
        auto_sub = headers_dict.get('auto-submitted', '').lower()
        if auto_sub and auto_sub != 'no':
            signals.append(f"header:auto-submitted({auto_sub})")

        # Precedence bulk/junk/list
        precedence = headers_dict.get('precedence', '').lower()
        if precedence in ['bulk', 'junk', 'list', 'newsletter', 'batch']:
            signals.append(f"header:precedence({precedence})")

        # Microsoft Exchange auto-reply suppression
        x_auto_suppress = headers_dict.get('x-auto-response-suppress', '').lower()
        if x_auto_suppress:
            signals.append(f"header:x-auto-response-suppress({x_auto_suppress})")

        # X-Autoreply
        if headers_dict.get('x-autoreply', '').lower() == 'yes':
            signals.append('header:x-autoreply')

        # Bulk ESP Headers (SendGrid, Mailchimp, HubSpot, etc.)
        detected_esp_headers = [h for h in BULK_ESP_HEADERS if h in headers_dict]
        if detected_esp_headers:
            signals.append(f"header:esp({','.join(detected_esp_headers[:3])})")

        # Spam headers
        x_spam_flag = headers_dict.get('x-spam-flag', '').lower()
        x_spam_status = headers_dict.get('x-spam-status', '').lower()
        if x_spam_flag == 'yes' or 'yes' in x_spam_status:
            signals.append('header:spam_flag_detected')

        # ── 4. GMAIL CATEGORY LABELS ──────────────────────────────────────────
        if 'CATEGORY_PROMOTIONS' in gmail_labels:
            signals.append('gmail_label:CATEGORY_PROMOTIONS')
        if 'CATEGORY_SOCIAL' in gmail_labels:
            signals.append('gmail_label:CATEGORY_SOCIAL')
        if 'CATEGORY_FORUMS' in gmail_labels:
            signals.append('gmail_label:CATEGORY_FORUMS')
        if 'SPAM' in gmail_labels or 'TRASH' in gmail_labels:
            signals.append('gmail_label:SPAM_OR_TRASH')

        # ── 5. SENDER ADDRESS PATTERNS ─────────────────────────────────────────
        sender_user = s_email.split('@')[0] if '@' in s_email else s_email
        sender_domain = s_email.split('@')[1] if '@' in s_email else ''

        if any(k in sender_user for k in NO_REPLY_KEYWORDS):
            signals.append('sender:no-reply_or_bot_keyword')

        if any(s_email.startswith(p) for p in NEWSLETTER_PREFIXES):
            signals.append('sender:newsletter_prefix')

        if any(s_email.startswith(p) for p in PROMOTIONAL_PREFIXES):
            signals.append('sender:promotional_prefix')

        if any(f in sender_domain for f in BULK_DOMAIN_FRAGMENTS):
            signals.append(f"sender_domain:bulk_esp({sender_domain})")

        # ── 6. BODY CONTENT SIGNALS ────────────────────────────────────────────
        unsubscribe_matches = [phrase for phrase in UNSUBSCRIBE_PHRASES if phrase in body_lower]
        if unsubscribe_matches:
            signals.append(f"body:unsubscribe_phrase({unsubscribe_matches[0]})")

        ad_phrase_matches = [p for p in AD_PHRASES if p in body_lower or p in s_subj]
        if ad_phrase_matches:
            signals.append(f"body:ad_phrase({ad_phrase_matches[0]})")

        support_matches = [w for w in SUPPORT_KEYWORDS if w in s_subj or w in body_lower[:500]]
        inquiry_matches = [w for w in INQUIRY_KEYWORDS if w in s_subj or w in body_lower[:500]]

        # ── 7. SYNTHESIZE SIGNALS & CLASSIFY ───────────────────────────────────

        # Check for explicit SPAM
        if 'gmail_label:SPAM_OR_TRASH' in signals or 'header:spam_flag_detected' in signals:
            return ClassificationResult(
                category='spam',
                confidence=0.98,
                is_unwanted=True,
                signals=signals,
                primary_reason="Spam flag or Gmail SPAM label detected",
                details={'signals': signals}
            )

        # Check for Automated Notification / System Message
        if (
            any(s.startswith('header:auto-submitted') for s in signals) or
            'header:x-auto-response-suppress' in signals or
            'header:x-autoreply' in signals or
            'sender:no-reply_or_bot_keyword' in signals or
            'gmail_label:CATEGORY_SOCIAL' in signals
        ):
            return ClassificationResult(
                category='notification',
                confidence=0.95,
                is_unwanted=True,
                signals=signals,
                primary_reason="Automated system/notification headers or no-reply sender address detected",
                details={'signals': signals}
            )

        # Check for Promotional Campaign First
        if (
            'gmail_label:CATEGORY_PROMOTIONS' in signals or
            'sender:promotional_prefix' in signals
        ):
            return ClassificationResult(
                category='promotion',
                confidence=0.95,
                is_unwanted=True,
                signals=signals,
                primary_reason="Promotional campaign prefix or Gmail CATEGORY_PROMOTIONS label detected",
                details={'signals': signals}
            )

        # Check for Newsletters / Marketing Mailing Lists
        if (
            has_list_unsubscribe or
            any(s.startswith('header:mailing_list') for s in signals) or
            'sender:newsletter_prefix' in signals or
            'gmail_label:CATEGORY_FORUMS' in signals or
            (len(unsubscribe_matches) > 0 and len(detected_esp_headers) > 0)
        ):
            return ClassificationResult(
                category='newsletter',
                confidence=0.94,
                is_unwanted=True,
                signals=signals,
                primary_reason="Mailing list / newsletter headers (e.g. List-Unsubscribe) or newsletter sender detected",
                details={'signals': signals}
            )

        # Check for Promotional / Advertisement Campaign
        if (
            'gmail_label:CATEGORY_PROMOTIONS' in signals or
            (len(detected_esp_headers) > 0 and len(unsubscribe_matches) > 0) or
            (len(ad_phrase_matches) > 0 and (len(detected_esp_headers) > 0 or len(unsubscribe_matches) > 0)) or
            precedence in ['bulk', 'junk']
        ):
            return ClassificationResult(
                category='promotion' if 'gmail_label:CATEGORY_PROMOTIONS' in signals else 'advertisement',
                confidence=0.92,
                is_unwanted=True,
                signals=signals,
                primary_reason="Commercial advertisement / promotional campaign signals detected",
                details={'signals': signals}
            )

        # If ad pitch phrases found in plain email without bulk headers (cold prospecting / advertisement)
        if len(ad_phrase_matches) >= 1:
            return ClassificationResult(
                category='advertisement',
                confidence=0.88,
                is_unwanted=True,
                signals=signals,
                primary_reason=f"Commercial cold sales solicitation / advertisement patterns detected ('{ad_phrase_matches[0]}')",
                details={'signals': signals}
            )

        # ── 8. LEGITIMATE CUSTOMER INQUIRIES & SUPPORT REQUESTS ────────────────
        if len(support_matches) > 0 and not has_list_unsubscribe:
            return ClassificationResult(
                category='customer_support',
                confidence=0.88,
                is_unwanted=False,
                signals=signals + [f"keyword:support({','.join(support_matches[:3])})"],
                primary_reason=f"Customer support / issue inquiry signals matched ('{support_matches[0]}')",
                details={'signals': signals, 'support_matches': support_matches}
            )

        if len(inquiry_matches) > 0 and not has_list_unsubscribe:
            return ClassificationResult(
                category='business_inquiry',
                confidence=0.87,
                is_unwanted=False,
                signals=signals + [f"keyword:inquiry({','.join(inquiry_matches[:3])})"],
                primary_reason=f"Direct business inquiry signals matched ('{inquiry_matches[0]}')",
                details={'signals': signals, 'inquiry_matches': inquiry_matches}
            )

        # Single direct conversation without bulk headers or unsubscribe
        if len(signals) == 0 and sender_domain and '@' in s_email:
            # Clean direct 1-on-1 business conversation
            return ClassificationResult(
                category='business_inquiry',
                confidence=0.75,
                is_unwanted=False,
                signals=['direct_1to1_email_no_bulk_flags'],
                primary_reason="Direct 1-to-1 incoming email without promotional or automated headers",
                details={'signals': signals}
            )

        # If there are residual unsubscribe links but no other inquiry matches -> treat as uncertain / promotional
        if len(unsubscribe_matches) > 0:
            return ClassificationResult(
                category='newsletter',
                confidence=0.80,
                is_unwanted=True,
                signals=signals,
                primary_reason="Unsubscribe/opt-out phrasing detected in message footer",
                details={'signals': signals}
            )

        # Fallback to uncertain
        return ClassificationResult(
            category='uncertain',
            confidence=0.40,
            is_unwanted=False,
            signals=signals,
            primary_reason="Classification uncertain: insufficient distinct signals",
            details={'signals': signals}
        )
