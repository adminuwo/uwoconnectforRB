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
    get_presentation_details,
    add_slide_to_presentation,
    delete_google_presentation,
    ai_generate_google_presentation,
)

from ..services.google_oauth_service import (
    SLIDES_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
    generate_google_auth_url,
)

logger = logging.getLogger(__name__)


class GoogleSlidesConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        auth_data = generate_google_auth_url("slides", client.id, scopes=SLIDES_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({"auth_url": auth_data["url"], "url": auth_data["url"]})


class GoogleSlidesCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        frontend_url = state_meta.get("frontend_url") or get_frontend_return_url(request=request)

        if error:
            logger.error("Google Slides OAuth error: %s", error)
            return redirect(f"{frontend_url}/client/channels?gslides_error=access_denied")

        client_id_str = state_meta.get("client_id") or cache.get(f"gslides_state_{state}")
        if not client_id_str:
            logger.error("Invalid or expired state token for Google Slides: %s", state)
            return redirect(f"{frontend_url}/client/channels?gslides_error=invalid_state")

        cache.delete(f"gslides_state_{state}")
        cache.delete(f"google_oauth_state_{state}")

        try:
            client_obj = Client.objects.get(id=client_id_str)
        except Client.DoesNotExist:
            return redirect(f"{frontend_url}/client/channels?gslides_error=client_not_found")

        creds = get_google_credentials()
        primary_redirect_uri = state_meta.get("redirect_uri") or get_google_redirect_uri("slides", request=request)
        candidate_uris = [
            primary_redirect_uri,
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-slides/callback/",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google-slides/callback",
            "https://uwoconnect.aisa24.com/api/auth/gmail/callback",
            "http://localhost:8080/api/auth/gmail/callback",
        ]
        candidate_uris = [u for i, u in enumerate(candidate_uris) if u and u not in candidate_uris[:i]]

        token_resp = None
        for cand_uri in candidate_uris:
            token_payload = {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": cand_uri,
            }
            token_resp = requests.post("https://oauth2.googleapis.com/token", data=token_payload, timeout=15)
            if token_resp.status_code == 200:
                logger.info("Google Slides token exchange successful using redirect_uri: %s", cand_uri)
                break
            else:
                logger.warning("Google Slides token exchange attempt with %s failed (%s): %s", cand_uri, token_resp.status_code, token_resp.text)

        if not token_resp or token_resp.status_code != 200:
            logger.error("Token exchange failed for Google Slides: %s", token_resp.text if token_resp else "No response")
            return redirect(f"{frontend_url}/client/channels?gslides_error=token_exchange_failed")

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

        return redirect(f"{frontend_url}/client/channels?gslides_connected=true")


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


class GoogleSlidesListView(APIView):
    """List Google Slides presentations accessible to the client."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_slides_enabled:
            return Response({"connected": False, "presentations": []})

        pres = list_client_presentations(client)
        return Response({"connected": True, "presentations": pres, "total": len(pres)})


class GoogleSlidesDetailView(APIView):
    """Fetch details and slide elements of a presentation."""
    permission_classes = [IsAuthenticated]

    def get(self, request, presentation_id=None):
        client = getattr(request.user, "client", None)
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        target_id = presentation_id or request.query_params.get("presentation_id")
        if not target_id:
            return Response({"error": "presentation_id is required."}, status=400)

        try:
            data = get_presentation_details(client, target_id)
            return Response(data)
        except Exception as e:
            logger.error("Failed fetching presentation %s: %s", target_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleSlidesAddSlideView(APIView):
    """Adds a slide to a presentation."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        presentation_id = request.data.get("presentation_id")
        title = request.data.get("title")
        bullets = request.data.get("bullets", [])
        layout = request.data.get("layout", "TITLE_AND_BODY")

        if not presentation_id:
            return Response({"error": "presentation_id is required."}, status=400)

        try:
            res = add_slide_to_presentation(client, presentation_id, title=title, bullet_points=bullets, layout=layout)
            return Response(res)
        except Exception as e:
            logger.error("Failed adding slide to %s: %s", presentation_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleSlidesDeleteView(APIView):
    """Trashes a Google Slides presentation."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        presentation_id = request.data.get("presentation_id")
        if not presentation_id:
            return Response({"error": "presentation_id is required."}, status=400)

        try:
            res = delete_google_presentation(client, presentation_id)
            return Response(res)
        except Exception as e:
            logger.error("Failed deleting presentation %s: %s", presentation_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleSlidesAIGenerateView(APIView):
    """AI Presentation Builder: generates presentation outline and real Google Slides presentation."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_slides_enabled:
            return Response({"error": "Google Slides is not connected."}, status=400)

        prompt = request.data.get("prompt", "").strip()
        slide_count = request.data.get("slide_count", 5)
        if not prompt:
            return Response({"error": "Prompt is required."}, status=400)

        try:
            res = ai_generate_google_presentation(client, prompt=prompt, slide_count=int(slide_count))
            return Response(res)
        except Exception as e:
            logger.error("AI Presentation Builder error: %s", e)
            return Response({"error": str(e)}, status=500)

