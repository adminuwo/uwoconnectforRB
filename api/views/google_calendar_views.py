"""
Google Calendar Integration Views
Handles OAuth2 connection, status checking, event synchronization, event booking, and disconnection.
"""
import os
import secrets
import logging
import requests
from datetime import datetime, timezone

from django.core.cache import cache
from django.http import HttpResponseRedirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..services.google_calendar_service import (
    _get_credentials,
    list_upcoming_events,
    create_calendar_event,
    get_valid_calendar_token,
)
from ..serializers import ClientSerializer

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

CALENDAR_SCOPES = " ".join([
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
])


class GoogleCalendarConnectView(APIView):
    """Initiate Google OAuth flow for Google Calendar integration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        creds = _get_credentials()
        if not creds["client_id"] or not creds["client_secret"]:
            return Response(
                {"error": "Google OAuth credentials not configured on backend (GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET)."},
                status=503,
            )

        state = secrets.token_urlsafe(32)
        cache.set(f"gcal_state_{state}", client.id, timeout=600)
        cache.set(f"calendar_state_{state}", client.id, timeout=3600)

        auth_url = (
            f"{GOOGLE_AUTH_ENDPOINT}"
            f"?client_id={creds['client_id']}"
            f"&response_type=code"
            f"&redirect_uri={creds['redirect_uri']}"
            f"&scope={CALENDAR_SCOPES}"
            f"&state={state}"
            f"&access_type=offline"
            f"&prompt=consent"
        )
        return Response({"url": auth_url})


class GoogleCalendarCallbackView(APIView):
    """Callback view called by Google after user approves Calendar access."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error={error}")

        if not code or not state:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=missing_code_or_state")

        client_id_val = cache.get(f"gcal_state_{state}") or cache.get(f"calendar_state_{state}")
        if not client_id_val:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=invalid_or_expired_state")

        cache.delete(f"gcal_state_{state}")
        cache.delete(f"calendar_state_{state}")

        try:
            from api.models import Client
            client_obj = Client.objects.get(id=client_id_val)
        except Exception:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=client_not_found")

        creds = _get_credentials()
        token_payload = {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "code": code,
            "redirect_uri": creds["redirect_uri"],
            "grant_type": "authorization_code",
        }
        token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload, timeout=20)
        if token_resp.status_code != 200:
            logger.error("Google Calendar token exchange failed: %s", token_resp.text)
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=token_exchange_failed")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        now_ts = datetime.now(timezone.utc).timestamp()

        # Fetch user info (email & profile)
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        email = userinfo_resp.json().get("email", "") if userinfo_resp.status_code == 200 else ""

        existing_config = client_obj.google_calendar_config or {}
        client_obj.google_calendar_enabled = True
        client_obj.google_calendar_config = {
            "account_email": email,
            "primary_calendar_id": email or "primary",
            "timezone": "Asia/Kolkata",
            "access_token": access_token,
            "refresh_token": refresh_token or existing_config.get("refresh_token"),
            "token_expires_at": now_ts + expires_in,
            "auto_sync_whatsapp": True,
            "auto_sync_crm": True,
            "default_duration": 30,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "events_count": 0,
        }
        client_obj.save()

        return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_connected=true")


class GoogleCalendarStatusView(APIView):
    """Retrieve Google Calendar connection status and upcoming events."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client or not client.google_calendar_enabled:
            return Response({"connected": False})

        config = client.google_calendar_config or {}
        events = []
        try:
            events = list_upcoming_events(client, max_results=10)
        except Exception as e:
            logger.warning("Failed fetching upcoming Google Calendar events: %s", e)

        return Response({
            "connected": True,
            "account_email": config.get("account_email", ""),
            "primary_calendar_id": config.get("primary_calendar_id", "primary"),
            "timezone": config.get("timezone", "Asia/Kolkata"),
            "auto_sync_whatsapp": config.get("auto_sync_whatsapp", True),
            "auto_sync_crm": config.get("auto_sync_crm", True),
            "default_duration": config.get("default_duration", 30),
            "last_sync_time": config.get("last_sync_time"),
            "events": events,
        })


class GoogleCalendarSyncView(APIView):
    """Refresh calendar events and update sync timestamp."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_calendar_enabled:
            return Response({"error": "Google Calendar is not connected."}, status=400)

        try:
            events = list_upcoming_events(client, max_results=20)
            config = client.google_calendar_config or {}
            config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
            config["events_count"] = len(events)
            client.google_calendar_config = config
            client.save(update_fields=["google_calendar_config"])

            return Response({
                "success": True,
                "events_count": len(events),
                "events": events,
                "message": "Google Calendar synced successfully.",
            })
        except Exception as e:
            logger.error("Google Calendar sync error: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleCalendarCreateEventView(APIView):
    """Book/create a new Google Calendar event directly from UWOConnect."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_calendar_enabled:
            return Response({"error": "Google Calendar is not connected."}, status=400)

        summary = request.data.get("summary")
        description = request.data.get("description", "")
        start_iso = request.data.get("start_iso")
        duration = request.data.get("duration", 30)
        attendee_email = request.data.get("attendee_email")
        location = request.data.get("location", "")

        if not summary:
            return Response({"error": "Event summary/title is required."}, status=400)

        try:
            res = create_calendar_event(
                client_obj=client,
                summary=summary,
                description=description,
                start_iso=start_iso,
                duration_minutes=int(duration),
                attendee_email=attendee_email,
                location=location,
            )
            return Response(res)
        except Exception as e:
            logger.error("Create Google Calendar event failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleCalendarDisconnectView(APIView):
    """Disconnect Google Calendar integration."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated."}, status=400)

        client.google_calendar_enabled = False
        client.google_calendar_config = {}
        client.save(update_fields=["google_calendar_enabled", "google_calendar_config"])

        serializer = ClientSerializer(client)
        return Response(serializer.data)
