import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

import requests
from api.models import User
from rest_framework_simplejwt.tokens import RefreshToken

user = User.objects.filter(role='ADMIN').first() or User.objects.first()
if not user:
    print("No user found in DB")
    exit(1)

refresh = RefreshToken.for_user(user)
access_token = str(refresh.access_token)
print(f"Testing with User: {user.email} (Role: {user.role})")

BASE_URL = "http://127.0.0.1:8080/api"
headers = {"Authorization": f"Bearer {access_token}"}

endpoints = [
    "/profile/",
    "/clients/",
    "/contacts/",
    "/conversations/",
    "/messages/",
    "/email/accounts/",
    "/templates/",
    "/automations/",
    "/client/stats",
    "/team/members/",
    "/team/projects/",
    "/team/tasks/",
    "/sales/analytics/",
    "/sales-documents/",
    "/invoices/",
    "/plans/public/",
    "/client/entitlements/",
]

print("\n--- LIVE HTTP ENDPOINT VERIFICATION (PORT 8080) ---")
passed = 0
failed = 0

for ep in endpoints:
    url = f"{BASE_URL}{ep}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        status = res.status_code
        if 200 <= status < 400:
            print(f"[OK] {ep:<32} -> {status}")
            passed += 1
        else:
            print(f"[FAIL] {ep:<32} -> {status} {res.text[:80]}")
            failed += 1
    except Exception as e:
        print(f"[ERR] {ep:<32} -> ERROR {e}")
        failed += 1

print(f"\nTotal: {len(endpoints)} | Passed: {passed} | Failed: {failed}")
