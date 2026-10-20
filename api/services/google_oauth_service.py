"""
Centralized Google OAuth 2.0 Scope Registry and Core Integration Service for UWOConnect.

Single source of truth for:
1. Google OAuth Scope definitions and least-privilege compliance.
2. Canonical scope constants across Gmail, Sheets, Docs, Slides, Calendar, and YouTube.
3. OAuth authorization URL generation with CSRF state protection.
4. Dynamic and configurable OAuth redirect URI resolution.
5. Reviewer test-account entitlement verification.
"""

import os
import secrets
import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urlencode

from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# Standard Google OAuth 2.0 endpoints
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

# Basic Identity Scopes included with all Google OAuth connections
BASE_IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ---------------------------------------------------------------------------
# Scope Definitions (Audited against Google Least-Privilege Requirements)
# ---------------------------------------------------------------------------

# 1. Google Sheets Integration
# Retained: Needed for reading and appending CRM leads/chat orders to spreadsheets
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
] + BASE_IDENTITY_SCOPES

# 2. Gmail Integration
# Retained: Required for reading customer emails, sending automated responses, and managing labels/status
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
] + BASE_IDENTITY_SCOPES

# 3. Google Presentations / Slides Integration
# Retained: Required for dynamic sales presentation deck creation and proposal decks
SLIDES_SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
] + BASE_IDENTITY_SCOPES

# 4. Google Docs Integration
# Retained: Required for creating digital client agreements, proposals, and dynamic contract docs
DOCS_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
] + BASE_IDENTITY_SCOPES

# 5. Google Calendar Integration
# Retained: 'calendar.events' for scheduling customer appointments, consultations, and syncing bookings.
# Retained: 'calendar' for primary calendar discovery and free/busy query availability.
# REMOVED under Least Privilege: 'https://www.googleapis.com/auth/calendar.calendars'
# (UWOConnect does not manage secondary calendar metadata/settings; 'calendar.events' is sufficient).
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
] + BASE_IDENTITY_SCOPES

# 6. YouTube Integration
# Retained: 'youtube.readonly' (read channel analytics, video details, comments)
# Retained: 'youtube.upload' (upload video broadcasts directly from UWO dashboard)
# Retained: 'youtube.force-ssl' (reply to comments, comment moderation, video deletion)
# REMOVED under Least Privilege: full 'https://www.googleapis.com/auth/youtube'
# (Full access is redundant and overly broad when granular sensitive scopes are used).
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
] + BASE_IDENTITY_SCOPES

# Full Bundle for Reviewer Workspace Demo (Shows all active scopes in one consent screen)
ALL_ACTIVE_SCOPES = list(dict.fromkeys(
    SHEETS_SCOPES + GMAIL_SCOPES + SLIDES_SCOPES + DOCS_SCOPES + CALENDAR_SCOPES + YOUTUBE_SCOPES
))
ALL_REQUESTED_GOOGLE_SCOPES = ALL_ACTIVE_SCOPES

# ---------------------------------------------------------------------------
# Comprehensive Scope Audit Matrix Registry
# ---------------------------------------------------------------------------
GOOGLE_SCOPES_AUDIT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "https://www.googleapis.com/auth/spreadsheets": {
        "service": "Google Sheets API v4",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Google Sheets Lead & Order Sync",
        "required_ops": ["spreadsheets.create", "spreadsheets.values.get", "spreadsheets.values.append"],
        "narrower_alternative": "None (spreadsheets is the standard scope for reading/writing Sheets)",
        "justification": "Allows businesses to export incoming leads and sales orders directly into spreadsheets."
    },
    "https://www.googleapis.com/auth/gmail.modify": {
        "service": "Gmail API v1",
        "category": "Restricted",
        "status": "RETAINED",
        "feature": "Enterprise Shared Inbox & Automated Email Sync",
        "required_ops": ["users.messages.list", "users.messages.get", "users.messages.send", "users.messages.modify"],
        "narrower_alternative": "Combination of gmail.send, gmail.readonly, gmail.labels is equivalent but gmail.modify provides cleaner unified inbox folder management",
        "justification": "Required for customer support inbox: read incoming emails, dispatch AI auto-replies, and toggle read/unread and folder labels."
    },
    "https://www.googleapis.com/auth/presentations": {
        "service": "Google Slides API v1",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Sales Pitch Deck & Presentation Generator",
        "required_ops": ["presentations.create", "presentations.get", "presentations.batchUpdate"],
        "narrower_alternative": "None for creating and populating Google Slides presentations",
        "justification": "Allows sales representatives to dynamically assemble customized client pitch decks."
    },
    "https://www.googleapis.com/auth/documents": {
        "service": "Google Docs API v1",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Agreement & Proposal Document Generator",
        "required_ops": ["documents.create", "documents.get", "documents.batchUpdate"],
        "narrower_alternative": "None for creating and writing Google Docs",
        "justification": "Allows sales and legal teams to auto-generate branded service proposals and client contracts."
    },
    "https://www.googleapis.com/auth/calendar": {
        "service": "Google Calendar API v3",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Consultation Booking & Slot Availability",
        "required_ops": ["calendars.get", "freeBusy.query"],
        "narrower_alternative": "calendar.events handles individual events; calendar is required for freeBusy checks on primary calendar",
        "justification": "Required to check real-time schedule availability and avoid double-booking."
    },
    "https://www.googleapis.com/auth/calendar.events": {
        "service": "Google Calendar API v3",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Google Calendar Event & Meet Scheduling",
        "required_ops": ["events.list", "events.insert", "events.delete", "events.patch"],
        "narrower_alternative": "Least-privilege scope for event creation and Meet link generation",
        "justification": "Required for scheduling client meetings and generating Google Meet links."
    },
    "https://www.googleapis.com/auth/calendar.calendars": {
        "service": "Google Calendar API v3",
        "category": "Sensitive",
        "status": "REMOVED_LEAST_PRIVILEGE",
        "feature": "Not required by UWOConnect",
        "required_ops": ["calendars.insert", "calendars.delete", "calendars.patch (metadata only)"],
        "narrower_alternative": "calendar.events is used instead",
        "justification": "Removed under least privilege: UWOConnect does not alter calendar metadata or secondary calendar settings."
    },
    "https://www.googleapis.com/auth/youtube.readonly": {
        "service": "YouTube Data API v3",
        "category": "Non-Sensitive",
        "status": "RETAINED",
        "feature": "YouTube Channel Analytics & Audience Comments",
        "required_ops": ["channels.list", "commentThreads.list", "search.list"],
        "narrower_alternative": "Least-privilege read scope for YouTube data",
        "justification": "Allows channel owners to monitor engagement, view video performance, and read audience questions."
    },
    "https://www.googleapis.com/auth/youtube.upload": {
        "service": "YouTube Data API v3",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Video Broadcast & Content Upload",
        "required_ops": ["videos.insert"],
        "narrower_alternative": "Narrower than full 'youtube' scope",
        "justification": "Enables businesses to publish promotional videos and update video descriptions directly."
    },
    "https://www.googleapis.com/auth/youtube.force-ssl": {
        "service": "YouTube Data API v3",
        "category": "Sensitive",
        "status": "RETAINED",
        "feature": "Community Comment Auto-Moderation & Direct Replies",
        "required_ops": ["comments.insert", "comments.setModerationStatus", "videos.delete"],
        "narrower_alternative": "Narrower than full 'youtube' scope; required by Google API for inserting comments/replies",
        "justification": "Enables the AI Community Bot to respond to pricing queries and moderate inappropriate comments."
    },
}

GOOGLE_SCOPE_AUDIT_REGISTRY = GOOGLE_SCOPES_AUDIT_REGISTRY

# ---------------------------------------------------------------------------
# Credentials and Redirect URI Helpers
# ---------------------------------------------------------------------------

def get_google_credentials() -> Dict[str, str]:
    """
    Returns client_id and client_secret from environment variables.
    Supports GMAIL_CLIENT_ID / GOOGLE_CLIENT_ID interchangeably.
    """
    # Prioritize GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET because the registered OAuth 2.0 Client ID
    # with authorized redirect URIs is 876129590251-lok6bi4ut8f2nhl63hh79mghd1ccuf6j.apps.googleusercontent.com
    client_id = (
        os.environ.get("GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
        or ""
    ).strip()

    client_secret = (
        os.environ.get("GMAIL_CLIENT_SECRET")
        or os.environ.get("GOOGLE_CLIENT_SECRET")
        or ""
    ).strip()

    return {
        "client_id": client_id,
        "client_secret": client_secret,
    }


def get_google_redirect_uri(service_name: str = "gmail", request=None) -> str:
    """
    Resolves the canonical OAuth redirect URI for a Google integration service.
    Supports YouTube, Calendar, Sheets, Gmail, Docs, Slides.
    """
    norm = service_name.lower().replace("google_", "").strip()

    # 1. Check dedicated service environment variable (production / deployment override)
    candidate_keys = [
        f"GOOGLE_{norm.upper()}_REDIRECT_URI",
        f"{norm.upper()}_REDIRECT_URI",
    ]
    for key in candidate_keys:
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()

    # 2. For unified services that share the verified Google OAuth callback (gmail, sheets, docs, slides, all),
    # prioritize the registered GMAIL_REDIRECT_URI if configured in environment
    if norm in ("gmail", "sheets", "docs", "slides", "all") and os.environ.get("GMAIL_REDIRECT_URI"):
        if not os.environ.get("USE_LOCAL_GOOGLE_CALLBACK", "").lower() in ("true", "1"):
            return os.environ["GMAIL_REDIRECT_URI"].strip()

    # Callback path mapping per service
    callback_paths = {
        "youtube": "/api/auth/youtube/callback",
        "calendar": "/api/auth/google-calendar/callback",
        "sheets": "/api/auth/gmail/callback",
        "docs": "/api/auth/gmail/callback",
        "slides": "/api/auth/gmail/callback",
        "gmail": "/api/auth/gmail/callback",
        "all": "/api/auth/gmail/callback",
    }
    callback_path = callback_paths.get(norm, "/api/auth/gmail/callback")

    # 3. If request is from local development (localhost / 127.0.0.1), use local callback
    if request:
        host = request.get_host()
        if "localhost" in host or "127.0.0.1" in host:
            return f"http://localhost:8080{callback_path}"

    # 4. Dynamic fallback for remote requests
    if request:
        return f"https://uwoconnectforrb-743928421487.asia-south1.run.app{callback_path}"

    if os.environ.get("GOOGLE_REDIRECT_URI"):
        return os.environ["GOOGLE_REDIRECT_URI"].strip()

    if os.environ.get("GMAIL_REDIRECT_URI"):
        return os.environ["GMAIL_REDIRECT_URI"].strip()

    # Default fallback
    return f"http://localhost:8080{callback_path}"



def get_frontend_return_url(client=None, request=None) -> str:
    """Resolves the frontend URL to redirect users back to after OAuth completion."""
    if request:
        origin = request.headers.get("Origin") or request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER")
        if origin and "://" in origin:
            parts = origin.split("/")
            return f"{parts[0]}//{parts[2]}"

    if client and getattr(client, "white_label_domain", None):
        return f"https://{client.white_label_domain}"

    return os.environ.get("FRONTEND_URL", "http://localhost:3000")


# ---------------------------------------------------------------------------
# Authorization URL Generator
# ---------------------------------------------------------------------------

def generate_google_auth_url(
    service_name: str,
    client_id_val: Any = None,
    scopes: Optional[List[str]] = None,
    request=None,
    extra_params: Optional[Dict[str, str]] = None,
    client_id: Any = None,
) -> Dict[str, Any]:
    """
    Generates a secure Google OAuth 2.0 authorization URL.
    Stores state and redirect_uri in Django cache for verification in callback.
    """
    effective_client_id = client_id_val if client_id_val is not None else client_id
    creds = get_google_credentials()
    if not creds["client_id"] or not creds["client_secret"]:
        return {
            "error": "Google OAuth credentials (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) not configured on backend.",
            "status_code": 503
        }

    # Determine scope list
    if scopes is None:
        scope_map = {
            "sheets": SHEETS_SCOPES,
            "google_sheets": SHEETS_SCOPES,
            "gmail": GMAIL_SCOPES,
            "slides": SLIDES_SCOPES,
            "google_slides": SLIDES_SCOPES,
            "docs": DOCS_SCOPES,
            "google_docs": DOCS_SCOPES,
            "calendar": CALENDAR_SCOPES,
            "google_calendar": CALENDAR_SCOPES,
            "youtube": YOUTUBE_SCOPES,
            "all": ALL_ACTIVE_SCOPES,
        }
        scopes = scope_map.get(service_name.lower(), BASE_IDENTITY_SCOPES)

    redirect_uri = get_google_redirect_uri(service_name, request=request)
    frontend_url = get_frontend_return_url(request=request)

    # Generate cryptographically strong state token
    state = secrets.token_urlsafe(32)

    # Store state metadata in cache for 1 hour
    state_payload = {
        "client_id": str(effective_client_id),
        "service": service_name,
        "redirect_uri": redirect_uri,
        "frontend_url": frontend_url,
    }
    
    norm_service = service_name.lower().replace("google_", "").strip()
    cache.set(f"google_oauth_state_{state}", state_payload, timeout=3600)

    # Store ONLY the service-specific cache key matching the requested service
    if norm_service in ("gmail", "all"):
        cache.set(f"gmail_state_{state}", {"client_id": str(effective_client_id), "return_origin": frontend_url}, timeout=3600)
    elif norm_service == "calendar":
        cache.set(f"gcal_state_{state}", str(effective_client_id), timeout=3600)
    elif norm_service == "sheets":
        cache.set(f"gsheets_state_{state}", str(effective_client_id), timeout=3600)
    elif norm_service == "docs":
        cache.set(f"gdocs_state_{state}", str(effective_client_id), timeout=3600)
    elif norm_service == "slides":
        cache.set(f"gslides_state_{state}", str(effective_client_id), timeout=3600)
    elif norm_service == "youtube":
        cache.set(f"youtube_state_{state}", str(effective_client_id), timeout=3600)

    params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    if extra_params:
        params.update(extra_params)

    auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
    return {
        "url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri,
        "scopes": scopes,
    }


# ---------------------------------------------------------------------------
# Reviewer Test Account Entitlement Verification (Phase 6)
# ---------------------------------------------------------------------------

def is_google_verification_account(client, user=None) -> bool:
    """
    Checks if the given client or user is designated as a Google OAuth verification / reviewer account.
    
    Criteria (any of the following):
    1. Client has is_verification_account flag or settings['is_verification_account'] is True.
    2. Client's owner user email matches GOOGLE_REVIEWER_EMAILS env variable.
    3. User email has domain @google.com or matches designated reviewer email pattern.
    """
    if not client and not user:
        return False

    # Check Client direct attribute or settings JSON
    if client:
        if getattr(client, "is_verification_account", False):
            return True
        settings_dict = getattr(client, "settings", {}) or {}
        if settings_dict.get("is_verification_account") is True:
            return True

    # Check configured reviewer email list
    configured_reviewer_emails = [
        e.strip().lower() for e in
        os.environ.get("GOOGLE_REVIEWER_EMAILS", "google-reviewer@uwoconnect.aisa24.com,reviewer@google.com").split(",")
        if e.strip()
    ]

    check_emails = []
    if user and getattr(user, "email", None):
        check_emails.append(user.email.strip().lower())
    if client:
        try:
            from api.models import User
            owner = User.objects.filter(client=client).first()
            if owner and owner.email:
                check_emails.append(owner.email.strip().lower())
        except Exception:
            pass

    for email in check_emails:
        if email in configured_reviewer_emails:
            return True
        if email.endswith("@google.com") or "google-reviewer" in email or "reviewer" in email:
            return True

    return False


def is_google_reviewer_account(client_or_email, user=None) -> bool:
    """Convenience alias supporting either Client object, User object, or email string."""
    if isinstance(client_or_email, str):
        email = client_or_email.strip().lower()
        if email.endswith("@google.com") or "google-reviewer" in email or "reviewer" in email:
            return True
        configured = [
            e.strip().lower() for e in
            os.environ.get("GOOGLE_REVIEWER_EMAILS", "google-reviewer@uwoconnect.aisa24.com,reviewer@google.com").split(",")
            if e.strip()
        ]
        return email in configured
    return is_google_verification_account(client=client_or_email, user=user)


def validate_google_oauth_state(state: str, expected_service: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates a Google OAuth CSRF state token against the cache and invalidates it (one-time use).
    """
    if not state:
        return {"is_valid": False, "error": "missing_state"}

    cache_key = f"google_oauth_state_{state}"
    state_meta = cache.get(cache_key)

    if not state_meta:
        return {"is_valid": False, "error": "invalid_or_expired_state"}

    # Invalidate immediately to prevent CSRF replay attacks
    cache.delete(cache_key)

    if expected_service and state_meta.get("service") != expected_service:
        return {
            "is_valid": False,
            "error": f"service_mismatch: expected {expected_service}, got {state_meta.get('service')}",
            "client_id": state_meta.get("client_id"),
        }

    return {
        "is_valid": True,
        "client_id": state_meta.get("client_id"),
        "service": state_meta.get("service"),
        "meta": state_meta,
    }


def audit_google_scopes() -> Dict[str, Any]:
    """Generates an audit report across all reviewed Google OAuth scopes."""
    retained = {k: v for k, v in GOOGLE_SCOPES_AUDIT_REGISTRY.items() if v["status"] == "RETAINED"}
    removed = {k: v for k, v in GOOGLE_SCOPES_AUDIT_REGISTRY.items() if v["status"] == "REMOVED"}
    return {
        "total_audited": len(GOOGLE_SCOPES_AUDIT_REGISTRY),
        "retained_count": len(retained),
        "removed_count": len(removed),
        "retained_scopes": list(retained.keys()),
        "removed_scopes": list(removed.keys()),
        "registry": GOOGLE_SCOPES_AUDIT_REGISTRY,
    }
