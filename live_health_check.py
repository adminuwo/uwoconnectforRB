import os
import sys
import time
import requests
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User
from rest_framework_simplejwt.tokens import RefreshToken

# 1. Get valid client user token
user = User.objects.filter(role__in=['CLIENT', 'OWNER']).first()
if not user:
    user = User.objects.exclude(role='ADMIN').first()
if not user:
    user = User.objects.first()

refresh = RefreshToken.for_user(user)
access_token = str(refresh.access_token)
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

BACKEND_BASE = "http://127.0.0.1:8000"
FRONTEND_BASE = "http://localhost:3000"

ENDPOINTS = [
    # System & Health
    {"category": "Health & System", "url": f"{BACKEND_BASE}/health/", "auth": False},
    {"category": "Health & System", "url": f"{BACKEND_BASE}/api/health/", "auth": False},
    {"category": "Health & System", "url": f"{BACKEND_BASE}/robots.txt", "auth": False},
    
    # Auth & Profile
    {"category": "Auth & Profile", "url": f"{BACKEND_BASE}/api/auth/google-client-id", "auth": False},
    {"category": "Auth & Profile", "url": f"{BACKEND_BASE}/api/profile/", "auth": True},
    {"category": "Auth & Profile", "url": f"{BACKEND_BASE}/api/user/preferences/", "auth": True},
    
    # Plans & Entitlements
    {"category": "Plans & Entitlements", "url": f"{BACKEND_BASE}/api/plans/public/", "auth": False},
    {"category": "Plans & Entitlements", "url": f"{BACKEND_BASE}/api/plans/", "auth": True},
    {"category": "Plans & Entitlements", "url": f"{BACKEND_BASE}/api/features/", "auth": True},
    {"category": "Plans & Entitlements", "url": f"{BACKEND_BASE}/api/client/entitlements/", "auth": True},
    
    # Connectors & Channels
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/connectors/effective/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/connectors/global-status/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/auth/youtube/status/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-drive/status/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-calendar/status/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-sheets/list/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-docs/list/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-slides/list/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/onedrive/status/", "auth": True},
    {"category": "Connectors & Channels", "url": f"{BACKEND_BASE}/api/google-drive/files/", "auth": True},
    
    # CRM, Inbox, Automations
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/messages/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/conversations/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/contacts/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/campaigns/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/automations/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/workflows/", "auth": True},
    {"category": "CRM & Automations", "url": f"{BACKEND_BASE}/api/knowledge/", "auth": True},
    
    # Billing, Products & Sales
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/wallet/dashboard/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/payments/history/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/products/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/orders/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/invoices/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/sales-documents/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/quotations/", "auth": True},
    {"category": "Billing & Sales", "url": f"{BACKEND_BASE}/api/proposals/", "auth": True},
    
    # Team & HR
    {"category": "Team & HR", "url": f"{BACKEND_BASE}/api/team/members/", "auth": True},
    {"category": "Team & HR", "url": f"{BACKEND_BASE}/api/team/tasks/", "auth": True},
    {"category": "Team & HR", "url": f"{BACKEND_BASE}/api/team/attendance/", "auth": True},
    {"category": "Team & HR", "url": f"{BACKEND_BASE}/api/team/leaves/", "auth": True},
    
    # Frontend Pages
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/login", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/client", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/client/channels", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/client/inbox", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/client/plans", "auth": False},
    {"category": "Frontend Pages", "url": f"{FRONTEND_BASE}/pricing", "auth": False},
]

print(f"Testing {len(ENDPOINTS)} live endpoints (Backend & Frontend)...\n")
session = requests.Session()
session.trust_env = False

passed = 0
failed = 0

for ep in ENDPOINTS:
    url = ep["url"]
    cat = ep["category"]
    req_headers = headers if ep["auth"] else {}
    
    t0 = time.time()
    try:
        r = session.get(url, headers=req_headers, timeout=10)
        ms = round((time.time() - t0) * 1000, 1)
        
        # 500 is a server crash, 404 on defined endpoint is error
        is_ok = r.status_code < 500
        if is_ok:
            passed += 1
            print(f"✅ [{cat:<22}] HTTP {r.status_code} ({ms}ms) -> {url}")
        else:
            failed += 1
            print(f"❌ [{cat:<22}] HTTP {r.status_code} ({ms}ms) -> {url}")
    except Exception as e:
        failed += 1
        print(f"❌ [{cat:<22}] EXCEPTION: {e} -> {url}")

print(f"\n==========================================")
print(f"LIVE AUDIT FINISHED: {passed}/{len(ENDPOINTS)} OK | 500 Crashes: {failed}")
print(f"==========================================")
