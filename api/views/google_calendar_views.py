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
    list_calendar_events_range,
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
    ai_calendar_assistant,
    get_valid_calendar_token,
)
from ..serializers import ClientSerializer

from ..services.google_oauth_service import (
    CALENDAR_SCOPES,
    GOOGLE_AUTH_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_USERINFO_ENDPOINT,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
    generate_google_auth_url,
)

logger = logging.getLogger(__name__)


class GoogleCalendarConnectView(APIView):
    """Initiate Google OAuth flow for Google Calendar integration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        auth_data = generate_google_auth_url("calendar", client.id, scopes=CALENDAR_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({"url": auth_data["url"], "auth_url": auth_data["url"]})


class GoogleCalendarCallbackView(APIView):
    """Callback view called by Google after user approves Calendar access."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        state = request.query_params.get("state")
        code = request.query_params.get("code")
        error = request.query_params.get("error")

        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        frontend_url = state_meta.get("frontend_url") or get_frontend_return_url(request=request)

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error={error}")

        if not code or not state:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=missing_code_or_state")

        client_id_val = state_meta.get("client_id") or cache.get(f"gcal_state_{state}") or cache.get(f"calendar_state_{state}")
        if not client_id_val:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=invalid_or_expired_state")

        cache.delete(f"gcal_state_{state}")
        cache.delete(f"calendar_state_{state}")
        cache.delete(f"google_oauth_state_{state}")

        try:
            from api.models import Client
            client_obj = Client.objects.get(id=client_id_val)
        except Exception:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_calendar_error=client_not_found")

        creds = _get_credentials()
        primary_redirect_uri = (
            state_meta.get("redirect_uri")
            or get_google_redirect_uri("calendar", request=request)
            or creds.get("redirect_uri")
        )
        candidate_uris = [
            primary_redirect_uri,
            creds.get("redirect_uri"),
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google-calendar/callback",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback",
            "https://uwoconnect.aisa24.com/api/auth/google-calendar/callback",
            "http://localhost:8080/api/auth/google-calendar/callback",
        ]
        # Remove duplicates while preserving order
        candidate_uris = [u for i, u in enumerate(candidate_uris) if u and u not in candidate_uris[:i]]

        token_resp = None
        for cand_uri in candidate_uris:
            token_payload = {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "code": code,
                "redirect_uri": cand_uri,
                "grant_type": "authorization_code",
            }
            token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload, timeout=20)
            if token_resp.status_code == 200:
                logger.info("Google Calendar token exchange successful using redirect_uri: %s", cand_uri)
                break
            else:
                logger.warning("Google Calendar token exchange attempt with %s failed (%s): %s", cand_uri, token_resp.status_code, token_resp.text)

        if not token_resp or token_resp.status_code != 200:
            logger.error("Google Calendar token exchange failed: %s", token_resp.text if token_resp else "No response")
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


class GoogleCalendarEventsView(APIView):
    """Retrieve Google Calendar events with date range filtering (Month, Week, Day)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_calendar_enabled:
            return Response({"connected": False, "events": []})

        start_iso = request.query_params.get("start")
        end_iso = request.query_params.get("end")
        max_results = request.query_params.get("max_results", 100)

        try:
            events = list_calendar_events_range(
                client_obj=client,
                start_iso=start_iso,
                end_iso=end_iso,
                max_results=int(max_results),
            )
            return Response({"connected": True, "events": events, "count": len(events)})
        except Exception as e:
            logger.error("Failed fetching calendar events range: %s", e)
            return Response({"error": str(e), "events": []}, status=500)


class GoogleCalendarUpdateEventView(APIView):
    """Updates/reschedules an existing Google Calendar event."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_calendar_enabled:
            return Response({"error": "Google Calendar is not connected."}, status=400)

        event_id = request.data.get("event_id")
        if not event_id:
            return Response({"error": "event_id is required."}, status=400)

        summary = request.data.get("summary")
        description = request.data.get("description")
        start_iso = request.data.get("start_iso")
        end_iso = request.data.get("end_iso")
        duration = request.data.get("duration")
        location = request.data.get("location")
        attendee_email = request.data.get("attendee_email")

        try:
            res = update_calendar_event(
                client_obj=client,
                event_id=event_id,
                summary=summary,
                description=description,
                start_iso=start_iso,
                end_iso=end_iso,
                duration_minutes=duration,
                location=location,
                attendee_email=attendee_email,
            )
            return Response(res)
        except Exception as e:
            logger.error("Failed updating calendar event %s: %s", event_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleCalendarDeleteEventView(APIView):
    """Deletes an event from Google Calendar."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_calendar_enabled:
            return Response({"error": "Google Calendar is not connected."}, status=400)

        event_id = request.data.get("event_id")
        if not event_id:
            return Response({"error": "event_id is required."}, status=400)

        try:
            res = delete_calendar_event(client, event_id)
            return Response(res)
        except Exception as e:
            logger.error("Failed deleting calendar event %s: %s", event_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleCalendarAIAssistantView(APIView):
    """Interprets natural language scheduling prompt and drafts/creates event."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_calendar_enabled:
            return Response({"error": "Google Calendar is not connected."}, status=400)

        prompt = request.data.get("prompt", "").strip()
        if not prompt:
            return Response({"error": "Prompt is required."}, status=400)

        try:
            res = ai_calendar_assistant(client, prompt)
            return Response(res)
        except Exception as e:
            logger.error("AI Calendar assistant error: %s", e)
            return Response({"error": str(e)}, status=500)

