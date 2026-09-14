import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
import requests
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User
from rest_framework_simplejwt.tokens import RefreshToken

BASE_URL = 'http://127.0.0.1:8000'

# 1. Get tokens
admin_user = User.objects.filter(role='ADMIN').first()
client_user = User.objects.filter(email='ai.mall@uwo24.com').first()

admin_token = str(RefreshToken.for_user(admin_user).access_token) if admin_user else None
client_token = str(RefreshToken.for_user(client_user).access_token) if client_user else None

print(f"Admin: {admin_user.email} -> Token OK")
print(f"Client: {client_user.email} -> Token OK\n")

admin_headers = {'Authorization': f'Bearer {admin_token}'}
client_headers = {'Authorization': f'Bearer {client_token}'}

# Group endpoints
endpoints = [
    # --- Public Endpoints ---
    ("Public", "Health Check", "/api/health", {}),
    ("Public", "Public Plans", "/api/plans/public/", {}),
    ("Public", "WhiteLabel Config", "/api/whitelabel/config", {}),

    # --- Auth & Profile ---
    ("Auth", "Admin Profile", "/api/profile/", admin_headers),
    ("Auth", "Client Profile", "/api/profile/", client_headers),
    ("Auth", "Client Entitlements", "/api/client/entitlements/", client_headers),
    ("Auth", "User Preferences", "/api/user/preferences/", client_headers),

    # --- Admin Endpoints ---
    ("Admin", "Overview", "/api/admin/overview/", admin_headers),
    ("Admin", "Admin Stats", "/api/admin/stats", admin_headers),
    ("Admin", "Clients Directory", "/api/admin/clients-directory/", admin_headers),
    ("Admin", "Intelligence Stats", "/api/admin/client-intelligence/stats/", admin_headers),
    ("Admin", "Intelligence Clients", "/api/admin/client-intelligence/clients/", admin_headers),
    ("Admin", "Users List", "/api/admin/users", admin_headers),
    ("Admin", "Messages List", "/api/admin/messages", admin_headers),
    ("Admin", "Automations List", "/api/admin/automations", admin_headers),
    ("Admin", "All Teams", "/api/admin/all-team/", admin_headers),
    ("Admin", "Team Summary", "/api/admin/team-summary/", admin_headers),
    ("Admin", "Team Analytics", "/api/admin/team-analytics/", admin_headers),
    ("Admin", "All Projects", "/api/admin/all-projects/", admin_headers),
    ("Admin", "All Channels", "/api/admin/all-channels/", admin_headers),
    ("Admin", "All Sales", "/api/admin/all-sales/", admin_headers),
    ("Admin", "All Quotations", "/api/admin/all-quotations/", admin_headers),
    ("Admin", "All Proposals", "/api/admin/all-proposals/", admin_headers),
    ("Admin", "All Invoices", "/api/admin/all-invoices/", admin_headers),
    ("Admin", "All Reports", "/api/admin/all-reports/", admin_headers),
    ("Admin", "All Products", "/api/admin/all-products/", admin_headers),
    ("Admin", "Global Search", "/api/admin/global-search/", admin_headers),
    ("Admin", "Channel Access Global", "/api/admin/channel-access/global/", admin_headers),
    ("Admin", "Channel Access Matrix", "/api/admin/channel-access/matrix/", admin_headers),
    ("Admin", "Channel Audit Logs", "/api/admin/channel-access/audit-logs/", admin_headers),
    ("Admin", "Wallet Overview", "/api/admin/wallet/overview/", admin_headers),
    ("Admin", "Wallet Rates", "/api/admin/wallet/rates/", admin_headers),
    ("Admin", "Plans List", "/api/plans/", admin_headers),
    ("Admin", "Features List", "/api/features/", admin_headers),
    ("Admin", "Plan Features", "/api/plan-features/", admin_headers),
    ("Admin", "WhiteLabel Revenue", "/api/admin/whitelabel/revenue/", admin_headers),

    # --- Client / Core Feature Endpoints ---
    ("Client", "Client Stats", "/api/client/stats/", client_headers),
    ("Client", "Client Messages", "/api/messages/", client_headers),
    ("Client", "Sales Dashboard", "/api/razorpay/sales/dashboard/", client_headers),
    ("Client", "Sales Analytics", "/api/sales/analytics/", client_headers),
    ("Client", "Wallet Dashboard", "/api/wallet/dashboard/", client_headers),
    ("Client", "Broadcast Entitlements", "/api/broadcasts/entitlement/", client_headers),
    ("Client", "Effective Connectors", "/api/connectors/effective/", client_headers),
    ("Client", "Global Connectors Status", "/api/connectors/global-status/", client_headers),
    ("Client", "Contacts", "/api/contacts/", client_headers),
    ("Client", "Conversations", "/api/conversations/", client_headers),
    ("Client", "Automations", "/api/automations/", client_headers),
    ("Client", "Workflows", "/api/workflows/", client_headers),
    ("Client", "Templates", "/api/templates/", client_headers),
    ("Client", "Campaigns", "/api/campaigns/", client_headers),
    ("Client", "Products", "/api/products/", client_headers),
    ("Client", "Orders", "/api/orders/", client_headers),
    ("Client", "Invoices", "/api/invoices/", client_headers),
    ("Client", "Sales Documents", "/api/sales-documents/", client_headers),
    ("Client", "Sales Doc Templates", "/api/sales-document-templates/", client_headers),
    ("Client", "Quotations", "/api/quotations/", client_headers),
    ("Client", "Proposals", "/api/proposals/", client_headers),
    ("Client", "Team Members", "/api/team/members/", client_headers),
    ("Client", "Team Projects", "/api/team/projects/", client_headers),
    ("Client", "Team Tasks", "/api/team/tasks/", client_headers),
    ("Client", "Team Attendance", "/api/team/attendance/", client_headers),
    ("Client", "Team Leaves", "/api/team/leaves/", client_headers),
    ("Client", "Team Channels", "/api/team/channels/", client_headers),
    ("Client", "Team Analytics", "/api/team/analytics/", client_headers),
    ("Client", "Guides", "/api/guides/", client_headers),
    ("Client", "Email Accounts", "/api/email/accounts/", client_headers),
    ("Client", "Email Messages", "/api/email/messages/", client_headers),
    ("Client", "Email Analytics", "/api/email/analytics/", client_headers),
    ("Client", "Monitoring Stats", "/api/monitoring/stats/", client_headers),
    ("Client", "Monitoring Analytics", "/api/monitoring/analytics/", client_headers),
    ("Client", "Audit Logs", "/api/audit-logs/", client_headers),
    ("Client", "WebRTC Config", "/api/webrtc/config/", client_headers),
    ("Client", "WebRTC History", "/api/webrtc/history/", client_headers),
]

passed = 0
failed = 0
results = []

print(f"{'Category':<10} | {'Endpoint Name':<26} | {'Path':<38} | {'Status':<6} | {'Time (ms)'}")
print("-" * 95)

for category, name, path, headers in endpoints:
    url = f"{BASE_URL}{path}"
    start = time.time()
    try:
        r = requests.get(url, headers=headers, timeout=15)
        dur = int((time.time() - start) * 1000)
        status = r.status_code
        if status in [200, 201]:
            mark = "PASS"
            passed += 1
        elif status == 403:
            mark = "PERM"
            passed += 1
        else:
            mark = "FAIL"
            failed += 1
        results.append((category, name, path, status, dur, mark, r.text[:80]))
        print(f"{category:<10} | {name:<26} | {path:<38} | {status:<6} | {dur}ms ({mark})")
    except Exception as e:
        dur = int((time.time() - start) * 1000)
        failed += 1
        results.append((category, name, path, "ERR", dur, "FAIL", str(e)[:80]))
        print(f"{category:<10} | {name:<26} | {path:<38} | ERR    | {dur}ms (FAIL: {e})")

print("\n" + "=" * 95)
print(f"SUMMARY: Total Checked: {len(endpoints)} | Passed: {passed} | Failed: {failed}")
print("=" * 95)

if failed > 0:
    print("\nFAILURES / UNEXPECTED CODES:")
    for r in results:
        if r[5] == "FAIL":
            print(f"  - [{r[0]}] {r[1]} ({r[2]}) -> Status: {r[3]}, Response: {r[6]}")
