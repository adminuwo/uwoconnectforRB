import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Top 10 Conversations Now in DB (Sorted by last_message_at) ===")
for c in db['api_conversation'].find().sort('last_message_at', -1).limit(10):
    summary = (c.get('last_message_summary') or '').replace('\n', ' ')[:40]
    print(f"{c.get('contact_platform_id'):<18} | {str(c.get('last_message_at')):<26} | {summary}")
