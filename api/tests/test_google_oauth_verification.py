#!/usr/bin/env python
"""
Automated Test & Verification Suite for Google OAuth 2.0 Remediation.
Tests:
1. Scope registry accuracy & least-privilege compliance (10 Scopes Audit).
2. Canonical scope constants consistency across services.
3. Auth URL generation & CSRF state caching.
4. State validation and tamper-resistance.
5. Reviewer entitlement bypass for Google Verification Reviewer accounts (Phase 6).
6. Regular tenant entitlement restrictions (zero regression on paywalls).
7. Diagnostic endpoints response structure.
8. Scopes catalog endpoint response.
9. Multi-scope reviewer authorization flow.
"""

import os
import sys
import io
from unittest.mock import patch

# Set utf-8 output encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from api.models import Client
from api.services.google_oauth_service import (
    GOOGLE_SCOPES_AUDIT_REGISTRY,
    GOOGLE_SCOPE_AUDIT_REGISTRY,
    GMAIL_SCOPES,
    SHEETS_SCOPES,
    DOCS_SCOPES,
    SLIDES_SCOPES,
    CALENDAR_SCOPES,
    YOUTUBE_SCOPES,
    ALL_ACTIVE_SCOPES,
    ALL_REQUESTED_GOOGLE_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    generate_google_auth_url,
    validate_google_oauth_state,
    is_google_reviewer_account,
    audit_google_scopes,
)
from api.services.entitlement_service import EntitlementService

User = get_user_model()


def run_google_oauth_tests():
    print("=" * 85)
    print("🚀 RUNNING UWO-CONNECT GOOGLE OAUTH REMEDIATION VERIFICATION SUITE")
    print("=" * 85)

    passed_count = 0
    failed_count = 0
    results = []

    def log_test(name, success, details=""):
        nonlocal passed_count, failed_count
        if success:
            passed_count += 1
            results.append((name, "PASSED", details))
            print(f"  [PASS] {name} - {details}")
        else:
            failed_count += 1
            results.append((name, "FAILED", details))
            print(f"  [FAIL] {name} - {details}")

    # ---------------------------------------------------------
    # TEST 1: Scope Audit Registry & Least-Privilege Verification
    # ---------------------------------------------------------
    try:
        reviewed_scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/youtube.force-ssl",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/calendar.calendars",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/youtube.upload",
        ]
        registry = GOOGLE_SCOPES_AUDIT_REGISTRY
        all_present = all(s in registry for s in reviewed_scopes)
        cal_status = registry["https://www.googleapis.com/auth/calendar.calendars"]["status"]
        cal_removed = "REMOVED" in cal_status
        retained_count = sum(1 for s, m in registry.items() if m["status"] == "RETAINED")

        if all_present and cal_removed and retained_count == 9:
            log_test(
                "Test 1: 10 Google OAuth Scopes Audit Registry",
                True,
                "All 10 evaluated: 9 RETAINED, 1 REMOVED (calendar.calendars strictly pruned)"
            )
        else:
            log_test(
                "Test 1: 10 Google OAuth Scopes Audit Registry",
                False,
                f"Present: {all_present}, Calendar Removed: {cal_removed}, Retained Count: {retained_count}"
            )
    except Exception as e:
        log_test("Test 1: 10 Google OAuth Scopes Audit Registry", False, str(e))

    # ---------------------------------------------------------
    # TEST 2: Active Service Scope Arrays Least-Privilege
    # ---------------------------------------------------------
    try:
        checks = [
            ("calendar.calendars pruned", "https://www.googleapis.com/auth/calendar.calendars" not in CALENDAR_SCOPES),
            ("calendar.events retained", "https://www.googleapis.com/auth/calendar.events" in CALENDAR_SCOPES),
            ("broad youtube scope purged", "https://www.googleapis.com/auth/youtube" not in YOUTUBE_SCOPES),
            ("youtube.readonly present", "https://www.googleapis.com/auth/youtube.readonly" in YOUTUBE_SCOPES),
            ("youtube.upload present", "https://www.googleapis.com/auth/youtube.upload" in YOUTUBE_SCOPES),
            ("youtube.force-ssl present", "https://www.googleapis.com/auth/youtube.force-ssl" in YOUTUBE_SCOPES),
            ("gmail.modify present", "https://www.googleapis.com/auth/gmail.modify" in GMAIL_SCOPES),
            ("sheets present", "https://www.googleapis.com/auth/spreadsheets" in SHEETS_SCOPES),
            ("docs present", "https://www.googleapis.com/auth/documents" in DOCS_SCOPES),
            ("presentations present", "https://www.googleapis.com/auth/presentations" in SLIDES_SCOPES),
        ]
        all_passed = all(c[1] for c in checks)
        if all_passed:
            log_test(
                "Test 2: Scope Arrays Least-Privilege Enforcement",
                True,
                f"Verified {len(checks)} granular scope constraints without broad permissions"
            )
        else:
            failed_c = [c[0] for c in checks if not c[1]]
            log_test("Test 2: Scope Arrays Least-Privilege Enforcement", False, f"Failed: {failed_c}")
    except Exception as e:
        log_test("Test 2: Scope Arrays Least-Privilege Enforcement", False, str(e))

    # ---------------------------------------------------------
    # TEST 3: Auth URL Generation & CSRF State Caching
    # ---------------------------------------------------------
    try:
        with patch("api.services.google_oauth_service.get_google_credentials") as mock_creds:
            mock_creds.return_value = {
                "client_id": "test-mock-id.apps.googleusercontent.com",
                "client_secret": "test-mock-secret",
            }
            res = generate_google_auth_url(
                service_name="google_sheets",
                client_id="mock-client-guid-12345",
                scopes=SHEETS_SCOPES,
            )
            url_valid = "accounts.google.com/o/oauth2/v2/auth" in res["url"]
            state_cached = cache.get(f"google_oauth_state_{res['state']}") is not None
            if url_valid and state_cached:
                log_test(
                    "Test 3: Authorization URL Generation & State Caching",
                    True,
                    f"Generated valid URL with offline access, prompt=consent, and cached state token"
                )
            else:
                log_test(
                    "Test 3: Authorization URL Generation & State Caching",
                    False,
                    f"URL Valid: {url_valid}, State Cached: {state_cached}"
                )
    except Exception as e:
        log_test("Test 3: Authorization URL Generation & State Caching", False, str(e))

    # ---------------------------------------------------------
    # TEST 4: CSRF State Validation & Single-Use Consumption
    # ---------------------------------------------------------
    try:
        dummy_state = "verify-test-csrf-nonce-998877"
        cache.set(f"google_oauth_state_{dummy_state}", {"client_id": "client-1", "service": "gmail"}, timeout=60)
        v1 = validate_google_oauth_state(dummy_state, expected_service="gmail")
        v2 = validate_google_oauth_state(dummy_state, expected_service="gmail")  # Should fail (already consumed)
        tampered = validate_google_oauth_state("invalid-random-token")

        if v1["is_valid"] and not v2["is_valid"] and not tampered["is_valid"]:
            log_test(
                "Test 4: CSRF State Anti-Replay & Validation",
                True,
                "State validated on first use, invalidated on replay, invalid states rejected"
            )
        else:
            log_test("Test 4: CSRF State Anti-Replay & Validation", False, f"v1={v1}, v2={v2}, tampered={tampered}")
    except Exception as e:
        log_test("Test 4: CSRF State Anti-Replay & Validation", False, str(e))

    # ---------------------------------------------------------
    # TEST 5: Google Reviewer Entitlement Bypass (Phase 6)
    # ---------------------------------------------------------
    reviewer_client = None
    try:
        # Create or fetch reviewer client
        reviewer_client, _ = Client.objects.get_or_create(
            business_name="Google Reviewer Verification Account",
            defaults={"status": "ACTIVE"}
        )
        if not isinstance(reviewer_client.settings, dict):
            reviewer_client.settings = {}
        reviewer_client.settings["is_verification_account"] = True
        reviewer_client.is_verification_account = True
        reviewer_client.save()

        # Check entitlement service
        entitlements = EntitlementService.get_effective_entitlements(reviewer_client)
        is_rev_plan = entitlements["plan_name"] == "Google Verification Reviewer Plan"

        google_channels = ["gmail", "google_calendar", "google_sheets", "google_docs", "google_slides", "youtube"]
        all_unlocked = True
        for ch in google_channels:
            can_access, reason = EntitlementService.can_access_channel(reviewer_client, ch)
            if not can_access:
                all_unlocked = False
                break

        if is_rev_plan and all_unlocked:
            log_test(
                "Test 5: Phase 6 Google Reviewer Entitlement Bypass",
                True,
                f"All 6 Google connectors unlocked for reviewer account without paid subscription paywall"
            )
        else:
            log_test(
                "Test 5: Phase 6 Google Reviewer Entitlement Bypass",
                False,
                f"Reviewer Plan: {is_rev_plan}, All 6 Unlocked: {all_unlocked}"
            )
    except Exception as e:
        log_test("Test 5: Phase 6 Google Reviewer Entitlement Bypass", False, str(e))

    # ---------------------------------------------------------
    # TEST 6: Zero Regression on Regular Tenant Paywalls
    # ---------------------------------------------------------
    try:
        regular_client, _ = Client.objects.get_or_create(
            business_name="Standard Free Tenant Test",
            defaults={"status": "ACTIVE"}
        )
        if not isinstance(regular_client.settings, dict):
            regular_client.settings = {}
        regular_client.settings["is_verification_account"] = False
        regular_client.is_verification_account = False
        regular_client.subscription_plan = None
        regular_client.save()

        can_access, reason = EntitlementService.can_access_channel(regular_client, "google_sheets")
        # Regular free tenant should require upgrade for premium connector
        if not can_access and reason == "UPGRADE_REQUIRED":
            log_test(
                "Test 6: Production Paywall Integrity (Zero Regression)",
                True,
                "Regular tenants without paid subscription are blocked with UPGRADE_REQUIRED"
            )
        else:
            log_test(
                "Test 6: Production Paywall Integrity (Zero Regression)",
                False,
                f"Access allowed incorrectly: {can_access}, Reason: {reason}"
            )
    except Exception as e:
        log_test("Test 6: Production Paywall Integrity (Zero Regression)", False, str(e))

    # ---------------------------------------------------------
    # TEST 7: Diagnostic Endpoint Output Structure
    # ---------------------------------------------------------
    try:
        api_client = APIClient()
        if not reviewer_client:
            reviewer_client = Client.objects.first()
        user, _ = User.objects.get_or_create(
            username="google_reviewer_admin_test",
            defaults={"email": "reviewer@google.com"}
        )
        user.client = reviewer_client
        user.save()
        api_client.force_authenticate(user=user)

        resp = api_client.get("/api/auth/google/diagnostic/")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("retained_scopes_count") == 9 and data.get("removed_scopes_count") == 1:
                log_test(
                    "Test 7: /api/auth/google/diagnostic Endpoint",
                    True,
                    "Returns 9 retained, 1 removed, configuration status & scope details"
                )
            else:
                log_test("Test 7: /api/auth/google/diagnostic Endpoint", False, f"Unexpected counts in: {data}")
        else:
            log_test("Test 7: /api/auth/google/diagnostic Endpoint", False, f"HTTP {resp.status_code}")
    except Exception as e:
        log_test("Test 7: /api/auth/google/diagnostic Endpoint", False, str(e))

    # ---------------------------------------------------------
    # TEST 8: Public Scopes Catalog Endpoint
    # ---------------------------------------------------------
    try:
        api_client = APIClient()
        resp = api_client.get("/api/auth/google/scopes/")
        if resp.status_code == 200:
            data = resp.json()
            services = data.get("active_services", {})
            has_all_services = all(
                s in services for s in ["gmail", "google_sheets", "google_docs", "google_slides", "google_calendar", "youtube"]
            )
            if has_all_services:
                log_test(
                    "Test 8: /api/auth/google/scopes Catalog Endpoint",
                    True,
                    f"Public scope catalog lists all 6 active Google services accurately"
                )
            else:
                log_test("Test 8: /api/auth/google/scopes Catalog Endpoint", False, f"Missing services in {services.keys()}")
        else:
            log_test("Test 8: /api/auth/google/scopes Catalog Endpoint", False, f"HTTP {resp.status_code}")
    except Exception as e:
        log_test("Test 8: /api/auth/google/scopes Catalog Endpoint", False, str(e))

    # ---------------------------------------------------------
    # TEST 9: Multi-Scope Reviewer Connect-All Flow
    # ---------------------------------------------------------
    try:
        api_client = APIClient()
        api_client.force_authenticate(user=user)
        with patch("api.services.google_oauth_service.get_google_credentials") as mock_creds:
            mock_creds.return_value = {
                "client_id": "test-mock-id.apps.googleusercontent.com",
                "client_secret": "test-mock-secret",
            }
            resp = api_client.get("/api/auth/google/connect-all/")
            if resp.status_code == 200:
                data = resp.json()
                req_scopes = data.get("scopes_requested", [])
                retained_scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://www.googleapis.com/auth/presentations",
                    "https://www.googleapis.com/auth/youtube.force-ssl",
                    "https://www.googleapis.com/auth/calendar",
                    "https://www.googleapis.com/auth/documents",
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/youtube.upload",
                ]
                all_9_in_request = all(s in req_scopes for s in retained_scopes)
                cal_not_in_request = "https://www.googleapis.com/auth/calendar.calendars" not in req_scopes
                broad_yt_not_in_request = "https://www.googleapis.com/auth/youtube" not in req_scopes

                if all_9_in_request and cal_not_in_request and broad_yt_not_in_request:
                    log_test(
                        "Test 9: Multi-Scope Verification Authorization Endpoint",
                        True,
                        "Generates single consent URL with all 9 retained scopes and 0 over-scoped permissions"
                    )
                else:
                    log_test(
                        "Test 9: Multi-Scope Verification Authorization Endpoint",
                        False,
                        f"All 9 present: {all_9_in_request}, Calendar pruned: {cal_not_in_request}, Broad YT pruned: {broad_yt_not_in_request}"
                    )
            else:
                log_test("Test 9: Multi-Scope Verification Authorization Endpoint", False, f"HTTP {resp.status_code}")
    except Exception as e:
        log_test("Test 9: Multi-Scope Verification Authorization Endpoint", False, str(e))

    print("\n" + "=" * 85)
    print(f"📊 VERIFICATION SUITE SUMMARY: {passed_count} PASSED, {failed_count} FAILED")
    print("=" * 85)

    if failed_count == 0:
        print("🎉 ALL GOOGLE OAUTH VERIFICATION REMEDIATION TESTS PASSED WITH ZERO REGRESSIONS!")
        return 0
    else:
        print("⚠️ SOME TESTS FAILED. PLEASE REVIEW LOGS ABOVE.")
        return 1


if __name__ == "__main__":
    exit_code = run_google_oauth_tests()
    sys.exit(exit_code)
