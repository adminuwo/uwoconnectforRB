import os
import re
import pymongo
from dotenv import load_dotenv

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

print("=== Starting Comprehensive Conversation & Contact Timestamp Sync ===")

all_messages = list(db['api_message'].find().sort('_id', -1))
print(f"Total messages in DB: {len(all_messages)}")

# Map latest message per address
address_to_latest_msg = {}
for m in all_messages:
    from_addr = str(m.get('from_address') or '').strip()
    to_addr = str(m.get('to_address') or '').strip()
    
    for addr in [from_addr, to_addr]:
        if not addr or addr == 'SYSTEM' or addr == 'WHATSAPP_SYSTEM':
            continue
        if addr not in address_to_latest_msg:
            address_to_latest_msg[addr] = m

print(f"Found {len(address_to_latest_msg)} unique addresses with messages")

updated_convos = 0
for convo in db['api_conversation'].find():
    cid = convo.get('contact_platform_id') or ''
    digits = re.sub(r'\D', '', str(cid))
    
    # Try all variations of the address
    matched_msg = None
    candidate_keys = [cid, digits, f"+{digits}"]
    if len(digits) == 10:
        candidate_keys.extend([f"91{digits}", f"+91{digits}"])
    elif digits.startswith('91') and len(digits) == 12:
        candidate_keys.extend([digits[2:], f"+{digits}"])
        
    for k in candidate_keys:
        if k in address_to_latest_msg:
            matched_msg = address_to_latest_msg[k]
            break
            
    if matched_msg:
        msg_time = matched_msg.get('created_at')
        msg_body = matched_msg.get('body') or ''
        db['api_conversation'].update_one(
            {'_id': convo['_id']},
            {'$set': {
                'last_message_at': msg_time,
                'last_message_summary': msg_body,
                'updated_at': msg_time
            }}
        )
        db['api_contact'].update_one(
            {'client_id': convo.get('client_id'), '$or': [{'platform_id': cid}, {'phone_number': cid}, {'platform_id': digits}, {'phone_number': digits}]},
            {'$set': {'updated_at': msg_time}}
        )
        updated_convos += 1

print(f"Successfully synced {updated_convos} conversations!")
print("\n=== Top 10 Conversations Now in DB ===")
for c in db['api_conversation'].find().sort('last_message_at', -1).limit(10):
    print(f"{c.get('contact_platform_id'):<18} | {str(c.get('last_message_at')):<26} | {(c.get('last_message_summary') or '')[:40]}")
