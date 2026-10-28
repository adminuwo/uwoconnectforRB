import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db.models import Q
from ..models import (
    ContactMessage,
    ContactMessageReply,
    UserFeedback,
    UserFeedbackReply,
    InAppNotification,
    User,
)
from ..serializers import (
    ContactMessageSerializer,
    ContactMessageReplySerializer,
    UserFeedbackSerializer,
    UserFeedbackReplySerializer,
    InAppNotificationSerializer,
)
from ..permissions.custom_permissions import IsSuperAdminUser

logger = logging.getLogger(__name__)


def normalize_source(raw_source):
    if not raw_source:
        return 'WEB'
    s = str(raw_source).strip().upper()
    if s in ['APP', 'MOBILE', 'MOBILE APP', 'IOS', 'ANDROID']:
        return 'APP'
    return 'WEB'


# ══════════════════════════════════════════════════════════════════════════════
# CONTACT US - PUBLIC & USER CLIENT VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class ContactSubmitView(APIView):
    """
    POST /api/contact/submit/
    Submits a contact inquiry from Web or Mobile App.
    Open to anonymous guests and authenticated users alike.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        subject = data.get('subject', '').strip() or 'Contact Inquiry'
        message = data.get('message', '').strip()
        source = normalize_source(data.get('source'))

        user = request.user if request.user.is_authenticated else None
        client = getattr(user, 'client', None) if user else None

        if user:
            if not name:
                name = user.get_full_name() or user.username
            if not email:
                email = user.email or ''
            if not phone and getattr(user, 'phone_number', None):
                phone = user.phone_number

        if not email:
            return Response({'error': 'Email address is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({'error': 'Message content is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            name = email.split('@')[0]

        contact_msg = ContactMessage.objects.create(
            user=user,
            client=client,
            name=name,
            email=email,
            phone=phone,
            subject=subject,
            message=message,
            source=source,
            status='PENDING'
        )

        # Notify platform administrators
        try:
            admin_users = User.objects.filter(
                Q(role='ADMIN') | Q(enterprise_role='SUPER_ADMIN') | Q(is_superuser=True)
            ).distinct()
            for admin in admin_users[:10]:
                InAppNotification.objects.create(
                    user=admin,
                    title=f"New Contact Message ({source})",
                    body=f"From {name}: {subject}",
                    notification_type='NEW_CONTACT',
                    link='/admin/contact-messages'
                )
        except Exception as e:
            logger.warning(f"Failed to create admin notification for contact inquiry: {e}")

        serializer = ContactMessageSerializer(contact_msg)
        return Response({
            'success': True,
            'message': 'Your contact inquiry has been submitted successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


class MyContactMessagesView(APIView):
    """
    GET /api/contact/my-messages/
    Returns conversation threads for the currently authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        q_filter = Q(user=user)
        if user.email:
            q_filter |= Q(email__iexact=user.email)

        messages = ContactMessage.objects.filter(q_filter).prefetch_related('replies').order_by('-created_at')
        serializer = ContactMessageSerializer(messages, many=True)
        return Response(serializer.data)


class ContactReplyView(APIView):
    """
    POST /api/contact/<id>/reply/
    Allows the submitting user to reply to an existing contact inquiry thread.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        reply_body = request.data.get('message', '').strip()
        if not reply_body:
            return Response({'error': 'Reply message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            contact_msg = ContactMessage.objects.get(pk=pk)
        except ContactMessage.DoesNotExist:
            return Response({'error': 'Contact message not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_owner = (
            contact_msg.user_id == user.id or
            (contact_msg.email and user.email and contact_msg.email.strip().lower() == user.email.strip().lower())
        )
        if not is_owner:
            return Response({'error': 'You do not have permission to view or reply to this conversation.'}, status=status.HTTP_403_FORBIDDEN)

        # Link contact_msg.user if not linked yet
        if not contact_msg.user:
            contact_msg.user = user
            if user.client:
                contact_msg.client = user.client

        # Create reply
        reply = ContactMessageReply.objects.create(
            contact_message=contact_msg,
            sender=user,
            sender_role='USER',
            message=reply_body
        )

        contact_msg.status = 'PENDING'
        contact_msg.save(update_fields=['status', 'updated_at'])

        # Notify admins
        try:
            admin_users = User.objects.filter(
                Q(role='ADMIN') | Q(enterprise_role='SUPER_ADMIN') | Q(is_superuser=True)
            ).distinct()
            for admin in admin_users[:10]:
                InAppNotification.objects.create(
                    user=admin,
                    title=f"User Follow-up on Inquiry #{contact_msg.id}",
                    body=f"{user.username}: {reply_body[:100]}",
                    notification_type='CONTACT_USER_REPLY',
                    link='/admin/contact-messages'
                )
        except Exception as e:
            logger.warning(f"Failed to alert admins: {e}")

        serializer = ContactMessageSerializer(contact_msg)
        return Response({
            'success': True,
            'message': 'Reply sent successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


# ══════════════════════════════════════════════════════════════════════════════
# USER FEEDBACK - PUBLIC & USER CLIENT VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class FeedbackSubmitView(APIView):
    """
    POST /api/feedback/submit/
    Submits user feedback from Web or Mobile App.
    Open to anonymous and authenticated users.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        category = str(data.get('category', 'GENERAL')).strip().upper()
        rating_raw = data.get('rating', 5)
        message = data.get('message', '').strip()
        source = normalize_source(data.get('source'))

        user = request.user if request.user.is_authenticated else None
        client = getattr(user, 'client', None) if user else None

        if user:
            if not name:
                name = user.get_full_name() or user.username
            if not email:
                email = user.email or ''

        try:
            rating = max(1, min(5, int(rating_raw)))
        except (ValueError, TypeError):
            rating = 5

        valid_categories = ['GENERAL', 'BUG', 'FEATURE', 'UX', 'PERFORMANCE', 'BILLING']
        if category not in valid_categories:
            category = 'GENERAL'

        if not message:
            return Response({'error': 'Feedback message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        feedback = UserFeedback.objects.create(
            user=user,
            client=client,
            name=name,
            email=email,
            category=category,
            rating=rating,
            message=message,
            source=source,
            status='NEW'
        )

        # Notify platform administrators
        try:
            admin_users = User.objects.filter(
                Q(role='ADMIN') | Q(enterprise_role='SUPER_ADMIN') | Q(is_superuser=True)
            ).distinct()
            for admin in admin_users[:10]:
                InAppNotification.objects.create(
                    user=admin,
                    title=f"New User Feedback ({source} - {category})",
                    body=f"Rating {rating}/5: {message[:100]}",
                    notification_type='NEW_FEEDBACK',
                    link='/admin/feedback'
                )
        except Exception as e:
            logger.warning(f"Failed to create admin notification for feedback: {e}")

        serializer = UserFeedbackSerializer(feedback)
        return Response({
            'success': True,
            'message': 'Thank you! Your feedback has been recorded.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


class MyFeedbackListView(APIView):
    """
    GET /api/feedback/my-feedback/
    Returns all feedback submitted by the currently logged-in user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        q_filter = Q(user=user)
        if user.email:
            q_filter |= Q(email__iexact=user.email)

        feedbacks = UserFeedback.objects.filter(q_filter).prefetch_related('replies').order_by('-created_at')
        serializer = UserFeedbackSerializer(feedbacks, many=True)
        return Response(serializer.data)


class FeedbackReplyView(APIView):
    """
    POST /api/feedback/<id>/reply/
    Allows the submitting user to reply to an existing feedback thread.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        reply_body = request.data.get('message', '').strip()
        if not reply_body:
            return Response({'error': 'Reply message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            feedback = UserFeedback.objects.get(pk=pk)
        except UserFeedback.DoesNotExist:
            return Response({'error': 'Feedback entry not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_owner = (
            feedback.user_id == user.id or
            (feedback.email and user.email and feedback.email.strip().lower() == user.email.strip().lower())
        )
        if not is_owner:
            return Response({'error': 'You do not have permission to view or reply to this feedback.'}, status=status.HTTP_403_FORBIDDEN)

        if not feedback.user:
            feedback.user = user
            if user.client:
                feedback.client = user.client

        UserFeedbackReply.objects.create(
            feedback=feedback,
            sender=user,
            sender_role='USER',
            message=reply_body
        )

        feedback.status = 'IN_REVIEW'
        feedback.save(update_fields=['status', 'updated_at'])

        # Notify admins
        try:
            admin_users = User.objects.filter(
                Q(role='ADMIN') | Q(enterprise_role='SUPER_ADMIN') | Q(is_superuser=True)
            ).distinct()
            for admin in admin_users[:10]:
                InAppNotification.objects.create(
                    user=admin,
                    title=f"User Reply on Feedback #{feedback.id}",
                    body=f"{user.username}: {reply_body[:100]}",
                    notification_type='FEEDBACK_USER_REPLY',
                    link='/admin/feedback'
                )
        except Exception as e:
            logger.warning(f"Failed to notify admins: {e}")

        serializer = UserFeedbackSerializer(feedback)
        return Response({
            'success': True,
            'message': 'Reply submitted successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD VIEWS - CONTACT MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

class AdminContactMessagesListView(APIView):
    """
    GET /api/admin/contact-messages/
    Lists all contact inquiries from Web and Mobile App for Super Admins.
    Supports search, status filters, source filters, and unanswered filter.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = ContactMessage.objects.all().prefetch_related('replies', 'user', 'client')

        # Filters
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(subject__icontains=search) |
                Q(message__icontains=search)
            )

        status_param = request.query_params.get('status', '').strip().upper()
        if status_param and status_param != 'ALL':
            qs = qs.filter(status=status_param)

        source_param = request.query_params.get('source', '').strip().upper()
        if source_param and source_param != 'ALL':
            qs = qs.filter(source=source_param)

        unanswered_param = request.query_params.get('unanswered', '').strip().lower()
        if unanswered_param in ['true', '1', 'yes']:
            # Filter where status is PENDING or last reply is USER or no replies
            qs = qs.filter(
                Q(replies__isnull=True) |
                Q(status='PENDING')
            ).distinct()

        # Summary statistics
        all_count = ContactMessage.objects.count()
        pending_count = ContactMessage.objects.filter(status='PENDING').count()
        replied_count = ContactMessage.objects.filter(status='REPLIED').count()
        resolved_count = ContactMessage.objects.filter(status='RESOLVED').count()
        web_count = ContactMessage.objects.filter(source='WEB').count()
        app_count = ContactMessage.objects.filter(source='APP').count()

        serializer = ContactMessageSerializer(qs, many=True)
        return Response({
            'results': serializer.data,
            'stats': {
                'total': all_count,
                'pending': pending_count,
                'replied': replied_count,
                'resolved': resolved_count,
                'web': web_count,
                'app': app_count,
            }
        })


class AdminContactMessageDetailView(APIView):
    """
    GET /api/admin/contact-messages/<id>/
    Returns detailed conversation for a specific contact inquiry.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, pk):
        try:
            msg = ContactMessage.objects.prefetch_related('replies').get(pk=pk)
        except ContactMessage.DoesNotExist:
            return Response({'error': 'Contact inquiry not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ContactMessageSerializer(msg)
        return Response(serializer.data)


class AdminContactMessageReplyView(APIView):
    """
    POST /api/admin/contact-messages/<id>/reply/
    Admin replies to a contact inquiry.
    Persists reply permanently in DB, marks status as REPLIED,
    and dispatches in-app notification to the user.
    """
    permission_classes = [IsSuperAdminUser]

    def post(self, request, pk):
        reply_body = request.data.get('message', '').strip()
        if not reply_body:
            return Response({'error': 'Reply message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            contact_msg = ContactMessage.objects.get(pk=pk)
        except ContactMessage.DoesNotExist:
            return Response({'error': 'Contact inquiry not found.'}, status=status.HTTP_404_NOT_FOUND)

        reply = ContactMessageReply.objects.create(
            contact_message=contact_msg,
            sender=request.user,
            sender_role='ADMIN',
            message=reply_body
        )

        contact_msg.status = 'REPLIED'
        contact_msg.save(update_fields=['status', 'updated_at'])

        # Notify the user
        target_user = contact_msg.user
        if not target_user and contact_msg.email:
            target_user = User.objects.filter(email__iexact=contact_msg.email).first()

        if target_user:
            try:
                InAppNotification.objects.create(
                    user=target_user,
                    title="Admin Replied to Your Contact Inquiry",
                    body=f"Subject: {contact_msg.subject}\n{reply_body[:120]}...",
                    notification_type='CONTACT_REPLY',
                    link='/client/support'
                )
            except Exception as e:
                logger.warning(f"Failed to create notification for user: {e}")

        serializer = ContactMessageSerializer(contact_msg)
        return Response({
            'success': True,
            'message': 'Reply sent and recorded permanently.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


class AdminContactMessageStatusView(APIView):
    """
    PATCH /api/admin/contact-messages/<id>/status/
    Updates contact inquiry status (PENDING, REPLIED, RESOLVED).
    """
    permission_classes = [IsSuperAdminUser]

    def patch(self, request, pk):
        new_status = request.data.get('status', '').strip().upper()
        if new_status not in ['PENDING', 'REPLIED', 'RESOLVED']:
            return Response({'error': 'Invalid status. Choose PENDING, REPLIED, or RESOLVED.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            contact_msg = ContactMessage.objects.get(pk=pk)
        except ContactMessage.DoesNotExist:
            return Response({'error': 'Contact inquiry not found.'}, status=status.HTTP_404_NOT_FOUND)

        contact_msg.status = new_status
        contact_msg.save(update_fields=['status', 'updated_at'])

        serializer = ContactMessageSerializer(contact_msg)
        return Response({
            'success': True,
            'message': f'Status updated to {new_status}.',
            'data': serializer.data
        })


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD VIEWS - USER FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════

class AdminUserFeedbackListView(APIView):
    """
    GET /api/admin/user-feedback/
    Lists all feedback from Web and Mobile App for Super Admins.
    Supports search, category filters, status filters, and source filters.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = UserFeedback.objects.all().prefetch_related('replies', 'user', 'client')

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(message__icontains=search)
            )

        status_param = request.query_params.get('status', '').strip().upper()
        if status_param and status_param != 'ALL':
            qs = qs.filter(status=status_param)

        category_param = request.query_params.get('category', '').strip().upper()
        if category_param and category_param != 'ALL':
            qs = qs.filter(category=category_param)

        source_param = request.query_params.get('source', '').strip().upper()
        if source_param and source_param != 'ALL':
            qs = qs.filter(source=source_param)

        unanswered_param = request.query_params.get('unanswered', '').strip().lower()
        if unanswered_param in ['true', '1', 'yes']:
            qs = qs.filter(
                Q(replies__isnull=True) |
                Q(status__in=['NEW', 'IN_REVIEW'])
            ).distinct()

        all_count = UserFeedback.objects.count()
        new_count = UserFeedback.objects.filter(status='NEW').count()
        in_review_count = UserFeedback.objects.filter(status='IN_REVIEW').count()
        replied_count = UserFeedback.objects.filter(status='REPLIED').count()
        resolved_count = UserFeedback.objects.filter(status='RESOLVED').count()
        web_count = UserFeedback.objects.filter(source='WEB').count()
        app_count = UserFeedback.objects.filter(source='APP').count()

        serializer = UserFeedbackSerializer(qs, many=True)
        return Response({
            'results': serializer.data,
            'stats': {
                'total': all_count,
                'new': new_count,
                'in_review': in_review_count,
                'replied': replied_count,
                'resolved': resolved_count,
                'web': web_count,
                'app': app_count,
            }
        })


class AdminUserFeedbackDetailView(APIView):
    """
    GET /api/admin/user-feedback/<id>/
    Returns detailed conversation for a specific feedback submission.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, pk):
        try:
            feedback = UserFeedback.objects.prefetch_related('replies').get(pk=pk)
        except UserFeedback.DoesNotExist:
            return Response({'error': 'Feedback entry not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = UserFeedbackSerializer(feedback)
        return Response(serializer.data)


class AdminUserFeedbackReplyView(APIView):
    """
    POST /api/admin/user-feedback/<id>/reply/
    Admin replies to a feedback submission.
    Persists reply permanently in DB, marks status as REPLIED,
    and dispatches in-app notification to the user.
    """
    permission_classes = [IsSuperAdminUser]

    def post(self, request, pk):
        reply_body = request.data.get('message', '').strip()
        if not reply_body:
            return Response({'error': 'Reply message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            feedback = UserFeedback.objects.get(pk=pk)
        except UserFeedback.DoesNotExist:
            return Response({'error': 'Feedback entry not found.'}, status=status.HTTP_404_NOT_FOUND)

        reply = UserFeedbackReply.objects.create(
            feedback=feedback,
            sender=request.user,
            sender_role='ADMIN',
            message=reply_body
        )

        feedback.status = 'REPLIED'
        feedback.save(update_fields=['status', 'updated_at'])

        # Notify the user
        target_user = feedback.user
        if not target_user and feedback.email:
            target_user = User.objects.filter(email__iexact=feedback.email).first()

        if target_user:
            try:
                InAppNotification.objects.create(
                    user=target_user,
                    title="Admin Replied to Your Feedback",
                    body=f"Regarding '{feedback.category}':\n{reply_body[:120]}...",
                    notification_type='FEEDBACK_REPLY',
                    link='/client/support'
                )
            except Exception as e:
                logger.warning(f"Failed to create notification for user: {e}")

        serializer = UserFeedbackSerializer(feedback)
        return Response({
            'success': True,
            'message': 'Reply sent and recorded permanently.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)


class AdminUserFeedbackStatusView(APIView):
    """
    PATCH /api/admin/user-feedback/<id>/status/
    Updates feedback status (NEW, IN_REVIEW, REPLIED, RESOLVED).
    """
    permission_classes = [IsSuperAdminUser]

    def patch(self, request, pk):
        new_status = request.data.get('status', '').strip().upper()
        if new_status not in ['NEW', 'IN_REVIEW', 'REPLIED', 'RESOLVED']:
            return Response({'error': 'Invalid status. Choose NEW, IN_REVIEW, REPLIED, or RESOLVED.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            feedback = UserFeedback.objects.get(pk=pk)
        except UserFeedback.DoesNotExist:
            return Response({'error': 'Feedback entry not found.'}, status=status.HTTP_404_NOT_FOUND)

        feedback.status = new_status
        feedback.save(update_fields=['status', 'updated_at'])

        serializer = UserFeedbackSerializer(feedback)
        return Response({
            'success': True,
            'message': f'Status updated to {new_status}.',
            'data': serializer.data
        })


# ══════════════════════════════════════════════════════════════════════════════
# IN-APP NOTIFICATIONS VIEW
# ══════════════════════════════════════════════════════════════════════════════

class InAppNotificationListView(APIView):
    """
    GET /api/notifications/
    POST /api/notifications/mark-all-read/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        notifications = InAppNotification.objects.filter(user=user).order_by('-created_at')[:50]
        unread_count = InAppNotification.objects.filter(user=user, is_read=False).count()
        serializer = InAppNotificationSerializer(notifications, many=True)
        return Response({
            'unread_count': unread_count,
            'results': serializer.data
        })

    def post(self, request):
        # Mark all as read
        InAppNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'success': True, 'message': 'All notifications marked as read.'})


class InAppNotificationMarkReadView(APIView):
    """
    POST /api/notifications/<id>/mark-read/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notif = InAppNotification.objects.get(pk=pk, user=request.user)
            notif.is_read = True
            notif.save(update_fields=['is_read'])
            return Response({'success': True})
        except InAppNotification.DoesNotExist:
            return Response({'error': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
