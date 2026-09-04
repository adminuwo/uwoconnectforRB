import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Contact, Message, Client
c = Contact.objects.filter(phone_number__icontains='7694045090').first()
print(f"Contact: {c.id} | Name: {c.name} | Phone: {c.phone_number} | Client: {c.client_id} ({c.client.business_name})")

msgs = Message.objects.filter(client=c.client).filter(from_address__in=['917694045090', '+917694045090', '7694045090']) | Message.objects.filter(client=c.client).filter(to_address__in=['917694045090', '+917694045090', '7694045090'])

print(f"Total messages for this contact: {msgs.count()}")
for m in msgs.order_by('-created_at')[:10]:
    print(f"ID: {m.id} | {m.message_type} | {m.status} | From: {m.from_address} -> To: {m.to_address}")
    print(f"   Body: {repr(m.body)}")
    print(f"   Created: {m.created_at}")
