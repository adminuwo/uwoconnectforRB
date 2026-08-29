import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, pymongo
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

c = db['api_client'].find_one({'_id': ObjectId('6a5338debec6daea1165d2b3')})
print("=== Client Details ===")
print("Client Name:", c.get('company_name') or c.get('business_name'))
print("gmail_enabled:", c.get('gmail_enabled'))
print("gmail_config email_address:", c.get('gmail_config', {}).get('email_address'))
print("outlook_enabled:", c.get('outlook_enabled'))
print("outlook_config email_address:", c.get('outlook_config', {}).get('email_address'))

print("\n=== Email Messages in DB for this client ===")
for em in db['api_emailmessage'].find({'client_id': ObjectId('6a5338debec6daea1165d2b3')}).sort('_id', -1).limit(5):
    print(f"ID: {em.get('_id')} | Sender: {em.get('sender_email')} | To: {em.get('to_recipients')} | Subject: {em.get('subject')} | Created: {em.get('created_at')}")
