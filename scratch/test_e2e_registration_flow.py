import os
import sys
from pathlib import Path
import django
import requests
import json

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User, Client

BASE_URL = 'http://localhost:8000'

def run_tests():
    print("==================================================")
    print("STARTING FULL END-TO-END REGISTRATION AUDIT")
    print("==================================================")

    # 1. Test registration blocked when meta_portfolio_eligible is False
    print("\n--- Test 1: Register with meta_portfolio_eligible: false ---")
    payload_false = {
        "first_name": "Gate",
        "last_name": "Blocked",
        "business_name": "Blocked Business",
        "email": "blocked_user@testdomain.com",
        "phone_number": "+1234567890",
        "password": "ValidPassword123!",
        "meta_portfolio_eligible": False
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload_false)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.text}")
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    assert "Meta Portfolio is required" in r.text
    print("PASSED: Registration rejected when meta_portfolio_eligible is False.")

    # 2. Test registration blocked when meta_portfolio_eligible is omitted
    print("\n--- Test 2: Register without meta_portfolio_eligible ---")
    payload_omitted = {
        "first_name": "Gate",
        "last_name": "Missing",
        "business_name": "Missing Gate Corp",
        "email": "missing_gate@testdomain.com",
        "phone_number": "+1234567891",
        "password": "ValidPassword123!"
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload_omitted)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.text}")
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    print("PASSED: Registration rejected when meta_portfolio_eligible is omitted.")

    # Clean up test user if exists
    test_email = "meta_approved_user@uwoconnect.test"
    User.objects.filter(email=test_email).delete()
    Client.objects.filter(business_name="Apex Automations").delete()

    # 3. Test registration succeeds when meta_portfolio_eligible is True
    print("\n--- Test 3: Register with meta_portfolio_eligible: true ---")
    payload_valid = {
        "first_name": "Alex",
        "last_name": "Eligible",
        "business_name": "Apex Automations",
        "email": test_email,
        "phone_number": "+18005550199",
        "password": "SecurePassword123!",
        "meta_portfolio_eligible": True,
        "meta_portfolio_name": "Apex Automations Portfolio"
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload_valid)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code in [200, 201], f"Expected 200/201, got {r.status_code}"
    res_data = r.json()
    assert "token" in res_data or "access_token" in res_data
    token = res_data.get("token") or res_data.get("access_token")
    print(f"PASSED: User registered and returned JWT Token: {token[:20]}...")

    # 4. Verify MongoDB record status
    print("\n--- Test 4: Verify MongoDB state for new user ---")
    user = User.objects.get(email=test_email)
    print(f"User email: {user.email}")
    print(f"User status: {user.status}")
    print(f"User is_active: {user.is_active}")
    print(f"User meta_portfolio_eligible: {user.meta_portfolio_eligible}")
    assert user.status == 'APPROVED', f"Expected APPROVED, got {user.status}"
    assert user.is_active is True
    assert user.meta_portfolio_eligible is True
    print("PASSED: User is created with APPROVED status and meta_portfolio_eligible=True.")

    # 5. Immediate Login Test
    print("\n--- Test 5: Immediate Login Test with Credentials ---")
    login_payload = {
        "email": test_email,
        "password": "SecurePassword123!"
    }
    r = requests.post(f"{BASE_URL}/api/auth/login", json=login_payload)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    login_data = r.json()
    assert "token" in login_data
    print("PASSED: User can immediately log in with NO admin approval waiting period.")

    # 6. Verify existing user login still works with zero disruption
    print("\n--- Test 6: Verify Existing Admin & Client Login (Zero Disruption) ---")
    admin_payload = {
        "email": "admin@uwo24.com",
        "password": "admin123"
    }
    r = requests.post(f"{BASE_URL}/api/auth/login", json=admin_payload)
    print(f"Admin Login Status: {r.status_code}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    admin_token = r.json().get('token')
    print("PASSED: Existing admin logs in smoothly.")

    # 7. Check Admin Overview Endpoint
    print("\n--- Test 7: Verify Admin Overview Endpoint ---")
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/admin/clients/overview/?search=Apex", headers=headers)
    print(f"Admin Overview Status: {r.status_code}")
    overview_data = r.json()
    clients = overview_data.get('clients', [])
    print(f"Found {len(clients)} matching clients in overview.")
    matching = [c for c in clients if c.get('email') == test_email or c.get('business_name') == 'Apex Automations']
    assert len(matching) > 0, "Registered client not found in admin overview"
    print(f"Client in Directory: {matching[0]['business_name']} - Status: {matching[0].get('status')}")
    print("PASSED: Client appears in Admin Directory as active.")

    print("\n==================================================")
    print("ALL 7 END-TO-END REGISTRATION AUDIT TESTS PASSED!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()
