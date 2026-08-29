import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, requests, pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

# Find client with whatsapp_waba_id
c = db['api_client'].find_one({'whatsapp_waba_id': {'$ne': None, '$ne': ''}})
if not c:
    print("No client found with whatsapp_waba_id")
    sys.exit(0)

waba_id = c.get('whatsapp_waba_id')
token = c.get('whatsapp_access_token')

print(f"Client: {c.get('name')}")
print(f"WABA ID: {waba_id}")
print(f"Token: {token[:15]}...")

url = f"https://graph.facebook.com/v19.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}"}
res = requests.get(url, headers=headers)
print("Meta API Status Code:", res.status_code)
data = res.json()
print("Total templates returned by Meta:", len(data.get('data', [])))
for idx, tmpl in enumerate(data.get('data', []), 1):
    print(f"\n--- Template #{idx} ---")
    print(f"Name: {tmpl.get('name')}")
    print(f"Language: {tmpl.get('language')}")
    print(f"Status: {tmpl.get('status')}")
    print(f"Category: {tmpl.get('category')}")
    print(f"Components: {tmpl.get('components')}")
