import pymongo
import os
import sys
import json
from bson import json_util
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

target_emails = ['ai.mall@uwo24.com', 'support@uwo24.com']

for email in target_emails:
    print("=" * 80)
    print(f"USER RECORD: {email}")
    print("=" * 80)
    user = db['api_user'].find_one({'$or': [{'email': email}, {'username': email}]})
    if not user:
        print(f"No user found for {email}")
        continue

    # Clean password for display
    user_display = dict(user)
    if 'password' in user_display:
        pwd = user_display['password']
        algo = pwd.split('$')[0] if isinstance(pwd, str) and '$' in pwd else 'hashed'
        user_display['password'] = f"[HASHED: {algo}...]"

    print(json.dumps(user_display, default=json_util.default, indent=2))

    # Check client
    cid = user.get('client_id')
    print("\n--- LINKED CLIENT WORKSPACE ---")
    if cid:
        client_doc = db['api_client'].find_one({'_id': cid})
        if client_doc:
            print(json.dumps(client_doc, default=json_util.default, indent=2))
        else:
            print(f"client_id {cid} is set on user, but NO document exists in api_client!")
    else:
        print("client_id is NULL / None on this user document.")

    # Check related data in other collections
    uid = user['_id']
    msg_count = db['api_message'].count_documents({'$or': [{'sender_id': uid}, {'assigned_to_id': uid}]})
    convo_count = db['api_conversation'].count_documents({'assigned_to_id': uid})
    contact_count = db['api_contact'].count_documents({'client_id': cid}) if cid else 0
    auto_count = db['api_automation'].count_documents({'client_id': cid}) if cid else 0
    
    print(f"\n--- RELATED COUNTS ---")
    print(f"Messages assigned/sent: {msg_count}")
    print(f"Conversations assigned: {convo_count}")
    if cid:
        print(f"Client contacts count: {contact_count}")
        print(f"Client automations count: {auto_count}")
    print("\n")
