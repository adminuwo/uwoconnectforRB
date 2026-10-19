import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from api.models import Message, Conversation, Client

c = Client.objects.filter(business_name='UWO Connect').first()

# Check Instagram conversations
convs = Conversation.objects.filter(client=c, channel='instagram')
print(f'Instagram conversations: {convs.count()}')
for conv in convs[:5]:
    msgs = Message.objects.filter(client=c, channel='INSTAGRAM').order_by('-created_at')[:3]
    print(f'  Conv: {conv.id} | {conv.contact_name or conv.external_id}')

# Check Instagram messages directly
ig_msgs = Message.objects.filter(client=c, channel='INSTAGRAM').order_by('-created_at')[:10]
print(f'\nInstagram messages in DB: {Message.objects.filter(client=c, channel="INSTAGRAM").count()}')
for m in ig_msgs:
    print(f'  [{m.message_type}] from={m.from_address} | {m.body[:80]}')

# All channels message count
print('\nMessages by channel:')
for ch in ['WHATSAPP', 'FACEBOOK', 'INSTAGRAM', 'GMAIL']:
    cnt = Message.objects.filter(client=c, channel=ch).count()
    print(f'  {ch}: {cnt}')
