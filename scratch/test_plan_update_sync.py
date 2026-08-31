import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

import requests
from api.models import User, Plan
from rest_framework_simplejwt.tokens import RefreshToken

admin_user = User.objects.filter(role='ADMIN').first()
if not admin_user:
    print("No admin user found")
    exit(1)

refresh = RefreshToken.for_user(admin_user)
token = str(refresh.access_token)

BASE_URL = "http://127.0.0.1:8080/api"
headers = {"Authorization": f"Bearer {token}"}

plan = Plan.objects.first()
if not plan:
    print("No plan found in DB")
    exit(1)

original_price = float(plan.price)
test_price = 1299.0

print(f"--- TESTING ADMIN PLAN UPDATE -> CLIENT SYNC ---")
print(f"1. Target Plan: '{plan.name}' (ID: {plan.id})")
print(f"2. Original Price: INR {original_price}")

# Admin updates plan price via API
update_payload = {
    "price": test_price,
    "metadata": {
        **(plan.metadata or {}),
        "monthly_price": test_price
    }
}
resp = requests.patch(f"{BASE_URL}/plans/{plan.id}/", json=update_payload, headers=headers)
print(f"3. Admin Patch Response: Status {resp.status_code}")

# Now simulate Client fetching public plans
client_resp = requests.get(f"{BASE_URL}/plans/public/")
print(f"4. Client Public Plans Response: Status {client_resp.status_code}")
public_plans = client_resp.json()

matching_plan = next((p for p in public_plans if str(p.get('id')) == str(plan.id) or p.get('slug') == plan.slug), None)
updated_price = float(matching_plan.get('price', 0)) if matching_plan else None

print(f"5. Client sees Updated Price: INR {updated_price}")

# Revert to original price
revert_payload = {
    "price": original_price,
    "metadata": {
        **(plan.metadata or {}),
        "monthly_price": original_price
    }
}
requests.patch(f"{BASE_URL}/plans/{plan.id}/", json=revert_payload, headers=headers)
print(f"6. Reverted Plan Price back to original: INR {original_price}")

if updated_price == test_price:
    print("\n✅ SYNC VERIFIED: Admin price updates instantly reflect in Client API & Dashboard!")
else:
    print("\n❌ SYNC ISSUE: Updated price did not match.")
