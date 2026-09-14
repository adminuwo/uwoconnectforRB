import pymongo
import os
import sys
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client['aisaconnect_db_v5']

# 1. Identify all users matching ai.mall@uwo24.com
ai_users = list(db['api_user'].find({
    '$or': [
        {'email': {'$regex': '^ai\\.mall@uwo24\\.com$', '$options': 'i'}},
        {'username': {'$regex': '^ai\\.mall@uwo24\\.com$', '$options': 'i'}}
    ]
}))

user_ids = [u['_id'] for u in ai_users]
client_ids = [u['client_id'] for u in ai_users if u.get('client_id')]

# Also include the restored 6a9e52db63911f59214c5578 client if it exists
for c in db['api_client'].find({'$or': [{'business_name': {'$regex': 'AI Mall', '$options': 'i'}}, {'_id': pymongo.collection.ObjectId('6a9e52db63911f59214c5578')}]}):
    if c['_id'] not in client_ids:
        client_ids.append(c['_id'])

print("=" * 80)
print("DELETION TARGETS FOR ai.mall@uwo24.com ONLY:")
print(f"Users to delete ({len(user_ids)}): {user_ids}")
print(f"Clients to delete ({len(client_ids)}): {client_ids}")
print("=" * 80)

if not user_ids and not client_ids:
    print("No data found for ai.mall@uwo24.com.")
    sys.exit(0)

# Collections to clean
collections_with_client = [
    'api_message',
    'api_conversation',
    'api_contact',
    'api_contactfollowup',
    'api_automation',
    'api_workflow',
    'api_workflowsession',
    'api_template',
    'api_campaign',
    'api_campaignfollowup',
    'api_salesdocument',
    'api_salesdocumentitem',
    'api_salesdocumentactivity',
    'api_salesdocumenttemplate',
    'api_invoice',
    'api_order',
    'api_product',
    'api_productpayment',
    'api_clientwallet',
    'api_walletledger',
    'api_walletrechargeorder',
    'api_teaminvite',
    'api_teammessage',
    'api_teamchannel',
    'api_teamchatmessage',
    'api_attendance',
    'api_leaverequest',
    'api_task',
    'api_project',
    'api_workreport',
    'api_auditlog',
    'api_conversationauditlog',
    'api_channelauditlog',
    'api_teammemberconnectoraccess',
    'api_clientconnectoraccess',
    'api_clientfeatureoverride',
    'api_clientsubscription',
    'api_broadcastentitlement',
    'api_broadcastusage',
    'api_emailaccount',
    'api_emailmessage',
    'api_emailautoreplyrule',
    'api_emailautomationworkflow',
    'api_emailteamnote',
    'api_knowledgedocument',
    'api_knowledgechunk',
    'api_guide',
    'api_guidestep',
    'api_guideprogress',
    'api_guidesection',
    'api_razorpayconnection',
    'api_qrauthsession',
    'api_linkeddevice',
    'api_userpreference',
    'api_passwordresetotp'
]

total_deleted = 0

# Delete from relational/feature collections
for coll in collections_with_client:
    if coll in db.list_collection_names():
        query = {'$or': []}
        if client_ids:
            query['$or'].append({'client_id': {'$in': client_ids}})
        if user_ids:
            query['$or'].extend([
                {'user_id': {'$in': user_ids}},
                {'sender_id': {'$in': user_ids}},
                {'assigned_to_id': {'$in': user_ids}},
                {'team_member_id': {'$in': user_ids}}
            ])
        res = db[coll].delete_many(query)
        if res.deleted_count > 0:
            print(f"Deleted {res.deleted_count} records from {coll}")
            total_deleted += res.deleted_count

# Delete client documents
if client_ids:
    c_res = db['api_client'].delete_many({'_id': {'$in': client_ids}})
    print(f"Deleted {c_res.deleted_count} records from api_client")
    total_deleted += c_res.deleted_count

# Delete user documents
if user_ids:
    u_res = db['api_user'].delete_many({'_id': {'$in': user_ids}})
    print(f"Deleted {u_res.deleted_count} records from api_user")
    total_deleted += u_res.deleted_count

print("=" * 80)
print(f"TOTAL DELETED RECORDS FOR ai.mall@uwo24.com: {total_deleted}")
print("=" * 80)

# Verify remaining users in DB to be 100% sure only ai.mall was touched
print("\n--- Remaining Users in Database ---")
for u in db['api_user'].find():
    print(f"  - {u['email']} (Role: {u.get('role')})")

print("\n--- Remaining Clients in Database ---")
for c in db['api_client'].find():
    print(f"  - {c.get('business_name')} (ID: {c['_id']})")
