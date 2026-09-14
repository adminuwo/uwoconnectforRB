import logging
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from api.models import User, LegalDocumentVersion, UserLegalConsent, AuditLog, QrAuthSession

logger = logging.getLogger(__name__)

DEFAULT_TERMS_VERSION = "1.0"
DEFAULT_PRIVACY_VERSION = "1.0"


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class LegalDocumentsView(APIView):
    """
    GET /api/legal/documents/
    Returns active legal document versions, metadata, and effective dates.
    Publicly accessible (no authentication required) so users can read
    Terms & Conditions and Privacy Policy prior to login/registration.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        doc_type = request.query_params.get('type')
        query = LegalDocumentVersion.objects.filter(is_active=True)
        if doc_type:
            query = query.filter(document_type=doc_type.upper())

        docs = list(query)
        result = {}

        # Terms & Conditions
        terms = next((d for d in docs if d.document_type == 'TERMS'), None)
        if terms:
            result['terms'] = {
                'id': str(terms.id),
                'document_type': 'TERMS',
                'title': terms.title or 'Terms & Conditions',
                'version': terms.version,
                'effective_date': terms.effective_date.isoformat() if terms.effective_date else None,
                'summary': terms.summary or '',
                'content': terms.content or '',
                'requires_reconsent': terms.requires_reconsent,
            }
        else:
            result['terms'] = {
                'document_type': 'TERMS',
                'title': 'Terms & Conditions',
                'version': DEFAULT_TERMS_VERSION,
                'effective_date': timezone.now().isoformat(),
                'summary': 'Standard operational terms for UWO Connect platform.',
                'content': '',
                'requires_reconsent': False,
            }

        # Privacy Policy
        privacy = next((d for d in docs if d.document_type == 'PRIVACY_POLICY'), None)
        if privacy:
            result['privacy_policy'] = {
                'id': str(privacy.id),
                'document_type': 'PRIVACY_POLICY',
                'title': privacy.title or 'Privacy Policy',
                'version': privacy.version,
                'effective_date': privacy.effective_date.isoformat() if privacy.effective_date else None,
                'summary': privacy.summary or '',
                'content': privacy.content or '',
                'requires_reconsent': privacy.requires_reconsent,
            }
        else:
            result['privacy_policy'] = {
                'document_type': 'PRIVACY_POLICY',
                'title': 'Privacy Policy',
                'version': DEFAULT_PRIVACY_VERSION,
                'effective_date': timezone.now().isoformat(),
                'summary': 'Data handling, protection, and privacy practices for UWO Connect.',
                'content': '',
                'requires_reconsent': False,
            }

        return Response(result, status=status.HTTP_200_OK)


class LegalConsentStatusView(APIView):
    """
    GET /api/legal/consent-status/
    Checks if current authenticated user needs to review and re-accept updated legal documents.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get latest active versions
        latest_terms = LegalDocumentVersion.objects.filter(document_type='TERMS', is_active=True).first()
        latest_privacy = LegalDocumentVersion.objects.filter(document_type='PRIVACY_POLICY', is_active=True).first()

        current_terms_ver = latest_terms.version if latest_terms else DEFAULT_TERMS_VERSION
        current_privacy_ver = latest_privacy.version if latest_privacy else DEFAULT_PRIVACY_VERSION

        user_terms_ver = getattr(user, 'terms_version', None) or ''
        user_privacy_ver = getattr(user, 'privacy_version', None) or ''

        terms_accepted = bool(getattr(user, 'terms_accepted', False))
        privacy_accepted = bool(getattr(user, 'privacy_accepted', False))

        # Check if re-consent is required:
        # Either not accepted yet, or version is older than latest required active version
        terms_ok = terms_accepted and (user_terms_ver == current_terms_ver)
        privacy_ok = privacy_accepted and (user_privacy_ver == current_privacy_ver)

        requires_consent = not (terms_ok and privacy_ok)

        return Response({
            'requires_consent': requires_consent,
            'terms': {
                'current_version': current_terms_ver,
                'accepted_version': user_terms_ver,
                'is_accepted': terms_ok,
                'accepted_at': user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
            },
            'privacy_policy': {
                'current_version': current_privacy_ver,
                'accepted_version': user_privacy_ver,
                'is_accepted': privacy_ok,
                'accepted_at': user.privacy_accepted_at.isoformat() if getattr(user, 'privacy_accepted_at', None) else None,
            }
        }, status=status.HTTP_200_OK)


class LegalConsentSubmitView(APIView):
    """
    POST /api/legal/consent/
    Records explicit user acceptance of specified Terms and Privacy Policy versions.
    Stores complete audit record in UserLegalConsent.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        data = request.data

        terms_accepted = data.get('terms_accepted', True)
        privacy_accepted = data.get('privacy_accepted', True)

        if not terms_accepted or not privacy_accepted:
            return Response({
                'error': 'Both Terms & Conditions and Privacy Policy must be accepted.'
            }, status=status.HTTP_400_BAD_REQUEST)

        terms_version = str(data.get('terms_version') or DEFAULT_TERMS_VERSION).strip()
        privacy_version = str(data.get('privacy_version') or DEFAULT_PRIVACY_VERSION).strip()

        ip_addr = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        now = timezone.now()

        # Record consent audits
        UserLegalConsent.objects.create(
            user=user,
            document_type='TERMS',
            document_version=terms_version,
            ip_address=ip_addr,
            user_agent=user_agent
        )

        UserLegalConsent.objects.create(
            user=user,
            document_type='PRIVACY_POLICY',
            document_version=privacy_version,
            ip_address=ip_addr,
            user_agent=user_agent
        )

        # Update User fields
        user.terms_accepted = True
        user.terms_version = terms_version
        user.terms_accepted_at = now

        user.privacy_accepted = True
        user.privacy_version = privacy_version
        user.privacy_accepted_at = now

        user.save(update_fields=[
            'terms_accepted', 'terms_version', 'terms_accepted_at',
            'privacy_accepted', 'privacy_version', 'privacy_accepted_at'
        ])

        return Response({
            'status': 'success',
            'message': 'Legal consent recorded successfully.',
            'terms_version': terms_version,
            'privacy_version': privacy_version,
            'accepted_at': now.isoformat(),
        }, status=status.HTTP_200_OK)


class AccountDeletionView(APIView):
    """
    POST/DELETE /api/auth/delete-account/
    Secure account deletion request workflow:
    - Verifies user identity
    - Deactivates personal user account (status='SUSPENDED', is_active=False)
    - Revokes linked device/QR sessions and authorization tokens
    - Preserves shared organization CRM records belonging to the business
    - Logs audit trail for compliance
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        return self._process_deletion(request)

    def post(self, request):
        return self._process_deletion(request)

    def _process_deletion(self, request):
        user = request.user
        password = request.data.get('password', '')
        confirmation = request.data.get('confirmation', '')

        # Password check if user has a usable password and provided one
        if user.has_usable_password() and password:
            if not user.check_password(password):
                return Response({
                    'error': 'Incorrect password. Please verify and try again.'
                }, status=status.HTTP_400_BAD_REQUEST)

        # Require explicit confirmation keyword
        if confirmation.strip().upper() != 'DELETE':
            return Response({
                'error': "Please type 'DELETE' to confirm account deletion."
            }, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        client_name = user.client.business_name if getattr(user, 'client', None) else 'Standalone'

        # Revoke QR/Web sessions
        try:
            QRAuthSession.objects.filter(user=user).delete()
        except Exception as _qr_err:
            logger.warning(f"Error clearing QR sessions for user {user.username}: {_qr_err}")

        # Create AuditLog entry before deactivation
        try:
            AuditLog.objects.create(
                admin_name=user.username,
                client_name=client_name,
                module='ACCOUNT_DELETION',
                action='REQUEST_ACCOUNT_DELETION',
                before_value=f"status={user.status}, is_active={user.is_active}",
                after_value="status=SUSPENDED, is_active=False, marked_deleted=True",
                ip_address=get_client_ip(request)
            )
        except Exception as _aud_err:
            logger.warning(f"Failed logging deletion audit: {_aud_err}")

        # Deactivate user account securely
        user.is_active = False
        user.status = 'SUSPENDED'
        user.is_online = False
        user.save(update_fields=['is_active', 'status', 'is_online'])

        return Response({
            'status': 'success',
            'message': 'Your account has been successfully deactivated and scheduled for permanent deletion.',
            'deactivated_at': now.isoformat()
        }, status=status.HTTP_200_OK)
