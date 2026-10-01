import os
import time
import secrets
import logging
import requests
from datetime import datetime, timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.cache import cache
from django.shortcuts import redirect

from ..models import Client
from ..services.google_slides_service import (
    create_google_presentation,
    list_client_presentations,
)

logger = logging.getLogger(__name__)

SLIDES_SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

class GoogleSlidesConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        client_id = os.getenv("GMAIL_CLIENT_ID")
        # Use whitelisted OAuth redirect URI
        redirect_uri = "http://localhost:8080/api/auth/gmail/callback"

        if not client_id:
            return Response({"error": "Google OAuth is not configured on backend."}, status=503)

        state = secrets.token_urlsafe(24)
        # Store state in cache to delegate callback
        cache.set(f"gslides_state_{state}", str(client.id), timeout=600)

        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            "response_type=code&"
            f"scope={'%20'.join(SLIDES_SCOPES)}&"
            "access_type=offline&"
            "prompt=consent&"
            f"state={state}"
        )

        return Response({"auth_url": auth_url})


class GoogleSlidesCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        if error:
            logger.error("Google Slides OAuth error: %s", error)
            return redirect("http://localhost:3000/client/channels?gslides_error=access_denied")

        client_id_str = cache.get(f"gslides_state_{state}")
        if not client_id_str:
            logger.error("Invalid or expired state token for Google Slides: %s", state)
            return redirect("http://localhost:3000/client/channels?gslides_error=invalid_state")

        cache.delete(f"gslides_state_{state}")

        try:
            client_obj = Client.objects.get(id=client_id_str)
        except Client.DoesNotExist:
            return redirect("http://localhost:3000/client/channels?gslides_error=client_not_found")

        client_id = os.getenv("GMAIL_CLIENT_ID")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET")
        redirect_uri = "http://localhost:8080/api/auth/gmail/callback"

        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        token_resp = requests.post("https://oauth2.googleapis.com/token", data=token_payload, timeout=15)
        if token_resp.status_code != 200:
            logger.error("Token exchange failed for Google Slides: %s", token_resp.text)
            return redirect("http://localhost:3000/client/channels?gslides_error=token_exchange_failed")

        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)

        # Get Google user email
        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        email = "Connected Account"
        if userinfo_resp.status_code == 200:
            email = userinfo_resp.json().get("email", email)

        existing_config = client_obj.google_slides_config or {}
        new_config = {
            "account_email": email,
            "access_token": access_token,
            "refresh_token": refresh_token or existing_config.get("refresh_token"),
            "token_expires_at": time.time() + expires_in,
            "auto_generate_pitch_decks": True,
            "auto_generate_catalog_decks": True,
            "presentations_created_count": existing_config.get("presentations_created_count", 0),
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "recent_presentations": existing_config.get("recent_presentations", []),
        }

        client_obj.google_slides_enabled = True
        client_obj.google_slides_config = new_config
        client_obj.save(update_fields=["google_slides_enabled", "google_slides_config"])

        # Auto-create default presentation if not existing
        try:
            create_google_presentation(client_obj)
        except Exception as _e:
            logger.warning("Default presentation creation warning: %s", _e)

        return redirect("http://localhost:3000/client/channels?gslides_connected=true")


class GoogleSlidesStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        config = client.google_slides_config or {}
        presentations = list_client_presentations(client)

        return Response({
            "connected": client.google_slides_enabled,
            "account_email": config.get("account_email", ""),
            "default_presentation_name": config.get("default_presentation_name", "UWOConnect Presentation"),
            "default_presentation_url": config.get("default_presentation_url", ""),
            "presentations_created_count": config.get("presentations_created_count", 0),
            "recent_presentations": presentations,
            "last_sync_time": config.get("last_sync_time"),
        })


class GoogleSlidesSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        try:
            config = client.google_slides_config or {}
            if not config.get("default_presentation_id"):
                create_google_presentation(client)

            presentations = list_client_presentations(client)
            return Response({
                "message": "Google Slides synced successfully.",
                "presentations": presentations,
                "default_presentation_url": config.get("default_presentation_url"),
            })
        except Exception as e:
            logger.error("Google Slides sync failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleSlidesCreatePresentationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        title = request.data.get("title", "").strip()
        topic = request.data.get("topic", "").strip()

        if not title:
            return Response({"error": "Title is required."}, status=400)

        try:
            presentation_id, presentation_url = create_google_presentation(client, title=title, topic=topic)
            return Response({
                "message": "Presentation created successfully.",
                "presentation_id": presentation_id,
                "presentation_url": presentation_url,
                "recent_presentations": list_client_presentations(client),
            })
        except Exception as e:
            logger.error("Failed creating presentation: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleSlidesDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        client.google_slides_enabled = False
        client.google_slides_config = {}
        client.save(update_fields=["google_slides_enabled", "google_slides_config"])

        return Response({"message": "Google Slides disconnected successfully."})
