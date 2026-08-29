import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Client
from api.services.gmail_service import sync_incoming_gmails

print("=== Testing Gmail Sync for all clients with gmail_enabled ===")
for client in Client.objects.filter(gmail_enabled=True):
    print(f"\nClient ID: {client.id}")
    print(f"Gmail Config: email_address={client.gmail_config.get('email_address') if client.gmail_config else None}")
    try:
        count = sync_incoming_gmails(client)
        print(f"Result: Synced {count} new emails!")
    except Exception as e:
        import traceback
        print(f"Error during sync: {e}")
        traceback.print_exc()

if not Client.objects.filter(gmail_enabled=True).exists():
    print("No client with gmail_enabled=True found!")
