import sys
sys.stdout.reconfigure(encoding='utf-8')
import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIClient
from api.models import User, Client

print("=" * 70)
print("🚀 COMPLETE END-TO-END ENDPOINT VERIFICATION (Client, Agent, Admin)")
print("=" * 70)

admin_user = User.objects.filter(role='ADMIN').first()
client_user = User.objects.filter(role__in=['CLIENT', 'OWNER', 'AGENT']).first()
if not client_user:
    client_user = User.objects.exclude(role='ADMIN').first()

print(f"👑 Admin User : {admin_user.username if admin_user else 'None'} ({admin_user.email if admin_user else ''})")
print(f"💼 Client User: {client_user.username if client_user else 'None'} ({client_user.email if client_user else ''})")

client_api = APIClient()
admin_api = APIClient()

if client_user:
    client_api.force_authenticate(user=client_user)

if admin_user:
    admin_api.force_authenticate(user=admin_user)

results = []

def test_endpoint(api_instance, method, url, name, role="CLIENT", payload=None):
    try:
        if method == 'GET':
            resp = api_instance.get(url)
        elif method == 'POST':
            resp = api_instance.post(url, data=payload or {}, format='json')
        elif method == 'DELETE':
            resp = api_instance.delete(url)
        
        status_code = resp.status_code
        ok = 200 <= status_code < 400
        icon = "✅" if ok else "❌"
        results.append({
            "name": name,
            "role": role,
            "method": method,
            "url": url,
            "status": status_code,
            "ok": ok
        })
        print(f"{icon} [{role}] {method} {url:<45} -> {status_code} ({name})")
        return resp
    except Exception as e:
        results.append({
            "name": name,
            "role": role,
            "method": method,
            "url": url,
            "status": f"ERR",
            "ok": False
        })
        print(f"❌ [{role}] {method} {url:<45} -> EXCEPTION: {e}")
        return None

print("\n📦 1. CLIENT & AGENT DASHBOARD ENDPOINTS")
test_endpoint(client_api, 'GET', '/api/profile/', 'Profile & Info', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/contacts/', 'CRM Contacts', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/conversations/', 'Inbox Conversations', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/messages/?limit=10', 'Chat Messages', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/campaigns/', 'Broadcast Campaigns', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/templates/', 'WhatsApp Templates', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/automations/', 'Auto Reply Rules', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/workflows/', 'Workflows Builder', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/email/messages/?folder=inbox', 'Gmail / Outlook Messages', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/email/accounts/', 'Connected Email Accounts', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/quotations/', 'Sales Quotations', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/invoices/', 'Invoices & Billing', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/proposals/', 'Proposals', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/products/', 'Product Catalog', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/orders/', 'Orders Management', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/knowledge/', 'Knowledge Base Documents', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/team/members/', 'Team Members', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/team/projects/', 'Team Projects', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/team/tasks/', 'Team Tasks', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/plans/public/', 'Public Subscription Plans', 'CLIENT')
test_endpoint(client_api, 'GET', '/api/client/entitlements/', 'Client Entitlements & Features', 'CLIENT')

print("\n🛡️ 2. SUPER ADMIN CONTROL CENTER ENDPOINTS")
test_endpoint(admin_api, 'GET', '/api/admin/overview/', 'Admin Overview Metrics', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/clients-directory/', 'Admin Clients Directory', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/clients/overview/', 'Admin Client Intelligence List', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-team/', 'Admin Team Directory', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-channels/', 'Admin Channels Center', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-messages/', 'Admin Live Messages', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-sales/', 'Admin Sales Control', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-quotations/', 'Admin Quotations', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-proposals/', 'Admin Proposals', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-invoices/', 'Admin Invoices', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-reports/', 'Admin Work Reports', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/admin/all-products/', 'Admin Products Catalog', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/plans/', 'Admin Plans Management', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/features/', 'Admin Features List', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/audit-logs/', 'Admin Audit Logs', 'ADMIN')
test_endpoint(admin_api, 'GET', '/api/support/messages/', 'Admin Support Messages', 'ADMIN')

passed = sum(1 for r in results if r['ok'])
total = len(results)
print("\n" + "=" * 70)
print(f"🎯 FINAL AUDIT RESULT: {passed}/{total} ENDPOINTS PASSED ({round(passed/total*100)}%)")
print("=" * 70)
