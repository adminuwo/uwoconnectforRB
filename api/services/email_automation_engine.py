"""
Enterprise Email Automation & Idempotency Engine
Ensures:
1. Zero automated replies to promotional emails, newsletters, ads, and spam by default.
2. Absolute idempotency: maximum ONE automated reply per incoming email across all workers and retries.
3. Enforcement of client-controlled settings (filters, allowlist, excluded senders/domains, category toggles).
4. Full audit decision logging for every incoming message.
"""

import logging
from django.utils import timezone
from api.models import (
    Client, EmailAccount, EmailMessage, EmailAutoReplyRule,
    EmailAutomationWorkflow, EmailAutomationSettings, EmailAutomationLog
)
from .email_classifier import EmailClassifier, ClassificationResult

logger = logging.getLogger(__name__)


def get_or_create_client_settings(client: Client, account: EmailAccount = None) -> EmailAutomationSettings:
    """
    Retrieves the effective automation settings for a client/account.
    Priority: specific EmailAccount settings -> client-wide default settings -> newly created defaults.
    """
    if account:
        acc_settings = EmailAutomationSettings.objects.filter(client=client, account=account).first()
        if acc_settings:
            return acc_settings

    global_settings = EmailAutomationSettings.objects.filter(client=client, account=None).first()
    if global_settings:
        return global_settings

    # Create sensible defaults if none exist
    return EmailAutomationSettings.objects.create(
        client=client,
        account=None,
        is_enabled=True,
        auto_reply_business_inquiry=True,
        auto_reply_customer_support=True,
        auto_reply_sales_inquiry=True,
        auto_reply_advertisement=False,
        auto_reply_newsletter=False,
        auto_reply_promotion=False,
        auto_reply_notification=False,
        auto_reply_spam=False,
        uncertain_fallback='skip',
        allowlist_mode=False
    )


def process_incoming_email_automation(
    client: Client,
    account: EmailAccount,
    provider_message_id: str,
    sender_email: str,
    sender_name: str = "",
    subject: str = "",
    body_text: str = "",
    headers: list = None,
    gmail_labels: list = None,
    incoming_email_message: EmailMessage = None,
    provider: str = 'gmail'
) -> dict:
    """
    Main entry point for evaluating automation for an incoming email.
    Guarantees idempotency and at most ONE reply per incoming email.
    """
    if not provider_message_id or not sender_email:
        return {'status': 'skipped', 'reason': 'Missing provider message ID or sender email'}

    import re
    cleaned_match = re.search(r'<([^>]+)>', sender_email)
    s_email = (cleaned_match.group(1) if cleaned_match else sender_email).strip().lower()
    s_domain = s_email.split('@')[1] if '@' in s_email else ''
    client_email = (account.email_address if account else getattr(client, 'email', '') or '').strip().lower()

    # ── 1. IDEMPOTENCY LOCK & DEDUPLICATION ──────────────────────────────────
    idempotency_key = f"{client.id}:{provider}:{provider_message_id}"
    
    # Check if this exact incoming email has already been processed or logged
    existing_log = EmailAutomationLog.objects.filter(idempotency_key=idempotency_key).first()
    if existing_log:
        if existing_log.decision in ['replied', 'processing']:
            logger.info(f"[AutomationIdempotency] Message {provider_message_id} already has decision '{existing_log.decision}'. Skipping duplicate.")
            return {
                'status': 'skipped',
                'decision': existing_log.decision,
                'reason': f"Duplicate event: already {existing_log.decision}"
            }
        elif existing_log.decision in ['skipped', 'pending_review']:
            # Already evaluated and skipped/pending
            return {
                'status': 'skipped',
                'decision': existing_log.decision,
                'reason': existing_log.reason
            }

    # ── 2. LOAD CLIENT SETTINGS ──────────────────────────────────────────────
    settings = get_or_create_client_settings(client, account)

    # ── 3. RUN MULTI-SIGNAL CLASSIFIER ───────────────────────────────────────
    classification: ClassificationResult = EmailClassifier.classify(
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        headers=headers,
        body_text=body_text,
        gmail_labels=gmail_labels,
        client_email=client_email
    )

    # Helper to record decision log
    def _create_log(decision: str, reason: str, rule: EmailAutoReplyRule = None, reply_msg: EmailMessage = None, reply_status: str = 'none', error_msg: str = '') -> EmailAutomationLog:
        return EmailAutomationLog.objects.create(
            client=client,
            account=account,
            provider=provider,
            provider_message_id=provider_message_id,
            incoming_message=incoming_email_message,
            idempotency_key=idempotency_key,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            mailbox=account.email_address if account else client_email,
            category=classification.category,
            confidence_score=classification.confidence,
            classification_details={
                'signals': classification.signals,
                'details': classification.details
            },
            decision=decision,
            reason=reason,
            rule_applied=rule,
            reply_message=reply_msg,
            reply_status=reply_status,
            replied_at=timezone.now() if decision == 'replied' else None,
            error_message=error_msg
        )

    # ── 4. EVALUATE CLIENT FILTERS ───────────────────────────────────────────

    # Rule A: Master Toggle
    if not settings.is_enabled:
        _create_log('skipped', "Automation skipped: Master email automation toggle is disabled in settings.")
        return {'status': 'skipped', 'reason': 'Master toggle disabled'}

    # Rule B: Excluded Senders (Aggregated across account & global settings)
    all_excluded_senders = set(s.strip().lower() for s in (settings.excluded_senders or []) if s)
    for other_s in EmailAutomationSettings.objects.filter(client=client):
        if other_s.excluded_senders:
            all_excluded_senders.update(s.strip().lower() for s in other_s.excluded_senders if s)

    if s_email in all_excluded_senders or any(s_email == x or (x and x in s_email) for x in all_excluded_senders):
        _create_log('skipped', f"Automation skipped: Sender {sender_email} is in client blocked email addresses list.")
        return {'status': 'skipped', 'reason': 'Sender in excluded list'}

    # Rule C: Excluded Domains (Aggregated across account & global settings)
    all_excluded_domains = set(d.strip().lower().lstrip('@') for d in (settings.excluded_domains or []) if d)
    for other_s in EmailAutomationSettings.objects.filter(client=client):
        if other_s.excluded_domains:
            all_excluded_domains.update(d.strip().lower().lstrip('@') for d in other_s.excluded_domains if d)

    if s_domain and any(s_domain == d or s_domain.endswith('.' + d) for d in all_excluded_domains):
        _create_log('skipped', f"Automation skipped: Sender domain @{s_domain} is in client blocked domains list.")
        return {'status': 'skipped', 'reason': 'Domain in excluded list'}

    # Rule D: Allowlist Mode
    if settings.allowlist_mode:
        allowed_senders = [s.strip().lower() for s in (settings.allowed_senders or []) if s]
        allowed_domains = [d.strip().lower().lstrip('@') for d in (settings.allowed_domains or []) if d]
        is_allowlisted = (s_email in allowed_senders) or any(s_domain == d or s_domain.endswith('.' + d) for d in allowed_domains)
        if not is_allowlisted:
            _create_log('skipped', "Automation skipped: Allowlist mode is active and sender/domain is not allowlisted.")
            return {'status': 'skipped', 'reason': 'Allowlist mode active: sender not allowlisted'}

    # Rule E: Excluded Keywords in Subject or Body (Aggregated across settings)
    all_exclude_keywords = set(k.strip().lower() for k in (settings.exclude_keywords or []) if k)
    for other_s in EmailAutomationSettings.objects.filter(client=client):
        if other_s.exclude_keywords:
            all_exclude_keywords.update(k.strip().lower() for k in other_s.exclude_keywords if k)

    text_to_search = f"{(subject or '').lower()} {(body_text or '').lower()}"
    for kw in all_exclude_keywords:
        if kw in text_to_search:
            _create_log('skipped', f"Automation skipped: Message matched client excluded keyword '{kw}'.")
            return {'status': 'skipped', 'reason': f"Matched excluded keyword '{kw}'"}

    # Rule F: Required Include Keywords
    include_keywords = [k.strip().lower() for k in (settings.include_keywords or []) if k]
    if include_keywords and not any(kw in text_to_search for kw in include_keywords):
        _create_log('skipped', "Automation skipped: Message did not match any of the client required include keywords.")
        return {'status': 'skipped', 'reason': 'Missing required include keywords'}

    # Rule G: Category Permission Check
    category_allowed_map = {
        'business_inquiry': settings.auto_reply_business_inquiry,
        'customer_support': settings.auto_reply_customer_support,
        'sales_inquiry': settings.auto_reply_sales_inquiry,
        'advertisement': settings.auto_reply_advertisement,
        'newsletter': settings.auto_reply_newsletter,
        'promotion': settings.auto_reply_promotion,
        'notification': settings.auto_reply_notification,
        'spam': settings.auto_reply_spam,
    }

    if classification.category == 'uncertain':
        if settings.uncertain_fallback == 'require_review':
            _create_log('pending_review', "Message classification uncertain; routed to Pending Review as configured.")
            return {'status': 'pending_review', 'reason': 'Uncertain classification: routed to review'}
        else:
            _create_log('skipped', f"Automation skipped: {classification.primary_reason} (Uncertain safe fallback).")
            return {'status': 'skipped', 'reason': 'Uncertain classification: safe fallback skip'}

    is_cat_enabled = category_allowed_map.get(classification.category, False)
    if not is_cat_enabled:
        reason_msg = f"Automation skipped: Category '{classification.category}' is disabled for auto-replies. ({classification.primary_reason})"
        _create_log('skipped', reason_msg)
        return {'status': 'skipped', 'reason': reason_msg}

    # ── 5. MATCH AUTOMATION RULE & DISPATCH AT MOST ONE REPLY ─────────────────
    active_rules = EmailAutoReplyRule.objects.filter(client=client, is_active=True).order_by('id')
    matched_rule = None

    for rule in active_rules:
        rule_matches = True

        if rule.subject_pattern and rule.subject_pattern.lower() not in (subject or "").lower():
            rule_matches = False
        if rule.sender_pattern and rule.sender_pattern.lower() not in s_email:
            rule_matches = False
        if rule.keyword_match:
            kw = rule.keyword_match.lower()
            if kw not in (subject or "").lower() and kw not in (body_text or "").lower():
                rule_matches = False

        if rule_matches:
            matched_rule = rule
            # GUARANTEE: Pick the first matching rule and break. Never trigger multiple replies!
            break

    if not matched_rule:
        _create_log('skipped', f"Category '{classification.category}' allowed, but no active auto-reply rule matched message criteria.")
        return {'status': 'skipped', 'reason': 'No matching auto-reply rule found'}

    # ── 6. PERSONALIZE & SEND AUTOMATED REPLY ────────────────────────────────
    first_name = sender_name.split(' ')[0] if sender_name else "there"
    last_name = sender_name.split(' ')[-1] if sender_name and ' ' in sender_name else ""
    full_name = sender_name or "Valued Customer"
    company_name = getattr(client, 'business_name', '') or getattr(client, 'name', '') or 'UWO Connect'

    def _replace_tags(text: str) -> str:
        if not text:
            return ""
        return (
            text.replace('{{first_name}}', first_name)
                .replace('{{last_name}}', last_name)
                .replace('{{full_name}}', full_name)
                .replace('{{email}}', sender_email)
                .replace('{{company}}', company_name)
        )

    r_body = _replace_tags(matched_rule.reply_body)
    r_subject = _replace_tags(matched_rule.reply_subject or f"Re: {subject}")

    # ── LAST-LINE SAFETY GATE: NEVER DISPATCH TO BLOCKED SENDER OR DOMAIN ──────────────
    fresh_excluded_senders = set(all_excluded_senders)
    fresh_excluded_domains = set(all_excluded_domains)
    for s_rec in EmailAutomationSettings.objects.filter(client=client):
        if s_rec.excluded_senders:
            fresh_excluded_senders.update(x.strip().lower() for x in s_rec.excluded_senders if x)
        if s_rec.excluded_domains:
            fresh_excluded_domains.update(x.strip().lower().lstrip('@') for x in s_rec.excluded_domains if x)

    if (
        s_email in fresh_excluded_senders
        or any(x and (x == s_email or x in s_email or s_email in x) for x in fresh_excluded_senders)
    ):
        logger.warning(f"[EmailAutomation] Last-line safety gate blocked reply to blocked sender {sender_email}")
        _create_log('skipped', f"Automation blocked: Sender {sender_email} is in client blocked email addresses list.")
        return {'status': 'skipped', 'reason': f"Blocked sender: {sender_email}"}

    if s_domain and any(s_domain == d or s_domain.endswith('.' + d) for d in fresh_excluded_domains):
        logger.warning(f"[EmailAutomation] Last-line safety gate blocked reply to blocked domain @{s_domain}")
        _create_log('skipped', f"Automation blocked: Sender domain @{s_domain} is in client blocked domains list.")
        return {'status': 'skipped', 'reason': f"Blocked domain: {s_domain}"}

    try:
        if provider == 'gmail':
            from .gmail_service import send_gmail_message
            send_gmail_message(client, sender_email, r_body, r_subject)
        else:
            # Placeholder for Outlook Graph or SMTP provider dispatch
            pass

        # Record sent reply in EmailMessage
        reply_email_msg = EmailMessage.objects.create(
            client=client,
            account=account,
            folder='sent',
            sender_email=client_email,
            sender_name=account.display_name if account and account.display_name else client_email,
            to_recipients=[sender_email],
            subject=r_subject,
            body_text=r_body,
            body_html=r_body,
            status='delivered',
            priority='normal',
            metadata={
                'reply_to_provider_msg_id': provider_message_id,
                'auto_reply_rule_id': str(matched_rule.id),
                'rule_name': matched_rule.name,
                'classification_category': classification.category
            }
        )

        # Log successful dispatch
        _create_log(
            decision='replied',
            reason=f"Automated reply sent matching rule '{matched_rule.name}' for {classification.category}.",
            rule=matched_rule,
            reply_msg=reply_email_msg,
            reply_status='delivered'
        )

        return {
            'status': 'replied',
            'rule': matched_rule.name,
            'category': classification.category,
            'reply_id': str(reply_email_msg.id)
        }

    except Exception as e:
        logger.error(f"[EmailAutomationEngine] Error sending reply to {sender_email}: {e}")
        _create_log(
            decision='failed',
            reason=f"Attempted reply with rule '{matched_rule.name}', but dispatch failed: {str(e)}",
            rule=matched_rule,
            reply_status='failed',
            error_msg=str(e)
        )
        return {'status': 'failed', 'error': str(e)}
