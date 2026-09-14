import os
import sys
import django
from datetime import timedelta
from django.utils import timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from api.models import Client, Contact, Conversation, Message, ConversationAuditLog, User
from api.services.bot_loop_protection_service import BotLoopProtectionService
from api.repositories.message_repository import MessageRepository
from rest_framework.test import APIRequestFactory, force_authenticate
from api.views.monitoring_views import ConversationViewSet


def reset_test_state(client, contact, test_phone):
    """Helper to ensure clean, isolated state before each test case."""
    Message.objects.filter(client=client, from_address=test_phone).delete()
    Message.objects.filter(client=client, to_address=test_phone).delete()
    contact.bot_paused = False
    contact.save()


def run_tests():
    print("=" * 80)
    print("🧪 RUNNING COMPREHENSIVE BOT LOOP PROTECTION & REGRESSION TEST SUITE")
    print("=" * 80)

    # 0. Setup test client and user
    client = Client.objects.filter(status='ACTIVE').first() or Client.objects.first()
    assert client is not None, "Client not found!"
    user = User.objects.filter(client=client).first() or User.objects.first()

    test_phone = "919888877771"

    # Clean up any existing test records for this phone
    Message.objects.filter(client=client, from_address=test_phone).delete()
    Message.objects.filter(client=client, to_address=test_phone).delete()
    Contact.objects.filter(client=client, platform_id=test_phone).delete()
    Conversation.objects.filter(client=client, contact_platform_id=test_phone).delete()

    contact = Contact.objects.create(
        client=client,
        name="Loop Test Contact",
        platform_id=test_phone,
        phone_number=test_phone,
        bot_paused=False
    )
    convo = Conversation.objects.create(
        client=client,
        contact=contact,
        contact_platform_id=test_phone,
        channel='WHATSAPP',
        status='OPEN'
    )

    passed_count = 0
    total_count = 0

    # -------------------------------------------------------------
    # TEST 1: Text Normalization Accuracy
    # -------------------------------------------------------------
    total_count += 1
    t1 = "  Hello, World!  "
    t2 = "hello world"
    t3 = "HELLO WORLD!!!"
    assert BotLoopProtectionService.normalize_text(t1) == "hello world"
    assert BotLoopProtectionService.normalize_text(t2) == "hello world"
    assert BotLoopProtectionService.normalize_text(t3) == "hello world"
    passed_count += 1
    print("  [PASS] Test 1: Text normalization properly handles case, punctuation, whitespace.")

    # -------------------------------------------------------------
    # TEST 2: Auto-responder Phrase Matching
    # -------------------------------------------------------------
    total_count += 1
    is_auto1, phrase1 = BotLoopProtectionService.is_auto_reply_phrase("I am currently out of office until Monday.")
    assert is_auto1 is True and "out of office" in phrase1.lower()
    is_auto2, _ = BotLoopProtectionService.is_auto_reply_phrase("Auto-Reply: Thank you for your email.")
    assert is_auto2 is True
    is_auto3, _ = BotLoopProtectionService.is_auto_reply_phrase("This is an automated message, do not reply.")
    assert is_auto3 is True
    is_human, _ = BotLoopProtectionService.is_auto_reply_phrase("Hi, what are the pricing packages for enterprise CRM?")
    assert is_human is False
    passed_count += 1
    print("  [PASS] Test 2: Auto-responder signatures detected accurately without false positives.")

    # -------------------------------------------------------------
    # TEST 3: Normal Human Conversation Flow (NO Loop Detected)
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)
    human_messages = [
        "Hi, I need information about your CRM.",
        "Can you also share the pricing tiers?",
        "Great, what integrations do you support?"
    ]
    for msg_text in human_messages:
        msg_obj = MessageRepository.create_message(
            client=client,
            channel='WHATSAPP',
            from_address=test_phone,
            to_address='TEST_BOT',
            body=msg_text,
            message_type='INCOMING',
            status='RECEIVED'
        )
        is_loop = BotLoopProtectionService.check_and_protect(
            client=client,
            contact_platform_id=test_phone,
            incoming_text=msg_text,
            channel='WHATSAPP',
            contact=contact,
            conversation=convo,
            current_message=msg_obj
        )
        assert is_loop is False, f"Normal human message falsely flagged as loop: '{msg_text}'"

    contact.refresh_from_db()
    assert contact.bot_paused is False, "Contact bot was paused during normal conversation!"
    passed_count += 1
    print("  [PASS] Test 3: Normal human conversation flow continues with zero interference (bot stays active).")

    # -------------------------------------------------------------
    # TEST 4: Repeated Consecutive Incoming Messages Loop
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)
    repeated_text = "Are you available right now?"

    # Prior message 1
    MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body=repeated_text,
        message_type='INCOMING',
        status='RECEIVED'
    )
    # Prior message 2
    MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body=repeated_text,
        message_type='INCOMING',
        status='RECEIVED'
    )
    # 3rd incoming message arrives
    curr_msg = MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body=repeated_text,
        message_type='INCOMING',
        status='RECEIVED'
    )

    is_loop_rep = BotLoopProtectionService.check_and_protect(
        client=client,
        contact_platform_id=test_phone,
        incoming_text=repeated_text,
        channel='WHATSAPP',
        contact=contact,
        conversation=convo,
        current_message=curr_msg
    )
    assert is_loop_rep is True, "3rd consecutive identical message failed to trigger loop protection!"

    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on repeated message loop!"

    # Verify audit log was created
    audit = ConversationAuditLog.objects.filter(
        conversation=convo,
        event_type="BOT_AUTO_PAUSED"
    ).order_by('-created_at').first()
    assert audit is not None, "ConversationAuditLog was not recorded for loop auto-pause!"
    assert audit.details.get('loop_type') == 'REPEATED_INCOMING_LOOP', f"Unexpected loop_type: {audit.details}"

    # Verify internal timeline note was created
    internal_notice = Message.objects.filter(
        client=client,
        to_address=test_phone,
        message_type='INTERNAL'
    ).order_by('-created_at').first()
    assert internal_notice is not None, "Internal timeline notice was not created for agents!"
    assert "Bot Auto-Paused" in internal_notice.body, f"Unexpected notice body: {internal_notice.body}"
    passed_count += 1
    print("  [PASS] Test 4: Repeated identical message loop detected (3x) -> Bot auto-paused, audit logged, notice posted.")

    # -------------------------------------------------------------
    # TEST 5: Resume Bot Restores Active State
    # -------------------------------------------------------------
    total_count += 1
    factory = APIRequestFactory()
    view_resume = ConversationViewSet.as_view({'post': 'resume_bot'})
    req = factory.post(f'/api/conversations/{convo.id}/resume_bot/')
    force_authenticate(req, user=user)
    res = view_resume(req, pk=str(convo.id))
    assert res.status_code == 200, f"resume_bot failed with status {res.status_code}"

    contact.refresh_from_db()
    assert contact.bot_paused is False, "Contact bot_paused is not False after resume_bot!"
    passed_count += 1
    print("  [PASS] Test 5: Resume Bot action successfully unpauses contact and restores bot active state.")

    # -------------------------------------------------------------
    # TEST 6: Bot-to-Bot External Auto-Responder Loop
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)

    # Bot sent an outgoing response
    MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address='TEST_BOT',
        to_address=test_phone,
        body="Hello! Thank you for contacting Uwo Connect. How can we help you today?",
        message_type='OUTGOING',
        status='SENT'
    )
    # External contact's server immediately auto-replies with out-of-office message
    auto_reply_text = "Auto-Reply: Thank you for contacting us. Our office is currently closed."
    auto_msg = MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body=auto_reply_text,
        message_type='INCOMING',
        status='RECEIVED'
    )

    is_loop_auto = BotLoopProtectionService.check_and_protect(
        client=client,
        contact_platform_id=test_phone,
        incoming_text=auto_reply_text,
        channel='WHATSAPP',
        contact=contact,
        conversation=convo,
        current_message=auto_msg
    )
    assert is_loop_auto is True, "External bot auto-reply failed to trigger loop protection!"
    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on auto-reply loop!"
    passed_count += 1
    print("  [PASS] Test 6: External bot auto-responder loop detected -> Bot auto-paused immediately.")

    # -------------------------------------------------------------
    # TEST 7: Self-Echo Mirroring Loop
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)

    bot_msg_text = "Here is our product catalog link: https://uwo24.com/catalog"
    MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address='TEST_BOT',
        to_address=test_phone,
        body=bot_msg_text,
        message_type='OUTGOING',
        status='SENT'
    )
    # Contact echoes back our bot's own text
    echo_msg = MessageRepository.create_message(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body=bot_msg_text,
        message_type='INCOMING',
        status='RECEIVED'
    )

    is_loop_echo = BotLoopProtectionService.check_and_protect(
        client=client,
        contact_platform_id=test_phone,
        incoming_text=bot_msg_text,
        channel='WHATSAPP',
        contact=contact,
        conversation=convo,
        current_message=echo_msg
    )
    assert is_loop_echo is True, "Self-echo failed to trigger loop protection!"
    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on self-echo!"
    passed_count += 1
    print("  [PASS] Test 7: Self-echo mirroring loop detected -> Bot auto-paused.")

    # -------------------------------------------------------------
    # TEST 8: Rapid Ping-Pong Alternating Loop
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)

    # Create 5 prior alternating messages (OUT, IN, OUT, IN, OUT) within 10 seconds
    base_time = timezone.now() - timedelta(seconds=12)
    for i in range(5):
        m_type = 'OUTGOING' if i % 2 == 0 else 'INCOMING'
        from_addr = 'TEST_BOT' if m_type == 'OUTGOING' else test_phone
        to_addr = test_phone if m_type == 'OUTGOING' else 'TEST_BOT'
        m = Message.objects.create(
            client=client,
            channel='WHATSAPP',
            from_address=from_addr,
            to_address=to_addr,
            body=f"Ping-pong cycle {i}",
            message_type=m_type,
            status='SENT'
        )
        Message.objects.filter(id=m.id).update(created_at=base_time + timedelta(seconds=i * 2))

    # The 6th message arrives (INCOMING)
    curr_pp = Message.objects.create(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body="Ping-pong cycle 5",
        message_type='INCOMING',
        status='RECEIVED'
    )
    Message.objects.filter(id=curr_pp.id).update(created_at=timezone.now())

    is_loop_pp = BotLoopProtectionService.check_and_protect(
        client=client,
        contact_platform_id=test_phone,
        incoming_text="Ping-pong cycle 5",
        channel='WHATSAPP',
        contact=contact,
        conversation=convo,
        current_message=curr_pp
    )
    assert is_loop_pp is True, "Rapid ping-pong alternating loop was not detected!"
    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on rapid ping-pong!"
    passed_count += 1
    print("  [PASS] Test 8: Rapid reciprocal ping-pong alternating loop detected -> Bot auto-paused.")

    # -------------------------------------------------------------
    # TEST 9: High-Frequency Message Burst Flood
    # -------------------------------------------------------------
    total_count += 1
    reset_test_state(client, contact, test_phone)

    # Contact sends 4 prior messages rapidly in the last 2 seconds
    for i in range(4):
        Message.objects.create(
            client=client,
            channel='WHATSAPP',
            from_address=test_phone,
            to_address='TEST_BOT',
            body=f"Flood message {i}",
            message_type='INCOMING',
            status='RECEIVED'
        )

    # 5th message arrives
    curr_flood = Message.objects.create(
        client=client,
        channel='WHATSAPP',
        from_address=test_phone,
        to_address='TEST_BOT',
        body="Flood message 5",
        message_type='INCOMING',
        status='RECEIVED'
    )

    is_loop_flood = BotLoopProtectionService.check_and_protect(
        client=client,
        contact_platform_id=test_phone,
        incoming_text="Flood message 5",
        channel='WHATSAPP',
        contact=contact,
        conversation=convo,
        current_message=curr_flood
    )
    assert is_loop_flood is True, "Message flood loop was not detected!"
    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on message flood!"
    passed_count += 1
    print("  [PASS] Test 9: High-frequency message flood burst detected -> Bot auto-paused.")

    # Clean up test records
    Message.objects.filter(client=client, from_address=test_phone).delete()
    Message.objects.filter(client=client, to_address=test_phone).delete()
    contact.delete()
    convo.delete()

    print("\n" + "=" * 80)
    print(f"🎉 ALL {passed_count}/{total_count} BOT LOOP PROTECTION VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == '__main__':
    run_tests()
