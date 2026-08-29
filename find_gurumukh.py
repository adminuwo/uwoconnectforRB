import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Searching for 4114184658605862 or Gurumukh ===")

contact = db['api_contact'].find_one({'$or': [{'platform_id': '4114184658605862'}, {'name': {'$regex': 'Gurumukh', '$options': 'i'}}]})
print("Contact:", contact)

convo = db['api_conversation'].find_one({'$or': [{'contact_platform_id': '4114184658605862'}, {'contact_platform_id': {'$regex': '4114184658605862'}}]})
print("Convo:", convo)

msg = db['api_message'].find_one({'$or': [{'from_address': '4114184658605862'}, {'to_address': '4114184658605862'}]})
print("Message:", msg)
