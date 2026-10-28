import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIRequestFactory, force_authenticate
from api.models import (
    User, Client, ContactMessage, ContactMessageReply,
    UserFeedback, UserFeedbackReply, InAppNotification
)
from api.views.contact_feedback_views import (
    ContactSubmitView, MyContactMessagesView, ContactReplyView,
    FeedbackSubmitView, MyFeedbackListView, FeedbackReplyView,
    AdminContactMessagesListView, AdminContactMessageReplyView,
    AdminContactMessageStatusView, AdminUserFeedbackListView,
    AdminUserFeedbackReplyView, AdminUserFeedbackStatusView,
    InAppNotificationListView
)

def run_tests():
    factory = APIRequestFactory()
    print("=" * 60)
    print("TESTING CONTACT US & FEEDBACK MANAGEMENT SYSTEM")
    print("=" * 60)

    # Clean test fixtures if existing
    ContactMessage.objects.filter(email__endswith='@testflow.com').delete()
    UserFeedback.objects.filter(email__endswith='@testflow.com').delete()

    # 1. Create test users
    admin_user, _ = User.objects.get_or_create(
        username='admin_test_cf',
        defaults={'email': 'admin@testflow.com', 'role': 'ADMIN', 'enterprise_role': 'SUPER_ADMIN'}
    )
    admin_user.role = 'ADMIN'
    admin_user.enterprise_role = 'SUPER_ADMIN'
    admin_user.save()

    client_record, _ = Client.objects.get_or_create(
        business_name='Test Client Co',
        defaults={'status': 'ACTIVE'}
    )

    user1, _ = User.objects.get_or_create(
        username='alice_cf',
        defaults={'email': 'alice@testflow.com', 'role': 'CLIENT', 'client': client_record}
    )
    user2, _ = User.objects.get_or_create(
        username='bob_cf',
        defaults={'email': 'bob@testflow.com', 'role': 'CLIENT', 'client': client_record}
    )

    # -------------------------------------------------------------
    # TEST 1: Submit Contact Message from WEB (Anonymous/Guest)
    # -------------------------------------------------------------
    req = factory.post('/api/contact/submit/', {
        'name': 'Guest Web User',
        'email': 'guestweb@testflow.com',
        'phone': '+1234567890',
        'subject': 'Inquiry about Enterprise Pricing',
        'message': 'Hello, what are your annual volume discounts?',
        'source': 'web'
    }, format='json')
    res = ContactSubmitView.as_view()(req)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.data}"
    web_msg_id = res.data['data']['id']
    assert res.data['data']['source'] == 'WEB'
    assert res.data['data']['status'] == 'PENDING'
    print("✓ Test 1 Passed: Guest Web Contact submission recorded with source='WEB'")

    # -------------------------------------------------------------
    # TEST 2: Submit Contact Message from MOBILE APP (Authenticated)
    # -------------------------------------------------------------
    req = factory.post('/api/contact/submit/', {
        'subject': 'Mobile App WhatsApp Integration Question',
        'message': 'How do I scan the QR code from within the mobile app?',
        'source': 'app'
    }, format='json')
    force_authenticate(req, user=user1)
    res = ContactSubmitView.as_view()(req)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.data}"
    app_msg_id = res.data['data']['id']
    assert res.data['data']['source'] == 'APP'
    assert res.data['data']['email'] == user1.email
    print("✓ Test 2 Passed: Authenticated Mobile App Contact submission recorded with source='APP'")

    # -------------------------------------------------------------
    # TEST 3: Admin List & Filter Contact Messages
    # -------------------------------------------------------------
    req = factory.get('/api/admin/contact-messages/?status=PENDING')
    force_authenticate(req, user=admin_user)
    res = AdminContactMessagesListView.as_view()(req)
    assert res.status_code == 200
    results = res.data['results']
    found_web = any(m['id'] == web_msg_id for m in results)
    found_app = any(m['id'] == app_msg_id for m in results)
    assert found_web and found_app, "Admin must see both Web and Mobile App submissions"
    print("✓ Test 3 Passed: Admin retrieves central Contact Messages with both Web and Mobile entries")

    # -------------------------------------------------------------
    # TEST 4: Admin Replies to Mobile App Contact Message
    # -------------------------------------------------------------
    req = factory.post(f'/api/admin/contact-messages/{app_msg_id}/reply/', {
        'message': 'You can scan the QR code from Settings -> Linked Devices.'
    }, format='json')
    force_authenticate(req, user=admin_user)
    res = AdminContactMessageReplyView.as_view()(req, pk=app_msg_id)
    assert res.status_code == 201
    assert res.data['data']['status'] == 'REPLIED'
    assert len(res.data['data']['replies']) == 1
    assert res.data['data']['replies'][0]['sender_role'] == 'ADMIN'
    print("✓ Test 4 Passed: Admin successfully replied to Contact Message; status updated to REPLIED")

    # -------------------------------------------------------------
    # TEST 5: User 1 Sees the Admin Reply in their account
    # -------------------------------------------------------------
    req = factory.get('/api/contact/my-messages/')
    force_authenticate(req, user=user1)
    res = MyContactMessagesView.as_view()(req)
    assert res.status_code == 200
    user_threads = res.data
    target_thread = next((t for t in user_threads if t['id'] == app_msg_id), None)
    assert target_thread is not None, "User 1 must see their own contact message"
    assert len(target_thread['replies']) == 1
    assert target_thread['replies'][0]['message'] == 'You can scan the QR code from Settings -> Linked Devices.'
    print("✓ Test 5 Passed: User 1 sees admin reply in their own account thread")

    # -------------------------------------------------------------
    # TEST 6: User 1 Replies Back (Thread continuity)
    # -------------------------------------------------------------
    req = factory.post(f'/api/contact/{app_msg_id}/reply/', {
        'message': 'Thank you! It connected immediately.'
    }, format='json')
    force_authenticate(req, user=user1)
    res = ContactReplyView.as_view()(req, pk=app_msg_id)
    assert res.status_code == 201
    assert len(res.data['data']['replies']) == 2
    assert res.data['data']['replies'][1]['sender_role'] == 'USER'
    print("✓ Test 6 Passed: User 1 replies back; multi-message threaded conversation preserved")

    # -------------------------------------------------------------
    # TEST 7: Tenant Isolation - User 2 Cannot Access User 1's Conversation
    # -------------------------------------------------------------
    req = factory.post(f'/api/contact/{app_msg_id}/reply/', {
        'message': 'I am trying to snoop on User 1'
    }, format='json')
    force_authenticate(req, user=user2)
    res = ContactReplyView.as_view()(req, pk=app_msg_id)
    assert res.status_code == 403, f"Expected 403 Forbidden, got {res.status_code}"

    req = factory.get('/api/contact/my-messages/')
    force_authenticate(req, user=user2)
    res = MyContactMessagesView.as_view()(req)
    assert not any(t['id'] == app_msg_id for t in res.data), "User 2 must not see User 1's messages"
    print("✓ Test 7 Passed: Strict authorization check prevents unauthorized cross-user message access")

    # -------------------------------------------------------------
    # TEST 8: Submit Feedback from Web and App
    # -------------------------------------------------------------
    req_web = factory.post('/api/feedback/submit/', {
        'name': 'Web Feedbacker',
        'email': 'feedbackweb@testflow.com',
        'category': 'UX',
        'rating': 4,
        'message': 'The dark mode looks awesome, but contrast on buttons could be higher.',
        'source': 'web'
    }, format='json')
    res_web = FeedbackSubmitView.as_view()(req_web)
    assert res_web.status_code == 201
    web_fb_id = res_web.data['data']['id']
    assert res_web.data['data']['source'] == 'WEB'

    req_app = factory.post('/api/feedback/submit/', {
        'category': 'FEATURE',
        'rating': 5,
        'message': 'Please add voice note transcripts in the mobile app!',
        'source': 'app'
    }, format='json')
    force_authenticate(req_app, user=user1)
    res_app = FeedbackSubmitView.as_view()(req_app)
    assert res_app.status_code == 201
    app_fb_id = res_app.data['data']['id']
    assert res_app.data['data']['source'] == 'APP'
    print("✓ Test 8 Passed: Feedback submitted from both Web and Mobile App with categories and ratings")

    # -------------------------------------------------------------
    # TEST 9: Admin Views Central User Feedback & Category Filtering
    # -------------------------------------------------------------
    req = factory.get('/api/admin/user-feedback/?category=FEATURE')
    force_authenticate(req, user=admin_user)
    res = AdminUserFeedbackListView.as_view()(req)
    assert res.status_code == 200
    assert any(f['id'] == app_fb_id for f in res.data['results'])
    assert not any(f['id'] == web_fb_id for f in res.data['results'])
    print("✓ Test 9 Passed: Admin User Feedback list and category filter working accurately")

    # -------------------------------------------------------------
    # TEST 10: Admin Replies to Feedback & User Receives In-App Notification
    # -------------------------------------------------------------
    req = factory.post(f'/api/admin/user-feedback/{app_fb_id}/reply/', {
        'message': 'Great suggestion! Voice note transcripts will be in the next update.'
    }, format='json')
    force_authenticate(req, user=admin_user)
    res = AdminUserFeedbackReplyView.as_view()(req, pk=app_fb_id)
    assert res.status_code == 201
    assert res.data['data']['status'] == 'REPLIED'

    # Check that in-app notification was generated for user1
    notifs = InAppNotification.objects.filter(user=user1, notification_type='FEEDBACK_REPLY')
    assert notifs.exists(), "In-app notification must be delivered to user1"
    print("✓ Test 10 Passed: Admin replied to Feedback, and in-app notification was generated for user")

    print("\nALL 10 BACKEND INTEGRATION TESTS PASSED WITH 100% SUCCESS!")

if __name__ == '__main__':
    run_tests()
