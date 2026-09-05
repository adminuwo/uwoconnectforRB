import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Message, Client, Contact

print("=== RECENT MESSAGES ===")
msgs = Message.objects.all().order_by('-created_at')[:15]
for m in msgs:
    print(f"ID: {m.id} | Type: {m.message_type} | Channel: {m.channel} | Status: {m.status} | From: {m.from_address} -> To: {m.to_address}")
    print(f"   Body: {repr(m.body)}")
    print(f"   Meta: {m.metadata}")
    print(f"   Created: {m.created_at}")
    print("-" * 50)
