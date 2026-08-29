import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Clients and Gmail Config in MongoDB ===")
for c in db['api_client'].find():
    print(f"\nClient ID: {c.get('_id')}")
    print(f"Name: {c.get('company_name') or c.get('name') or c.get('business_name')}")
    print(f"gmail_enabled: {c.get('gmail_enabled')}")
    g_conf = c.get('gmail_config') or {}
    print(f"Gmail email_address: {g_conf.get('email_address')}")
    print(f"Gmail has token: {bool(g_conf.get('token'))}")
    print(f"Gmail has refresh_token: {bool(g_conf.get('refresh_token'))}")
    print(f"Gmail client_id: {bool(g_conf.get('client_id'))}")
