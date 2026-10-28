import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIRequestFactory, force_authenticate
from django.db.models import Q
from api.models import (
    User, Client, ContactMessage, ContactMessageReply,
    UserFeedback, UserFeedbackReply, InAppNotification
)
from api.views.contact_feedback_views import (
    ContactSubmitView, MyContactMessagesView, ContactReplyView,
    FeedbackSubmitView, MyFeedbackListView, FeedbackReplyView,
    AdminContactMessagesListView, AdminContactMessageDetailView,
    AdminContactMessageReplyView, AdminContactMessageStatusView,
    AdminUserFeedbackListView, AdminUserFeedbackDetailView,
    AdminUserFeedbackReplyView, AdminUserFeedbackStatusView,
    InAppNotificationListView
)

def run_comprehensive_verification():
    factory = APIRequestFactory()
    print("=" * 70)
    print("UWO CONNECT: CONTACT US & FEEDBACK END-TO-END VERIFICATION SUITE")
    print("=" * 70)

    # Clean existing test data
    ContactMessage.objects.filter(email__endswith='@uwotest.org').delete()
    UserFeedback.objects.filter(email__endswith='@uwotest.org').delete()

    # Fixtures
    admin_user, _ = User.objects.get_or_create(
        username='e2e_admin',
        defaults={'email': 'admin@uwotest.org', 'role': 'ADMIN', 'enterprise_role': 'SUPER_ADMIN'}
    )
    admin_user.role = 'ADMIN'
    admin_user.enterprise_role = 'SUPER_ADMIN'
    admin_user.save()

    client_acct, _ = Client.objects.get_or_create(
        business_name='E2E Test Enterprise',
        defaults={'status': 'ACTIVE'}
    )

    web_user, _ = User.objects.get_or_create(
        username='e2e_web_user',
        defaults={'email': 'webuser@uwotest.org', 'role': 'CLIENT', 'client': client_acct}
    )

    mobile_user, _ = User.objects.get_or_create(
        username='e2e_mobile_user',
        defaults={'email': 'mobileuser@uwotest.org', 'role': 'CLIENT', 'client': client_acct}
    )

    snooper_user, _ = User.objects.get_or_create(
        username='e2e_snooper_user',
        defaults={'email': 'snooper@uwotest.org', 'role': 'CLIENT', 'client': client_acct}
    )

    # ─────────────────────────────────────────────────────────────
    # SECTION 1: CONTACT US FLOW (WEB + APP -> ADMIN -> REPLIES)
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section 1: Contact Us Verification] ---")

    # 1. Submit from Website (authenticated web user)
    req1 = factory.post('/api/contact/submit/', {
        'name': 'Web User Official',
        'email': web_user.email,
        'phone': '+91 98765 00001',
        'subject': 'Website Inquiry: High Volume WhatsApp API Limits',
        'message': 'We are expecting 50,000 incoming customer queries tomorrow. Can we increase our TPS limit?',
        'source': 'web'
    }, format='json')
    force_authenticate(req1, user=web_user)
    res1 = ContactSubmitView.as_view()(req1)
    assert res1.status_code == 201, f"Expected 201, got {res1.status_code}"
    web_inquiry_id = res1.data['data']['id']
    assert res1.data['data']['source'] == 'WEB'
    assert res1.data['data']['status'] == 'PENDING'
    print(f"✓ Step 1: Website Contact message submitted successfully (ID: {web_inquiry_id}, Source: WEB)")

    # 2. Submit from Mobile App (authenticated mobile user)
    req2 = factory.post('/api/contact/submit/', {
        'name': 'Mobile User App',
        'email': mobile_user.email,
        'phone': '+91 98765 00002',
        'subject': 'App Inquiry: QR Code Session Sync',
        'message': 'Can I stay logged in on both Android and iOS tablet simultaneously?',
        'source': 'app'
    }, format='json')
    force_authenticate(req2, user=mobile_user)
    res2 = ContactSubmitView.as_view()(req2)
    assert res2.status_code == 201
    mobile_inquiry_id = res2.data['data']['id']
    assert res2.data['data']['source'] == 'APP'
    assert res2.data['data']['status'] == 'PENDING'
    print(f"✓ Step 2: Mobile App Contact message submitted successfully (ID: {mobile_inquiry_id}, Source: APP)")

    # 3. Central Admin Dashboard receives both submissions
    req3 = factory.get('/api/admin/contact-messages/')
    force_authenticate(req3, user=admin_user)
    res3 = AdminContactMessagesListView.as_view()(req3)
    assert res3.status_code == 200
    all_admin_messages = res3.data['results']
    web_msg_found = next((m for m in all_admin_messages if m['id'] == web_inquiry_id), None)
    mobile_msg_found = next((m for m in all_admin_messages if m['id'] == mobile_inquiry_id), None)
    assert web_msg_found is not None, "Website message must appear in admin dashboard"
    assert mobile_msg_found is not None, "Mobile app message must appear in admin dashboard"
    assert web_msg_found['source'] == 'WEB'
    assert mobile_msg_found['source'] == 'APP'
    assert res3.data['stats']['total'] >= 2
    print("✓ Step 3: Admin Dashboard correctly displays both Website and Mobile messages in central inbox")

    # 4. Admin replies to Website message
    web_reply_text = "Yes, your WhatsApp TPS limit has been raised to 100 queries/sec for your event."
    req4 = factory.post(f'/api/admin/contact-messages/{web_inquiry_id}/reply/', {
        'message': web_reply_text
    }, format='json')
    force_authenticate(req4, user=admin_user)
    res4 = AdminContactMessageReplyView.as_view()(req4, pk=web_inquiry_id)
    assert res4.status_code == 201
    assert res4.data['data']['status'] == 'REPLIED'
    assert len(res4.data['data']['replies']) == 1
    assert res4.data['data']['replies'][0]['message'] == web_reply_text
    print("✓ Step 4: Admin successfully replied to Website message; status updated to REPLIED")

    # 5. Admin replies to Mobile App message
    mobile_reply_text = "Yes, you can link up to 4 companion devices via Linked Devices QR sync."
    req5 = factory.post(f'/api/admin/contact-messages/{mobile_inquiry_id}/reply/', {
        'message': mobile_reply_text
    }, format='json')
    force_authenticate(req5, user=admin_user)
    res5 = AdminContactMessageReplyView.as_view()(req5, pk=mobile_inquiry_id)
    assert res5.status_code == 201
    assert res5.data['data']['status'] == 'REPLIED'
    print("✓ Step 5: Admin successfully replied to Mobile App message; status updated to REPLIED")

    # 6. Verify User sees reply on Website
    req6 = factory.get('/api/contact/my-messages/')
    force_authenticate(req6, user=web_user)
    res6 = MyContactMessagesView.as_view()(req6)
    assert res6.status_code == 200
    my_web_thread = next((m for m in res6.data if m['id'] == web_inquiry_id), None)
    assert my_web_thread is not None
    assert my_web_thread['status'] == 'REPLIED'
    assert len(my_web_thread['replies']) == 1
    assert my_web_thread['replies'][0]['message'] == web_reply_text
    print("✓ Step 6: Website user sees admin reply in their account conversation thread")

    # 7. Verify User sees reply on Mobile App
    req7 = factory.get('/api/contact/my-messages/')
    force_authenticate(req7, user=mobile_user)
    res7 = MyContactMessagesView.as_view()(req7)
    assert res7.status_code == 200
    my_mobile_thread = next((m for m in res7.data if m['id'] == mobile_inquiry_id), None)
    assert my_mobile_thread is not None
    assert my_mobile_thread['status'] == 'REPLIED'
    assert len(my_mobile_thread['replies']) == 1
    assert my_mobile_thread['replies'][0]['message'] == mobile_reply_text
    print("✓ Step 7: Mobile App user sees admin reply in their account conversation thread")

    # 8. User replies back from Mobile App
    user_followup = "Thanks! Connected my tablet successfully."
    req8 = factory.post(f'/api/contact/{mobile_inquiry_id}/reply/', {
        'message': user_followup
    }, format='json')
    force_authenticate(req8, user=mobile_user)
    res8 = ContactReplyView.as_view()(req8, pk=mobile_inquiry_id)
    assert res8.status_code == 201
    assert len(res8.data['data']['replies']) == 2
    assert res8.data['data']['replies'][1]['sender_role'] == 'USER'
    assert res8.data['data']['status'] == 'PENDING' # Returns to pending so admin knows a new message arrived
    print("✓ Step 8: Mobile user multi-reply continuity verified (2 messages in thread)")

    # ─────────────────────────────────────────────────────────────
    # SECTION 2: USER FEEDBACK FLOW (WEB + APP -> ADMIN -> REPLIES)
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section 2: User Feedback Verification] ---")

    # 9. Submit Feedback from Website
    req9 = factory.post('/api/feedback/submit/', {
        'name': 'Web Tester',
        'email': web_user.email,
        'category': 'UX',
        'rating': 4,
        'message': 'The new workflow editor is super clean! Could we have dark mode presets for nodes?',
        'source': 'web'
    }, format='json')
    force_authenticate(req9, user=web_user)
    res9 = FeedbackSubmitView.as_view()(req9)
    assert res9.status_code == 201
    web_feedback_id = res9.data['data']['id']
    assert res9.data['data']['source'] == 'WEB'
    assert res9.data['data']['category'] == 'UX'
    assert res9.data['data']['rating'] == 4
    print(f"✓ Step 9: Website Feedback submitted (ID: {web_feedback_id}, Rating: 4, Category: UX)")

    # 10. Submit Feedback from Mobile App
    req10 = factory.post('/api/feedback/submit/', {
        'name': 'Mobile Tester',
        'email': mobile_user.email,
        'category': 'FEATURE',
        'rating': 5,
        'message': 'Love the fast notifications! Please add a dark theme toggle directly on the top bar.',
        'source': 'app'
    }, format='json')
    force_authenticate(req10, user=mobile_user)
    res10 = FeedbackSubmitView.as_view()(req10)
    assert res10.status_code == 201
    mobile_feedback_id = res10.data['data']['id']
    assert res10.data['data']['source'] == 'APP'
    assert res10.data['data']['category'] == 'FEATURE'
    assert res10.data['data']['rating'] == 5
    print(f"✓ Step 10: Mobile App Feedback submitted (ID: {mobile_feedback_id}, Rating: 5, Category: FEATURE)")

    # 11. Admin views both feedbacks in User Feedback dashboard
    req11 = factory.get('/api/admin/user-feedback/')
    force_authenticate(req11, user=admin_user)
    res11 = AdminUserFeedbackListView.as_view()(req11)
    assert res11.status_code == 200
    all_admin_feedback = res11.data['results']
    fb_web_found = next((f for f in all_admin_feedback if f['id'] == web_feedback_id), None)
    fb_mobile_found = next((f for f in all_admin_feedback if f['id'] == mobile_feedback_id), None)
    assert fb_web_found is not None, "Website feedback must appear in admin feedback dashboard"
    assert fb_mobile_found is not None, "Mobile feedback must appear in admin feedback dashboard"
    assert fb_web_found['source'] == 'WEB'
    assert fb_mobile_found['source'] == 'APP'
    print("✓ Step 11: Admin dashboard retrieves both Website and Mobile feedback in central view")

    # 12. Admin replies to Feedback
    feedback_reply_text = "Thank you! Dark theme presets for workflow nodes are slated for release v1.4."
    req12 = factory.post(f'/api/admin/user-feedback/{web_feedback_id}/reply/', {
        'message': feedback_reply_text
    }, format='json')
    force_authenticate(req12, user=admin_user)
    res12 = AdminUserFeedbackReplyView.as_view()(req12, pk=web_feedback_id)
    assert res12.status_code == 201
    assert res12.data['data']['status'] == 'REPLIED'
    print("✓ Step 12: Admin replied to feedback; status updated to REPLIED")

    # 13. User sees Feedback reply in their account
    req13 = factory.get('/api/feedback/my-feedback/')
    force_authenticate(req13, user=web_user)
    res13 = MyFeedbackListView.as_view()(req13)
    assert res13.status_code == 200
    my_fb = next((f for f in res13.data if f['id'] == web_feedback_id), None)
    assert my_fb is not None
    assert len(my_fb['replies']) == 1
    assert my_fb['replies'][0]['message'] == feedback_reply_text
    print("✓ Step 13: User successfully views admin response inside their Feedback section")

    # ─────────────────────────────────────────────────────────────
    # SECTION 3: SECURITY, REGRESSION & TENANT ISOLATION
    # ─────────────────────────────────────────────────────────────
    print("\n--- [Section 3: Security & Regression Checks] ---")

    # 14. Unauthorized user cannot access Admin functions
    req14 = factory.get('/api/admin/contact-messages/')
    force_authenticate(req14, user=web_user) # CLIENT, not ADMIN
    res14 = AdminContactMessagesListView.as_view()(req14)
    assert res14.status_code in [401, 403], f"Regular user must be denied admin access. Got {res14.status_code}"
    print("✓ Step 14: Non-admin users are strictly blocked (403 Forbidden) from admin contact endpoints")

    req14b = factory.get('/api/admin/user-feedback/')
    force_authenticate(req14b, user=mobile_user)
    res14b = AdminUserFeedbackListView.as_view()(req14b)
    assert res14b.status_code in [401, 403]
    print("✓ Step 15: Non-admin users are strictly blocked (403 Forbidden) from admin feedback endpoints")

    # 15. User Snooper cannot view or reply to Web User's Contact message
    req15 = factory.post(f'/api/contact/{web_inquiry_id}/reply/', {
        'message': 'Trying to hijack another user conversation'
    }, format='json')
    force_authenticate(req15, user=snooper_user)
    res15 = ContactReplyView.as_view()(req15, pk=web_inquiry_id)
    assert res15.status_code == 403, f"Expected 403, got {res15.status_code}"
    print("✓ Step 16: Snooper user cannot reply to another user's contact thread (403 Forbidden)")

    # 16. User Snooper cannot view Web User's messages in my-messages
    req16 = factory.get('/api/contact/my-messages/')
    force_authenticate(req16, user=snooper_user)
    res16 = MyContactMessagesView.as_view()(req16)
    assert not any(m['id'] == web_inquiry_id for m in res16.data)
    assert not any(m['id'] == mobile_inquiry_id for m in res16.data)
    print("✓ Step 17: Tenant isolation verified: Snooper user cannot see other users' inquiries")

    # 17. Notifications delivered
    req17 = factory.get('/api/notifications/')
    force_authenticate(req17, user=web_user)
    res17 = InAppNotificationListView.as_view()(req17)
    assert res17.status_code == 200
    assert len(res17.data['results']) >= 1
    print(f"✓ Step 18: In-App notifications verified for user ({res17.data['unread_count']} unread)")

    # 18. Validation: Empty message rejection
    req18 = factory.post('/api/contact/submit/', {
        'email': 'valid@uwotest.org',
        'message': '   '
    }, format='json')
    res18 = ContactSubmitView.as_view()(req18)
    assert res18.status_code == 400
    print("✓ Step 19: Empty message input validation rejected with 400 Bad Request")

    print("\n" + "=" * 70)
    print("ALL 19 VERIFICATION STEPS PASSED WITHOUT ANY REGRESSIONS!")
    print("=" * 70)

if __name__ == '__main__':
    run_comprehensive_verification()
