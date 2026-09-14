import pymongo
import os
import sys
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

clients_map = {}
for c in db['api_client'].find():
    clients_map[str(c['_id'])] = {
        'business_name': c.get('business_name', 'N/A'),
        'plan': c.get('plan', 'N/A'),
        'is_agency': c.get('is_agency', False),
        'phone': c.get('phone_number', 'N/A')
    }

print("=" * 100)
print(f"{'#':<3} | {'Email':<28} | {'Role':<8} | {'Status':<9} | {'Name':<20} | {'Business / Workspace':<25}")
print("=" * 100)

users = list(db['api_user'].find())
for i, u in enumerate(users, 1):
    email = u.get('email', u.get('username', 'N/A'))
    role = u.get('role', 'N/A')
    status = u.get('status', 'N/A')
    name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or 'N/A'
    cid = str(u.get('client_id')) if u.get('client_id') else None
    cinfo = clients_map.get(cid, {}) if cid else {}
    bname = cinfo.get('business_name', 'No Workspace')
    plan = cinfo.get('plan', 'N/A')
    
    print(f"{i:<3} | {email:<28} | {role:<8} | {status:<9} | {name:<20} | {bname:<25}")
    print(f"    ↳ ID: {u['_id']} | Plan: {plan} | Meta Portfolio: {u.get('meta_portfolio_name', 'None')} (Eligible: {u.get('meta_portfolio_eligible', False)})")
print("=" * 100)

print("\n--- Client Workspaces in DB ---")
for c in db['api_client'].find():
    print(f"Client ID: {c['_id']} | Business: {c.get('business_name')} | Plan: {c.get('plan')} | Status: {c.get('status')}")
