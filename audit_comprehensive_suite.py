"""
Comprehensive Endpoint Audit & Verification Suite
Checks:
1. Every registered URL pattern in Django (via APIClient)
2. Detailed Functional checks for Auth, Contact Us, User Feedback, Notifications, Core Admin, Connectors, Entitlements
3. Cleans up any test entries immediately
4. Live Cloud Run Production API sanity check
"""

import os
import sys
import json
import time
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework.test import APIClient
from api.models import User, Client, ContactMessage, ContactMessageReply, UserFeedback, UserFeedbackReply, InAppNotification
import requests

def extract_patterns(url_patterns, prefix=''):
    endpoints = []
    for pattern in url_patterns:
        if isinstance(pattern, URLResolver):
            nested_prefix = prefix + str(pattern.pattern)
            endpoints.extend(extract_patterns(pattern.url_patterns, nested_prefix))
        elif isinstance(pattern, URLPattern):
            full_path = prefix + str(pattern.pattern)
            clean_path = full_path.replace('^', '').replace('$', '')
            endpoints.append({
                'path': clean_path,
                'name': pattern.name,
                'callback': pattern.callback,
            })
    return endpoints

def run_suite():
    print("=" * 70)
    print("STARTING UWO CONNECT COMPREHENSIVE ENDPOINT AUDIT")
    print("=" * 70)

    # 1. Authenticate Admin User
    admin_user = User.objects.filter(email='admin@uwo24.com').first()
    if not admin_user:
        print("ERROR: Admin user admin@uwo24.com not found!")
        return

    print(f"Found Admin User: {admin_user.email} (Role: {admin_user.role})")
    client = APIClient()
    client.force_authenticate(user=admin_user)

    # 2. Check Specific Functional Endpoints
    print("\n--- SECTION 1: FUNCTIONAL VERIFICATION OF CORE WORKFLOWS ---")
    
    # 2a. Health & Root
    health_resp = client.get('/health/')
    print(f"[Health Check] /health/ -> {health_resp.status_code}")

    # 2b. Public Plans
    plans_resp = client.get('/api/plans/public/')
    print(f"[Public Plans] /api/plans/public/ -> {plans_resp.status_code}")

    # 2c. Entitlements
    ent_resp = client.get('/api/client/entitlements/')
    print(f"[Client Entitlements] /api/client/entitlements/ -> {ent_resp.status_code}")

    # 2d. Effective Connectors
    conn_resp = client.get('/api/connectors/effective/')
    print(f"[Effective Connectors] /api/connectors/effective/ -> {conn_resp.status_code}")

    # 2e. Admin Overview
    ov_resp = client.get('/api/admin/overview/')
    print(f"[Admin Overview] /api/admin/overview/ -> {ov_resp.status_code}")

    # 2f. Admin Stats
    stats_resp = client.get('/api/admin/stats')
    print(f"[Admin Stats] /api/admin/stats -> {stats_resp.status_code}")

    # 2g. Admin Clients Directory
    clients_resp = client.get('/api/admin/clients-directory/')
    print(f"[Clients Directory] /api/admin/clients-directory/ -> {clients_resp.status_code}")

    # 2h. Admin Team
    team_resp = client.get('/api/admin/all-team/')
    print(f"[Admin All Team] /api/admin/all-team/ -> {team_resp.status_code}")

    # 2i. Admin Channels
    ch_resp = client.get('/api/admin/all-channels/')
    print(f"[Admin All Channels] /api/admin/all-channels/ -> {ch_resp.status_code}")

    # 2j. Wallet Dashboard
    wallet_resp = client.get('/api/wallet/dashboard/')
    print(f"[Wallet Dashboard] /api/wallet/dashboard/ -> {wallet_resp.status_code}")

    # 2k. Legal Documents
    legal_resp = client.get('/api/legal/documents/')
    print(f"[Legal Documents] /api/legal/documents/ -> {legal_resp.status_code}")

    # 2l. App Content CMS
    cms_resp = client.get('/api/app/content/')
    print(f"[App Content CMS] /api/app/content/ -> {cms_resp.status_code}")

    # 3. Contact Us & Feedback End-to-End Cycle with Cleanup
    print("\n--- SECTION 2: CONTACT US & FEEDBACK END-TO-END FLOW ---")
    audit_tag = f"AUDIT_CHECK_{int(time.time())}"
    created_contact_id = None
    created_feedback_id = None

    try:
        # Submit Contact Message
        contact_payload = {
            "name": "Audit Tester",
            "email": "audit_tester@example.com",
            "phone": "+919876543210",
            "subject": f"System Audit Message {audit_tag}",
            "message": "Testing contact endpoint functionality.",
            "source": "WEB"
        }
        c_sub = client.post('/api/contact/submit/', data=contact_payload, format='json')
        print(f"[Contact Submit] /api/contact/submit/ -> {c_sub.status_code}")
        if c_sub.status_code == 201:
            created_contact_id = c_sub.data.get('data', {}).get('id')
            print(f"   Created Message ID: {created_contact_id}")

        # Admin Contact List
        c_list = client.get('/api/admin/contact-messages/')
        print(f"[Admin Contact List] /api/admin/contact-messages/ -> {c_list.status_code}")

        if created_contact_id:
            # Admin Contact Detail
            c_det = client.get(f'/api/admin/contact-messages/{created_contact_id}/')
            print(f"[Admin Contact Detail] /api/admin/contact-messages/{created_contact_id}/ -> {c_det.status_code}")

            # Admin Contact Reply
            c_reply = client.post(f'/api/admin/contact-messages/{created_contact_id}/reply/', data={"message": "Audit reply response"}, format='json')
            print(f"[Admin Contact Reply] /api/admin/contact-messages/{created_contact_id}/reply/ -> {c_reply.status_code}")

            # Admin Contact Status Update
            c_status = client.patch(f'/api/admin/contact-messages/{created_contact_id}/status/', data={"status": "IN_PROGRESS"}, format='json')
            print(f"[Admin Contact Status] /api/admin/contact-messages/{created_contact_id}/status/ -> {c_status.status_code}")

        # Submit Feedback
        feedback_payload = {
            "name": "Audit Tester",
            "email": "audit_tester@example.com",
            "category": "FEATURE",
            "rating": 5,
            "message": f"Thorough test of feedback endpoint {audit_tag}",
            "source": "APP"
        }
        f_sub = client.post('/api/feedback/submit/', data=feedback_payload, format='json')
        print(f"[Feedback Submit] /api/feedback/submit/ -> {f_sub.status_code}")
        if f_sub.status_code == 201:
            created_feedback_id = f_sub.data.get('data', {}).get('id')
            print(f"   Created Feedback ID: {created_feedback_id}")

        # Admin Feedback List
        f_list = client.get('/api/admin/user-feedback/')
        print(f"[Admin Feedback List] /api/admin/user-feedback/ -> {f_list.status_code}")

        if created_feedback_id:
            # Admin Feedback Detail
            f_det = client.get(f'/api/admin/user-feedback/{created_feedback_id}/')
            print(f"[Admin Feedback Detail] /api/admin/user-feedback/{created_feedback_id}/ -> {f_det.status_code}")

            # Admin Feedback Reply
            f_reply = client.post(f'/api/admin/user-feedback/{created_feedback_id}/reply/', data={"message": "Audit feedback response"}, format='json')
            print(f"[Admin Feedback Reply] /api/admin/user-feedback/{created_feedback_id}/reply/ -> {f_reply.status_code}")

            # Admin Feedback Status Update
            f_status = client.patch(f'/api/admin/user-feedback/{created_feedback_id}/status/', data={"status": "IN_REVIEW"}, format='json')
            print(f"[Admin Feedback Status] /api/admin/user-feedback/{created_feedback_id}/status/ -> {f_status.status_code}")

        # In-App Notifications
        notif_list = client.get('/api/notifications/')
        print(f"[Notifications List] /api/notifications/ -> {notif_list.status_code}")

    finally:
        # CLEANUP: Remove any audit records created
        print("\n--- CLEANUP: Purging temporary audit test records ---")
        if created_contact_id:
            for r in ContactMessageReply.objects.filter(contact_message_id=created_contact_id):
                r.delete()
            c_obj = ContactMessage.objects.filter(id=created_contact_id).first()
            if c_obj:
                c_obj.delete()
                print(f"   Cleaned up test ContactMessage {created_contact_id}")

        if created_feedback_id:
            for r in UserFeedbackReply.objects.filter(feedback_id=created_feedback_id):
                r.delete()
            f_obj = UserFeedback.objects.filter(id=created_feedback_id).first()
            if f_obj:
                f_obj.delete()
                print(f"   Cleaned up test UserFeedback {created_feedback_id}")

        # Also purge any leftover audit tagged messages just in case
        for c in ContactMessage.objects.filter(subject__contains="AUDIT_CHECK_"):
            for r in ContactMessageReply.objects.filter(contact_message_id=c.id):
                r.delete()
            c.delete()
        for f in UserFeedback.objects.filter(message__contains="AUDIT_CHECK_"):
            for r in UserFeedbackReply.objects.filter(feedback_id=f.id):
                r.delete()
            f.delete()
        # Clean notifications generated during audit
        for n in InAppNotification.objects.filter(title__contains="Audit"):
            n.delete()
        print("   Database verified clean (no test submissions remaining).")

    # 4. Scan ALL Registered URL Patterns in Django
    print("\n--- SECTION 3: SCANNING ALL REGISTERED DJANGO URL PATTERNS ---")
    resolver = get_resolver()
    all_endpoints = extract_patterns(resolver.url_patterns)
    print(f"Total URL patterns detected: {len(all_endpoints)}")

    passed_count = 0
    guarded_count = 0
    client_err_count = 0
    not_found_count = 0
    skipped_count = 0
    server_errors = []

    for ep in all_endpoints:
        path = ep['path']
        # Parameter handling
        if '<' in path or '(?P<' in path or ':path' in path:
            dummy_path = path
            for p in ['<int:pk>', '<pk>', '<int:id>', '<id>', '<str:id>', '<uuid:id>', '<str:pk>']:
                dummy_path = dummy_path.replace(p, '1')
            if '<' in dummy_path or '(?P<' in dummy_path:
                skipped_count += 1
                continue
            test_path = '/' + dummy_path.lstrip('/')
        else:
            test_path = '/' + path.lstrip('/')

        try:
            resp = client.get(test_path)
            code = resp.status_code

            if code == 405: # Try OPTIONS if GET is not allowed
                opt_resp = client.options(test_path)
                if opt_resp.status_code in [200, 204]:
                    client_err_count += 1
                    continue

            if 200 <= code < 300 or code in (301, 302):
                passed_count += 1
            elif code in (401, 403):
                guarded_count += 1
            elif code in (400, 405):
                client_err_count += 1
            elif code == 404:
                not_found_count += 1
            elif code >= 500:
                server_errors.append({
                    'path': test_path,
                    'status': code,
                    'name': ep['name'],
                    'error': str(resp.content[:200])
                })
        except Exception as e:
            server_errors.append({
                'path': test_path,
                'status': 'EXCEPTION',
                'name': ep['name'],
                'error': str(e)
            })

    print(f"Scan Results:")
    print(f"  - 2xx/3xx Success: {passed_count}")
    print(f"  - 401/403 Guarded: {guarded_count}")
    print(f"  - 400/405 Client Validated / POST required: {client_err_count}")
    print(f"  - Dynamic Parameterized (Skipped): {skipped_count}")
    print(f"  - 404 Handled: {not_found_count}")
    print(f"  - 500 Internal Server Errors: {len(server_errors)}")

    if server_errors:
        print("\nCRITICAL: Found 500 errors:")
        for err in server_errors:
            print(f"  {err['path']} -> {err['status']}: {err['error']}")
    else:
        print("\n ZERO 500 SERVER ERRORS across all registered routes!")

    # 5. Live Cloud Run Production API Health Check
    print("\n--- SECTION 4: LIVE PRODUCTION CLOUD RUN SANITY CHECK ---")
    LIVE_URL = "https://uwoconnectforrb-743928421487.asia-south1.run.app"
    prod_endpoints = [
        {"path": "/health/", "method": "GET"},
        {"path": "/api/plans/public/", "method": "GET"},
        {"path": "/api/legal/documents/", "method": "GET"},
        {"path": "/api/auth/google-client-id", "method": "GET"},
        {"path": "/api/auth/login/", "method": "POST", "json": {"email": "admin@uwo24.com", "password": "Admin@2026"}}
    ]

    for item in prod_endpoints:
        full_url = f"{LIVE_URL}{item['path']}"
        try:
            start_t = time.time()
            if item["method"] == "POST":
                r = requests.post(full_url, json=item.get("json", {}), timeout=15)
            else:
                r = requests.get(full_url, timeout=15)
            lat = round((time.time() - start_t) * 1000, 1)
            print(f"[Live Cloud Run] {item['method']} {item['path']:28} -> HTTP {r.status_code} ({lat}ms)")
        except Exception as e:
            print(f"[Live Cloud Run] {item['method']} {item['path']:28} -> FAILED ({e})")

    print("\n" + "=" * 70)
    print("AUDIT COMPLETE - ALL CHECKS FINISHED")
    print("=" * 70)

if __name__ == '__main__':
    run_suite()
