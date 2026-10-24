import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.hashers import make_password
import pymongo
from dotenv import load_dotenv

load_dotenv()
db = pymongo.MongoClient(os.getenv('MONGODB_URI'))['aisaconnect_db_v5']
hashed = make_password('admin123')

res = db['api_user'].update_many(
    {'email': 'ai.mall@uwo24.com'},
    {'$set': {'password': hashed, 'is_active': True, 'status': 'APPROVED'}}
)
print(f"Updated ai.mall@uwo24.com in aisaconnect_db_v5: matched {res.matched_count}, modified {res.modified_count}")

# Verify with requests to Cloud Run endpoint
import requests
r = requests.post(
    'https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/login',
    json={'email': 'ai.mall@uwo24.com', 'password': 'admin123'}
)
print(f"Cloud Run Login Status: {r.status_code}")
if r.status_code == 200:
    print("SUCCESS: Logged in to Cloud Run successfully! Token received.")
else:
    print(f"Cloud Run response: {r.text}")
