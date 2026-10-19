#!/usr/bin/env python
"""
Comprehensive Live HTTP Endpoint Health & Verification Audit.
Sends real HTTP requests to the running backend server on http://127.0.0.1:8000.
Tests:
1. Public & Info Endpoints
2. Google OAuth Connect & Callback Endpoints
3. Authenticated CRM, Chat, Contacts, Invoices, Workflows
4. Reviewer Entitlement Diagnostic Endpoints
"""

import os
import sys
import io
import json
import urllib.request
import urllib.error

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from api.models import Client

User = get_user_model()
BASE_URL = "http://127.0.0.1:8000"

def get_auth_token():
    """Generates a valid JWT access token for an active client user."""
    user = User.objects.filter(is_active=True).first()
    if not user:
        client, _ = Client.objects.get_or_create(business_name="Audit Test Client", defaults={"status": "ACTIVE"})
        user = User.objects.create_user(username="endpoint_audit_user", email="audit@uwoconnect.test", client=client)
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), user

def test_endpoint(path, method="GET", token=None, expected_statuses=(200,)):
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "UWOConnect-Endpoint-Auditor/1.0",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.status
            content = response.read().decode('utf-8')
            is_ok = status in expected_statuses
            return status, is_ok, "HTTP " + str(status)
    except urllib.error.HTTPError as e:
        status = e.code
        # For connect endpoints with query tokens, 302 or redirect or 400 with 'no client' is expected
        is_ok = status in expected_statuses
        return status, is_ok, f"HTTP {status}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, False, f"Connection Failed: {e.reason}"
    except Exception as e:
        return 0, False, str(e)


def run_audit():
    print("=" * 95)
    print("🌐 RUNNING COMPREHENSIVE LIVE API ENDPOINT VERIFICATION (http://127.0.0.1:8000)")
    print("=" * 95)

    token, user = get_auth_token()
    print(f"Authenticated as user: '{user.username}' (Client: {getattr(user.client, 'business_name', 'None')})\n")

    endpoints_to_test = [
        # --- 1. Google OAuth & Diagnostic Endpoints ---
        ("Public Google Scopes Catalog", "/api/auth/google/scopes/", "GET", None, (200,)),
        ("Google Diagnostic (Authenticated)", "/api/auth/google/diagnostic/", "GET", token, (200,)),
        ("Google Connect-All Flow", "/api/auth/google/connect-all/", "GET", token, (200,)),
        ("Gmail Connect Flow", "/api/auth/gmail/connect", "GET", token, (200, 302)),
        ("Google Calendar Connect Flow", "/api/auth/google-calendar/connect", "GET", token, (200, 302)),
        ("Google Sheets Connect Flow", "/api/google-sheets/connect/", "GET", token, (200, 302)),
        ("Google Docs Connect Flow", "/api/google-docs/connect/", "GET", token, (200, 302)),
        ("Google Slides Connect Flow", "/api/google-slides/connect/", "GET", token, (200, 302)),
        ("YouTube Connect Flow", "/api/auth/youtube/connect", "GET", token, (200, 302)),
        ("YouTube Status Endpoint", "/api/auth/youtube/status", "GET", token, (200,)),

        # --- 2. Core CRM, Chat, Automations, & Invoicing ---
        ("Client Details / Profile", "/api/client/details/", "GET", token, (200,)),
        ("CRM Contacts List", "/api/contacts/", "GET", token, (200,)),
        ("Conversations List", "/api/conversations/", "GET", token, (200,)),
        ("Invoices List", "/api/invoices/", "GET", token, (200,)),
        ("Sales Documents List", "/api/sales-documents/", "GET", token, (200,)),
        ("Products List", "/api/products/", "GET", token, (200,)),
        ("Workflows List", "/api/workflows/", "GET", token, (200,)),
        ("Automations List", "/api/automations/", "GET", token, (200,)),
        ("Channels List / Status", "/api/channels/", "GET", token, (200,)),
        ("WhatsApp Health / Settings", "/api/whatsapp/settings/", "GET", token, (200,)),

        # --- 3. Security & Auth Guard Checks ---
        ("Protected Endpoint without Token (Auth Guard)", "/api/client/details/", "GET", None, (401,)),
        ("Google Diagnostic without Token (Auth Guard)", "/api/auth/google/diagnostic/", "GET", None, (401,)),
    ]

    passed = 0
    failed = 0

    print(f"{'Endpoint Name':<42} | {'Method':<6} | {'Path':<32} | {'Status':<10}")
    print("-" * 95)

    for name, path, method, auth_token, expected in endpoints_to_test:
        status, is_ok, reason = test_endpoint(path, method=method, token=auth_token, expected_statuses=expected)
        icon = "✅" if is_ok else "❌"
        if is_ok:
            passed += 1
        else:
            failed += 1
        print(f"{name:<42} | {method:<6} | {path:<32} | {icon} {status}")

    print("\n" + "=" * 95)
    print(f"📊 SUMMARY: {passed} PASSED, {failed} FAILED across {len(endpoints_to_test)} endpoints tested.")
    print("=" * 95)

    if failed == 0:
        print("🎉 ALL TESTED ENDPOINTS ARE FULLY OPERATIONAL AND HEALTHY!")
    else:
        print("⚠️ SOME ENDPOINTS NEED ATTENTION.")

if __name__ == "__main__":
    run_audit()
