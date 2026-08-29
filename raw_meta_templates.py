import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, requests, pymongo, json
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]
c = db['api_client'].find_one({'whatsapp_waba_id': {'$ne': None, '$ne': ''}})
waba_id = c.get('whatsapp_waba_id')
token = c.get('whatsapp_access_token')

url = f"https://graph.facebook.com/v19.0/{waba_id}/message_templates"
headers = {"Authorization": f"Bearer {token}"}
res = requests.get(url, headers=headers)
data = res.json()
print(json.dumps(data, indent=2))
