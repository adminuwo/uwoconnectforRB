import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Email Accounts in MongoDB ===")
for ea in db['api_emailaccount'].find():
    print(f"ID: {ea.get('_id')} | client_id: {ea.get('client_id')} | provider: {ea.get('provider')} | email: {ea.get('email_address')}")

print("\n=== Email Messages for Unified Web Options in MongoDB ===")
c_id = pymongo.MongoClient(os.getenv('MONGODB_URI'))[os.getenv('MONGODB_DB_NAME')]['api_client'].find_one({'name': 'Unified Web Options Pvt Ltd'})['_id']
print(f"Unified Web Options Client ID: {c_id}")
for em in db['api_emailmessage'].find({'client_id': c_id}).sort('_id', -1).limit(5):
    print(f"Sender: {em.get('sender_email')} | To: {em.get('to_recipients')} | Subject: {em.get('subject')} | Created: {em.get('created_at')}")
