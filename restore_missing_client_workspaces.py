import pymongo
import os
import sys
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
client = pymongo.MongoClient(os.getenv('MONGODB_URI'))
db = client[os.getenv('MONGODB_DB_NAME')]

clients_to_restore = [
    {
        '_id': pymongo.collection.ObjectId('6a9e52db63911f59214c5578'),
        'business_name': 'AI Mall',
        'meta_portfolio_name': 'AI-Mall Portfolio',
        'phone_number': '+919876543210',
        'address': '',
        'automation_enabled': True,
        'plan': 'Advanced',
        'assigned_plan_id': pymongo.collection.ObjectId('6a92723215a74712132680d4'),
        'status': 'ACTIVE',
        'whatsapp_enabled': True,
        'facebook_enabled': True,
        'instagram_enabled': True,
        'gmail_enabled': True,
        'selected_channels': ['whatsapp', 'facebook', 'instagram', 'gmail'],
        'billing_period': 'MONTHLY',
        'channel_access': {
            'whatsapp': True,
            'facebook': True,
            'instagram': True,
            'gmail': True
        },
        'greeting_enabled': True,
        'greeting_message': '',
        'greeting_buttons': [],
        'ai_enabled': False,
        'facebook_config': {},
        'instagram_config': {},
        'whatsapp_config': {},
        'gmail_config': {},
        'settings': {
            'meta_portfolio_name': 'AI-Mall Portfolio',
            'business_portfolio_name': 'AI-Mall Portfolio'
        },
        'is_agency': False,
        'parent_agency_id': None
    },
    {
        '_id': pymongo.collection.ObjectId('6a8d545c6e9bd5881927cce7'),
        'business_name': 'EFV Support',
        'meta_portfolio_name': None,
        'phone_number': '+91 96171 90909',
        'address': '',
        'automation_enabled': True,
        'plan': 'Advanced',
        'assigned_plan_id': pymongo.collection.ObjectId('6a92723215a74712132680d4'),
        'status': 'ACTIVE',
        'whatsapp_enabled': True,
        'facebook_enabled': True,
        'instagram_enabled': True,
        'gmail_enabled': True,
        'selected_channels': ['whatsapp', 'facebook', 'instagram', 'gmail'],
        'billing_period': 'MONTHLY',
        'channel_access': {
            'whatsapp': True,
            'facebook': True,
            'instagram': True,
            'gmail': True
        },
        'greeting_enabled': True,
        'greeting_message': '',
        'greeting_buttons': [],
        'ai_enabled': False,
        'facebook_config': {},
        'instagram_config': {},
        'whatsapp_config': {},
        'gmail_config': {},
        'settings': {},
        'is_agency': False,
        'parent_agency_id': None
    }
]

for cdoc in clients_to_restore:
    cid = cdoc['_id']
    existing = db['api_client'].find_one({'_id': cid})
    if existing:
        print(f"Client {cid} already exists: {existing.get('business_name')}")
    else:
        db['api_client'].insert_one(cdoc)
        print(f"Successfully restored Client {cid}: {cdoc['business_name']}")

print("\n--- Verifying Users and their Client linkages ---")
for email in ['ai.mall@uwo24.com', 'support@uwo24.com']:
    u = db['api_user'].find_one({'email': email})
    cid = u.get('client_id')
    c = db['api_client'].find_one({'_id': cid}) if cid else None
    print(f"User: {email} -> Client ID: {cid} -> Found: {c.get('business_name') if c else 'MISSING'}")
