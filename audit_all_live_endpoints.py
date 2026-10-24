"""
Audit All Live Endpoints with Exact Registered Routes
"""

import os
import sys
import time
import json
import requests

BASE_URL = "http://127.0.0.1:8000"

token = ""
if os.path.exists("live_test_token.txt"):
    with open("live_test_token.txt") as f:
        token = f.read().strip()

auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
unauth_headers = {}

session = requests.Session()
session.trust_env = False

# Verified exact endpoints from api/urls.py
EXACT_ENDPOINTS = [
    # 1. System & Health
    {"domain": "System & Health", "method": "GET", "path": "/", "auth": False},
    {"domain": "System & Health", "method": "GET", "path": "/health", "auth": False},
    {"domain": "System & Health", "method": "GET", "path": "/health/", "auth": False},
    {"domain": "System & Health", "method": "GET", "path": "/robots.txt", "auth": False},
    {"domain": "System & Health", "method": "GET", "path": "/sitemap.xml", "auth": False},

    # 2. Knowledge Base & RAG
    {"domain": "Knowledge & RAG", "method": "GET", "path": "/api/knowledge/", "auth": True},
    {"domain": "Knowledge & RAG", "method": "POST", "path": "/api/knowledge/query/", "auth": True, "json": {"query": "What are your services?", "top_k": 2}},

    # 3. Authentication & Security
    {"domain": "Authentication", "method": "POST", "path": "/api/auth/login/", "auth": False, "json": {"email": "test@test.com", "password": "wrong"}},
    {"domain": "Authentication", "method": "GET", "path": "/api/auth/google-client-id", "auth": False},
    {"domain": "Authentication", "method": "POST", "path": "/api/auth/qr/create/", "auth": False, "json": {}},
    {"domain": "Authentication", "method": "GET", "path": "/api/auth/linked-devices/", "auth": True},
    {"domain": "Authentication", "method": "GET", "path": "/api/profile/", "auth": True},
    {"domain": "Authentication", "method": "GET", "path": "/api/user/preferences/", "auth": True},

    # 4. Plans & Entitlements
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/plans/public/", "auth": False},
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/plans/", "auth": True},
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/features/", "auth": True},
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/plan-features/", "auth": True},
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/client/entitlements/", "auth": True},
    {"domain": "Plans & Entitlements", "method": "GET", "path": "/api/client-feature-overrides/", "auth": True},

    # 5. Client Core & Messages
    {"domain": "Client Core", "method": "GET", "path": "/api/client/stats/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/messages/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/contacts/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/conversations/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/templates/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/campaigns/", "auth": True},
    {"domain": "Client Core", "method": "GET", "path": "/api/admin/client-platform-overview/", "auth": True},

    # 6. Automation & AI
    {"domain": "Automation & AI", "method": "GET", "path": "/api/automations/", "auth": True},
    {"domain": "Automation & AI", "method": "GET", "path": "/api/workflows/", "auth": True},
    {"domain": "Automation & AI", "method": "POST", "path": "/api/platform-assistant/", "auth": True, "json": {"message": "hello"}},

    # 7. Connectors & Channels
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/connectors/effective/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/connectors/global-status/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/auth/gmail/connect", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/auth/youtube/status/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/onedrive/status/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-calendar/status/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-sheets/list/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-docs/list/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-slides/list/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-drive/status/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/google-news/settings/", "auth": True},
    {"domain": "Channels & Connectors", "method": "GET", "path": "/api/auth/outlook/status/", "auth": True},

    # 8. Billing, Wallet & Sales
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/wallet/dashboard/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/payments/history/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/products/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/orders/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/invoices/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/sales-documents/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/quotations/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/proposals/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/sales/analytics/", "auth": True},
    {"domain": "Billing & Wallet", "method": "GET", "path": "/api/broadcasts/entitlement/", "auth": True},

    # 9. Team & HR
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/members/", "auth": True},
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/projects/", "auth": True},
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/tasks/", "auth": True},
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/attendance/", "auth": True},
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/leaves/", "auth": True},
    {"domain": "Team & HR", "method": "GET", "path": "/api/team/analytics/", "auth": True},

    # 10. WebRTC & Calls
    {"domain": "Calls & WebRTC", "method": "GET", "path": "/api/webrtc/config/", "auth": True},
    {"domain": "Calls & WebRTC", "method": "GET", "path": "/api/webrtc/history/", "auth": True},
    {"domain": "Calls & WebRTC", "method": "GET", "path": "/api/calls/analytics/", "auth": True},

    # 11. Guides & Support
    {"domain": "Guides & Support", "method": "GET", "path": "/api/guides/", "auth": True},
    {"domain": "Guides & Support", "method": "GET", "path": "/api/support/messages/", "auth": True},

    # 12. Agency & Whitelabel
    {"domain": "Agency & Whitelabel", "method": "GET", "path": "/api/agency/stats/", "auth": True},
    {"domain": "Agency & Whitelabel", "method": "GET", "path": "/api/agency/sub-clients/", "auth": True},
    {"domain": "Agency & Whitelabel", "method": "GET", "path": "/api/whitelabel/config/", "auth": True},

    # 13. Super Admin & Monitoring
    {"domain": "Super Admin", "method": "GET", "path": "/api/admin/overview/", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/admin/clients-directory/?page=1&page_size=10", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/admin/stats", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/admin/users", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/monitoring/stats/", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/monitoring/analytics/", "auth": True},
    {"domain": "Super Admin", "method": "GET", "path": "/api/admin/logs/", "auth": True},

    # 14. CMS & Legal
    {"domain": "CMS & Legal", "method": "GET", "path": "/api/legal/documents/", "auth": False},
    {"domain": "CMS & Legal", "method": "GET", "path": "/api/legal/consent-status/", "auth": True},
    {"domain": "CMS & Legal", "method": "GET", "path": "/api/app/content/", "auth": False},
    {"domain": "CMS & Legal", "method": "GET", "path": "/api/admin/content/banners/", "auth": True},
    {"domain": "CMS & Legal", "method": "GET", "path": "/api/admin/content/feature-flags/", "auth": True},

    # 15. Webhooks
    {"domain": "Webhooks", "method": "GET", "path": "/api/webhook/whatsapp/", "auth": False},
    {"domain": "Webhooks", "method": "GET", "path": "/api/webhook/facebook-instagram/", "auth": False},
    {"domain": "Webhooks", "method": "POST", "path": "/api/payments/webhook/", "auth": False, "json": {}},
]

def run():
    print(f"============================================================")
    print(f"AUDITING {len(EXACT_ENDPOINTS)} LIVE API ROUTES AGAINST: {BASE_URL}")
    print(f"============================================================\n")

    results_by_domain = {}
    total_passed = 0
    total_failed = 0
    total_500 = 0
    total_404 = 0

    for idx, ep in enumerate(EXACT_ENDPOINTS, 1):
        domain = ep["domain"]
        method = ep["method"]
        path = ep["path"]
        use_auth = ep.get("auth", False)
        payload = ep.get("json", None)

        url = f"{BASE_URL}{path}"
        headers = auth_headers if use_auth else unauth_headers

        start = time.time()
        try:
            if method == "POST":
                resp = session.post(url, headers=headers, json=payload or {}, timeout=15)
            else:
                resp = session.get(url, headers=headers, timeout=15)
            duration_ms = round((time.time() - start) * 1000, 1)
            status = resp.status_code

            is_500 = status >= 500
            is_404 = status == 404
            is_ok = (status < 400) or (status in (400, 401, 403) and not is_404)

            entry = {
                "path": path,
                "method": method,
                "status": status,
                "duration_ms": duration_ms,
                "ok": is_ok,
                "is_500": is_500,
                "is_404": is_404,
                "snippet": resp.text[:120].strip().replace("\n", " ")
            }

            if domain not in results_by_domain:
                results_by_domain[domain] = []
            results_by_domain[domain].append(entry)

            if is_500:
                total_500 += 1
                total_failed += 1
                flag = " CRITICAL 500"
            elif is_404:
                total_404 += 1
                total_failed += 1
                flag = "❌ 404 NOT FOUND"
            else:
                total_passed += 1
                flag = "✅ OK"

            print(f"[{idx:02d}/{len(EXACT_ENDPOINTS):02d}] {method:4} {path:42} -> HTTP {status:3} ({duration_ms:5.1f}ms) {flag}")

        except Exception as e:
            total_failed += 1
            total_500 += 1
            print(f"[{idx:02d}/{len(EXACT_ENDPOINTS):02d}] {method:4} {path:42} -> EXCEPTION: {e}")

    print("\n" + "="*60)
    print("DOMAIN-BY-DOMAIN AUDIT SUMMARY:")
    print("="*60)
    for domain, items in results_by_domain.items():
        domain_ok = all(it["ok"] for it in items)
        status_sym = "✅" if domain_ok else "❌"
        print(f"\n{status_sym} Domain: {domain} ({len(items)} endpoints tested)")
        for it in items:
            badge = "✅" if it["ok"] else ("❌ 500" if it["is_500"] else "❌ 404")
            print(f"    {badge} {it['method']:4} {it['path']:38} [{it['status']}] {it['duration_ms']}ms")

    print("\n" + "="*60)
    print(f"FINAL AUDIT RESULT:")
    print(f"Total Tested: {len(EXACT_ENDPOINTS)}")
    print(f"Passed / Healthy: {total_passed}")
    print(f"Failed (404 Missing): {total_404}")
    print(f"Internal Server Errors (500): {total_500}")
    print("="*60)

    with open("exact_endpoint_audit_summary.json", "w") as f:
        json.dump(results_by_domain, f, indent=2)

if __name__ == "__main__":
    run()
