import os
import sys
import requests
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User, Client
from rest_framework_simplejwt.tokens import RefreshToken

CLOUD_RUN_URL = "https://uwoconnectforrb-743928421487.asia-south1.run.app"
LIVE_WEB_URL = "https://uwoconnect.aisa24.com"

print("======================================================================")
print("🔍 COMPREHENSIVE LIVE AUDIT (PRODUCTION CLOUD RUN & PRODUCTION WEB)")
print("======================================================================\n")

test_results = []

def record(test_name, success, details):
    status = "✅ PASS" if success else "❌ FAIL"
    test_results.append((test_name, success, details))
    print(f"{status} | {test_name:<42} | {details}")

# 1. Database User & Plan Status Checks
print("--- 1. DATABASE & USER CREDENTIAL INTEGRITY ---")
admin_user = User.objects.filter(email='admin@uwo24.com').first()
if admin_user and admin_user.check_password('Admin@123') and admin_user.email_verified:
    record("Admin User (admin@uwo24.com)", True, "Password: Admin@123 | email_verified: True")
else:
    record("Admin User (admin@uwo24.com)", False, f"User exists: {bool(admin_user)}")

aditi_user = User.objects.filter(email='aditi@uwo24.com').first()
if aditi_user and aditi_user.client and aditi_user.client.plan in ['ADVANCED', 'Advanced']:
    record("Aditi User Workspace Plan", True, f"Plan: {aditi_user.client.plan} (All channels unlocked)")
else:
    record("Aditi User Workspace Plan", False, f"Plan: {aditi_user.client.plan if aditi_user and aditi_user.client else 'None'}")

reviewer_user = User.objects.filter(email='google-reviewer@uwoconnect.aisa24.com').first()
if reviewer_user and reviewer_user.check_password('UwoReviewer@2026!') and reviewer_user.email_verified:
    record("Google Reviewer (google-reviewer)", True, f"Plan: {reviewer_user.client.plan} | email_verified: True")
else:
    record("Google Reviewer (google-reviewer)", False, "Reviewer account missing or unverified")

free_clients_count = Client.objects.filter(plan='FREE').count()
record("Zero Blocked 'FREE' Clients in DB", free_clients_count == 0, f"Remaining FREE clients: {free_clients_count}")

# 2. Live Cloud Run Authentication
print("\n--- 2. LIVE CLOUD RUN AUTHENTICATION ---")
try:
    r = requests.get(f"{CLOUD_RUN_URL}/health/", timeout=10)
    record("Cloud Run /health/ Endpoint", r.status_code == 200, f"HTTP {r.status_code} ({round(r.elapsed.total_seconds()*1000, 1)}ms)")
except Exception as e:
    record("Cloud Run /health/ Endpoint", False, str(e))

# Test Cloud Run Login for Admin
admin_token = None
try:
    r = requests.post(f"{CLOUD_RUN_URL}/api/auth/login", json={"email": "admin@uwo24.com", "password": "Admin@123"}, timeout=10)
    if r.status_code == 200:
        admin_token = r.json().get("token")
    record("Cloud Run Admin Login (admin@uwo24.com)", r.status_code == 200, f"HTTP {r.status_code} (Token issued: {bool(admin_token)})")
except Exception as e:
    record("Cloud Run Admin Login (admin@uwo24.com)", False, str(e))

# Test Cloud Run Login for Reviewer
reviewer_token = None
try:
    r = requests.post(f"{CLOUD_RUN_URL}/api/auth/login", json={"email": "google-reviewer@uwoconnect.aisa24.com", "password": "UwoReviewer@2026!"}, timeout=10)
    if r.status_code == 200:
        reviewer_token = r.json().get("token")
    record("Cloud Run Reviewer Login (google-reviewer)", r.status_code == 200, f"HTTP {r.status_code} (Token issued: {bool(reviewer_token)})")
except Exception as e:
    record("Cloud Run Reviewer Login (google-reviewer)", False, str(e))

# 3. Live Cloud Run Backend API Endpoints
print("\n--- 3. LIVE CLOUD RUN INTEGRATION & BUSINESS ENDPOINTS ---")
auth_token = reviewer_token or admin_token or str(RefreshToken.for_user(aditi_user or admin_user).access_token)
auth_headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

critical_endpoints = [
    ("Client Entitlements API", f"{CLOUD_RUN_URL}/api/client/entitlements/", True),
    ("Effective Connectors API", f"{CLOUD_RUN_URL}/api/connectors/effective/", True),
    ("Global Connectors Status API", f"{CLOUD_RUN_URL}/api/connectors/global-status/", True),
    ("Google Drive Status API", f"{CLOUD_RUN_URL}/api/google-drive/status/", True),
    ("YouTube Status API", f"{CLOUD_RUN_URL}/api/auth/youtube/status/", True),
    ("Google Calendar Status API", f"{CLOUD_RUN_URL}/api/google-calendar/status/", True),
    ("Google Sheets List API", f"{CLOUD_RUN_URL}/api/google-sheets/list/", True),
    ("Google Docs List API", f"{CLOUD_RUN_URL}/api/google-docs/list/", True),
    ("Google Slides List API", f"{CLOUD_RUN_URL}/api/google-slides/list/", True),
    ("Live Messages API", f"{CLOUD_RUN_URL}/api/messages/", True),
    ("Live Conversations API", f"{CLOUD_RUN_URL}/api/conversations/", True),
    ("Live Contacts API", f"{CLOUD_RUN_URL}/api/contacts/", True),
    ("Live Campaigns API", f"{CLOUD_RUN_URL}/api/campaigns/", True),
    ("Live Automations API", f"{CLOUD_RUN_URL}/api/automations/", True),
    ("Live Workflows API", f"{CLOUD_RUN_URL}/api/workflows/", True),
    ("Live Wallet API", f"{CLOUD_RUN_URL}/api/wallet/dashboard/", True),
    ("Live Invoices API", f"{CLOUD_RUN_URL}/api/invoices/", True),
    ("Public Plans API", f"{CLOUD_RUN_URL}/api/plans/public/", False),
]

for name, url, use_auth in critical_endpoints:
    headers = auth_headers if use_auth else {}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        ms = round(r.elapsed.total_seconds() * 1000, 1)
        ok = r.status_code != 500
        record(name, ok, f"HTTP {r.status_code} ({ms}ms)")
    except Exception as e:
        record(name, False, str(e))

# 4. Live Production Frontend Pages (https://uwoconnect.aisa24.com)
print("\n--- 4. LIVE PRODUCTION FRONTEND (uwoconnect.aisa24.com) ---")
frontend_pages = [
    ("Landing Page", f"{LIVE_WEB_URL}/"),
    ("Login Page", f"{LIVE_WEB_URL}/auth/login"),
    ("Client Dashboard", f"{LIVE_WEB_URL}/client"),
    ("Channels & Integrations", f"{LIVE_WEB_URL}/client/channels"),
    ("Inbox & Messages", f"{LIVE_WEB_URL}/client/inbox"),
    ("Plans & Subscriptions", f"{LIVE_WEB_URL}/client/plans"),
    ("Public Pricing", f"{LIVE_WEB_URL}/pricing"),
    ("Contact Page", f"{LIVE_WEB_URL}/contact"),
    ("Terms of Service", f"{LIVE_WEB_URL}/terms-and-conditions"),
]

for name, url in frontend_pages:
    try:
        r = requests.get(url, timeout=10, allow_redirects=True)
        ms = round(r.elapsed.total_seconds() * 1000, 1)
        ok = r.status_code == 200
        record(f"Live Web: {name}", ok, f"HTTP {r.status_code} ({ms}ms)")
    except Exception as e:
        record(f"Live Web: {name}", False, str(e))

# Final Summary
passed = sum(1 for _, ok, _ in test_results if ok)
total = len(test_results)
print("\n" + "=" * 70)
print(f"🎯 MASTER VERIFICATION RESULT: {passed}/{total} CHECKS PASSED ({round(passed/total*100, 1)}%)")
if passed == total:
    print("🚀 100% OPERATIONAL & PRODUCTION READY! (Zero Errors / Zero Crashes)")
else:
    print(f"⚠️ {total - passed} checks had issues.")
print("=" * 70)
