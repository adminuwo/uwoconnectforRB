import pymongo
import os
import sys
from collections import Counter
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

targets = [
    ('ai.mall@uwo24.com', pymongo.collection.ObjectId('6a9e52db63911f59214c5578')),
    ('support@uwo24.com', pymongo.collection.ObjectId('6a8d545c6e9bd5881927cce7'))
]

for email, cid in targets:
    print("=" * 70)
    print(f"ANALYTICS & CHANNELS FOR {email} (Client ID: {cid})")
    print("=" * 70)

    # Channel breakdown in conversations
    convos = list(db['api_conversation'].find({'client_id': cid}))
    channels = Counter(c.get('channel') for c in convos)
    print(f"Total Conversations: {len(convos)}")
    for ch, count in channels.items():
        print(f"  - Channel {ch}: {count} threads")

    # Channel breakdown in messages
    msgs = list(db['api_message'].find({'client_id': cid}, {'channel': 1, 'message_type': 1}))
    m_channels = Counter(m.get('channel') for m in msgs)
    m_types = Counter(m.get('message_type') for m in msgs)
    print(f"\nTotal Messages: {len(msgs)}")
    for ch, count in m_channels.items():
        print(f"  - {ch}: {count} messages")
    print(f"Message Types: {dict(m_types)}")

    # Contacts count
    contact_count = db['api_contact'].count_documents({'client_id': cid})
    print(f"\nTotal CRM Contacts: {contact_count}")
    print("\n")
