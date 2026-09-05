import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from api.models import Client, Contact, Conversation, User
from api.serializers import ConversationSerializer
from rest_framework.test import APIRequestFactory, force_authenticate
from api.views.monitoring_views import ConversationViewSet

def test_bot_toggle_integrity():
    print("=" * 70)
    print("RUNNING BOT TOGGLE & HANDOFF SERIALIZATION VERIFICATION")
    print("=" * 70)

    # 1. Setup client and user
    client = Client.objects.filter(status='ACTIVE').first() or Client.objects.first()
    assert client is not None, "Client workspace not found!"
    print(f"[OK] Testing with Client: {client.business_name}")

    user = User.objects.filter(client=client).first() or User.objects.first()
    assert user is not None, "User not found!"

    # 2. Setup contact and conversation
    contact, _ = Contact.objects.get_or_create(
        client=client,
        platform_id="919999999999",
        defaults={'name': 'Test Handoff Contact', 'phone_number': '919999999999', 'bot_paused': False}
    )
    # Ensure starting in bot active (bot_paused = False)
    contact.bot_paused = False
    contact.save()

    convo, _ = Conversation.objects.get_or_create(
        client=client,
        contact_platform_id="919999999999",
        defaults={'contact': contact, 'channel': 'WHATSAPP', 'status': 'OPEN'}
    )
    convo.contact = contact
    convo.save()

    # 3. Verify Serializer output includes bot_paused = False
    serializer = ConversationSerializer(convo)
    data = serializer.data
    assert 'bot_paused' in data, "bot_paused missing in ConversationSerializer!"
    assert data['bot_paused'] is False, f"Expected bot_paused=False, got {data['bot_paused']}"
    print(f"  [PASS] Serializer bot_paused field verified: {data['bot_paused']} (Bot is Active/ON)")

    # 4. Test Takeover action (Turn Bot OFF)
    factory = APIRequestFactory()
    view = ConversationViewSet.as_view({'post': 'takeover'})
    req = factory.post(f'/api/conversations/{convo.id}/takeover/')
    force_authenticate(req, user=user)
    res = view(req, pk=str(convo.id))
    assert res.status_code == 200, f"Takeover failed with {res.status_code}"

    contact.refresh_from_db()
    assert contact.bot_paused is True, "Contact bot_paused was not set to True on takeover!"
    
    # Check serializer after takeover
    data_after_takeover = ConversationSerializer(convo).data
    assert data_after_takeover['bot_paused'] is True, "Serializer bot_paused should be True after takeover"
    print(f"  [PASS] Takeover executed: contact.bot_paused is now {contact.bot_paused} (Bot is Paused/OFF)")

    # 5. Test Resume Bot action (Turn Bot ON)
    view_resume = ConversationViewSet.as_view({'post': 'resume_bot'})
    req_resume = factory.post(f'/api/conversations/{convo.id}/resume_bot/')
    force_authenticate(req_resume, user=user)
    res_resume = view_resume(req_resume, pk=str(convo.id))
    assert res_resume.status_code == 200, f"Resume bot failed with {res_resume.status_code}"

    contact.refresh_from_db()
    assert contact.bot_paused is False, "Contact bot_paused was not set to False on resume_bot!"
    data_after_resume = ConversationSerializer(convo).data
    assert data_after_resume['bot_paused'] is False, "Serializer bot_paused should be False after resume"
    print(f"  [PASS] Resume Bot executed: contact.bot_paused is now {contact.bot_paused} (Bot is Resumed/ON)")

    print("\n" + "=" * 70)
    print("ALL BOT TOGGLE & SERIALIZATION VERIFICATIONS PASSED!")
    print("=" * 70)

if __name__ == '__main__':
    test_bot_toggle_integrity()
