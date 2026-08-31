import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

import requests
from api.models import User
from rest_framework_simplejwt.tokens import RefreshToken

admin_user = User.objects.filter(role='ADMIN').first()
if not admin_user:
    print("❌ No admin user found in database.")
    exit(1)

refresh = RefreshToken.for_user(admin_user)
token = str(refresh.access_token)

BASE_URL = "http://127.0.0.1:8080/api"
headers = {"Authorization": f"Bearer {token}"}

admin_endpoints = [
    ("/admin/overview/", "Admin Overview Metrics"),
    ("/admin/clients-directory/", "Clients Directory"),
    ("/admin/clients/overview/", "Client Intelligence"),
    ("/admin/all-team/", "Team Directory"),
    ("/admin/all-channels/", "Channels Center"),
    ("/admin/all-messages/", "Live Messages Feed"),
    ("/admin/all-sales/", "Sales Control"),
    ("/admin/all-quotations/", "Admin Quotations"),
    ("/admin/all-proposals/", "Admin Proposals"),
    ("/admin/all-invoices/", "Admin Invoices"),
    ("/admin/all-reports/", "Admin Work Reports"),
    ("/admin/all-products/", "Admin Products Catalog"),
    ("/plans/", "Plans Management"),
    ("/features/", "Features List"),
    ("/audit-logs/", "Audit Logs"),
    ("/support/messages/", "Support Messages"),
    ("/admin/settings/global", "Global Settings"),
]

print("=" * 70)
print(f"👑 ADMIN DASHBOARD COMPREHENSIVE VERIFICATION")
print(f"User: {admin_user.username} ({admin_user.email}) | Role: {admin_user.role}")
print("=" * 70)

passed = 0
failed = 0

for path, label in admin_endpoints:
    url = f"{BASE_URL}{path}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        status = res.status_code
        if 200 <= status < 400:
            print(f"[OK] {status} | {label:<30} ({path})")
            passed += 1
        else:
            print(f"[FAIL] {status} | {label:<30} ({path}) -> {res.text[:80]}")
            failed += 1
    except Exception as e:
        print(f"[ERR] EXCEPTION | {label:<30} ({path}) -> {e}")
        failed += 1

print("=" * 70)
print(f"🎯 ADMIN DASHBOARD AUDIT: {passed}/{len(admin_endpoints)} PASSED ({int(passed/len(admin_endpoints)*100)}%)")
print("=" * 70)
