import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import re
import pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Fixing Channels for All Conversations and Contacts based on Real Messages ===")

all_messages = list(db['api_message'].find().sort('_id', -1))
address_to_channel = {}
for m in all_messages:
    ch = m.get('channel')
    if not ch:
        continue
    from_addr = str(m.get('from_address') or '').strip()
    to_addr = str(m.get('to_address') or '').strip()
    
    for addr in [from_addr, to_addr]:
        if not addr or addr in ('SYSTEM', 'WHATSAPP_SYSTEM'):
            continue
        if addr not in address_to_channel:
            address_to_channel[addr] = ch.upper()

print(f"Mapped {len(address_to_channel)} addresses to channels")

fixed_convos = 0
for convo in db['api_conversation'].find():
    cid = convo.get('contact_platform_id') or ''
    digits = re.sub(r'\D', '', str(cid))
    
    actual_channel = None
    candidate_keys = [cid, digits, f"+{digits}"]
    if len(digits) == 10:
        candidate_keys.extend([f"91{digits}", f"+91{digits}"])
    elif digits.startswith('91') and len(digits) == 12:
        candidate_keys.extend([digits[2:], f"+{digits}"])
        
    for k in candidate_keys:
        if k in address_to_channel:
            actual_channel = address_to_channel[k]
            break
            
    if actual_channel and convo.get('channel') != actual_channel:
        print(f"Fixing Convo {cid}: {convo.get('channel')} -> {actual_channel}")
        db['api_conversation'].update_one(
            {'_id': convo['_id']},
            {'$set': {'channel': actual_channel}}
        )
        db['api_contact'].update_one(
            {'client_id': convo.get('client_id'), '$or': [{'platform_id': cid}, {'phone_number': cid}, {'platform_id': digits}, {'phone_number': digits}]},
            {'$set': {'preferred_channel': actual_channel}}
        )
        fixed_convos += 1

print(f"Successfully fixed channels for {fixed_convos} conversations!")

print("\n=== Gurumukh P Ahuja Convo After Fix ===")
g_convo = db['api_conversation'].find_one({'$or': [{'contact_platform_id': '4114184658605862'}, {'contact_platform_id': {'$regex': '4114184658605862'}}]})
print(f"Contact ID: {g_convo.get('contact_platform_id')} | Channel: {g_convo.get('channel')}")
