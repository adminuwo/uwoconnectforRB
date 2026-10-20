"""
Google OAuth 2.0 Diagnostic, Scope Registry, and Verification Management Views.
Allows developers and automated testing suites to inspect OAuth configuration,
verify scope least-privilege compliance, and test reviewer bypass without exposing secrets.
"""

import os
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from ..services.google_oauth_service import (
    GOOGLE_SCOPES_AUDIT_REGISTRY,
    SHEETS_SCOPES,
    GMAIL_SCOPES,
    SLIDES_SCOPES,
    DOCS_SCOPES,
    CALENDAR_SCOPES,
    YOUTUBE_SCOPES,
    ALL_ACTIVE_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    generate_google_auth_url,
    is_google_verification_account,
)

logger = logging.getLogger(__name__)


class GoogleOAuthScopesView(APIView):
    """
    GET /api/auth/google/scopes/
    Returns the comprehensive Google OAuth scope audit registry,
    documenting all 10 scopes reviewed by Google, their least-privilege status,
    and associated application features.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        active_map = {
            "gmail": GMAIL_SCOPES,
            "google_calendar": CALENDAR_SCOPES,
            "calendar": CALENDAR_SCOPES,
            "google_sheets": SHEETS_SCOPES,
            "sheets": SHEETS_SCOPES,
            "google_docs": DOCS_SCOPES,
            "docs": DOCS_SCOPES,
            "google_slides": SLIDES_SCOPES,
            "slides": SLIDES_SCOPES,
            "youtube": YOUTUBE_SCOPES,
        }
        retained = sum(1 for s in GOOGLE_SCOPES_AUDIT_REGISTRY.values() if s["status"] == "RETAINED")
        removed = sum(1 for s in GOOGLE_SCOPES_AUDIT_REGISTRY.values() if s["status"] != "RETAINED")
        return Response({
            "status": "success",
            "scope_audit_registry": GOOGLE_SCOPES_AUDIT_REGISTRY,
            "audit_registry": GOOGLE_SCOPES_AUDIT_REGISTRY,
            "active_services": active_map,
            "active_service_scopes": active_map,
            "all_active_scopes": ALL_ACTIVE_SCOPES,
            "total_audited_scopes": len(GOOGLE_SCOPES_AUDIT_REGISTRY),
            "retained_scopes_count": retained,
            "removed_scopes_count": removed,
            "least_privilege_note": "calendar.calendars and broad youtube scope purged under least privilege."
        })


class GoogleOAuthDiagnosticView(APIView):
    """
    GET /api/auth/google/diagnostic/
    Provides diagnostic status of Google OAuth configurations without exposing secrets.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        creds = get_google_credentials()
        has_client_id = bool(creds["client_id"])
        has_client_secret = bool(creds["client_secret"])

        is_reviewer = is_google_verification_account(client, request.user)

        redirect_uris = {
            "gmail": get_google_redirect_uri("gmail", request=request),
            "calendar": get_google_redirect_uri("calendar", request=request),
            "sheets": get_google_redirect_uri("sheets", request=request),
            "docs": get_google_redirect_uri("docs", request=request),
            "slides": get_google_redirect_uri("slides", request=request),
            "youtube": get_google_redirect_uri("youtube", request=request),
        }

        # Check connector enablement on client
        connectors_status = {}
        if client:
            connectors_status = {
                "gmail_enabled": bool(client.gmail_enabled),
                "calendar_enabled": bool(client.google_calendar_enabled),
                "sheets_enabled": bool(client.google_sheets_enabled),
                "docs_enabled": bool(client.google_docs_enabled),
                "slides_enabled": bool(client.google_slides_enabled),
                "youtube_enabled": bool(client.youtube_enabled),
            }

        retained = sum(1 for s in GOOGLE_SCOPES_AUDIT_REGISTRY.values() if s["status"] == "RETAINED")
        removed = sum(1 for s in GOOGLE_SCOPES_AUDIT_REGISTRY.values() if s["status"] != "RETAINED")

        return Response({
            "status": "success",
            "oauth_configured": has_client_id and has_client_secret,
            "oauth_credentials_configured": has_client_id and has_client_secret,
            "has_client_id": has_client_id,
            "has_client_secret": has_client_secret,
            "client_id_prefix": creds["client_id"][:12] + "..." if has_client_id else None,
            "is_verification_account": is_reviewer,
            "client_plan": getattr(client, "plan", "FREE") if client else None,
            "connectors_status": connectors_status,
            "resolved_redirect_uris": redirect_uris,
            "server_origin": request.build_absolute_uri("/"),
            "scopes_audit": GOOGLE_SCOPES_AUDIT_REGISTRY,
            "retained_scopes_count": retained,
            "removed_scopes_count": removed,
        })


class GoogleOAuthConnectAllView(APIView):
    """
    GET /api/auth/google/connect-all/
    Initiates Google OAuth flow requesting ALL approved scopes in a single consent screen.
    Designed specifically for Google Verification video demonstration and full workspace authorization.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        auth_data = generate_google_auth_url("all", client.id, scopes=ALL_ACTIVE_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({
            "url": auth_data["url"],
            "auth_url": auth_data["url"],
            "scopes": ALL_ACTIVE_SCOPES,
            "scopes_requested": ALL_ACTIVE_SCOPES,
        })
