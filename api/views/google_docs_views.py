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
from ..services.google_docs_service import (
    create_google_doc,
    append_text_to_doc,
    list_client_docs,
    get_google_doc_content,
    delete_google_doc,
    ai_generate_google_doc,
)

from ..services.google_oauth_service import (
    DOCS_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
    generate_google_auth_url,
)

logger = logging.getLogger(__name__)


class GoogleDocsConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        auth_data = generate_google_auth_url("docs", client.id, scopes=DOCS_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({"auth_url": auth_data["url"], "url": auth_data["url"]})


class GoogleDocsCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        frontend_url = state_meta.get("frontend_url") or get_frontend_return_url(request=request)

        if error:
            logger.error("Google Docs OAuth error: %s", error)
            return redirect(f"{frontend_url}/client/channels?gdocs_error=access_denied")

        client_id_str = state_meta.get("client_id") or cache.get(f"gdocs_state_{state}")
        if not client_id_str:
            logger.error("Invalid or expired state token for Google Docs: %s", state)
            return redirect(f"{frontend_url}/client/channels?gdocs_error=invalid_state")

        cache.delete(f"gdocs_state_{state}")
        cache.delete(f"google_oauth_state_{state}")

        try:
            client_obj = Client.objects.get(id=client_id_str)
        except Client.DoesNotExist:
            return redirect(f"{frontend_url}/client/channels?gdocs_error=client_not_found")

        creds = get_google_credentials()
        primary_redirect_uri = state_meta.get("redirect_uri") or get_google_redirect_uri("docs", request=request)
        candidate_uris = [
            primary_redirect_uri,
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-docs/callback/",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google-docs/callback",
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
                logger.info("Google Docs token exchange successful using redirect_uri: %s", cand_uri)
                break
            else:
                logger.warning("Google Docs token exchange attempt with %s failed (%s): %s", cand_uri, token_resp.status_code, token_resp.text)

        if not token_resp or token_resp.status_code != 200:
            logger.error("Token exchange failed for Google Docs: %s", token_resp.text if token_resp else "No response")
            return redirect(f"{frontend_url}/client/channels?gdocs_error=token_exchange_failed")

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

        existing_config = client_obj.google_docs_config or {}
        new_config = {
            "account_email": email,
            "access_token": access_token,
            "refresh_token": refresh_token or existing_config.get("refresh_token"),
            "token_expires_at": time.time() + expires_in,
            "auto_generate_summaries": True,
            "auto_generate_receipts": True,
            "docs_created_count": existing_config.get("docs_created_count", 0),
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "recent_docs": existing_config.get("recent_docs", []),
        }

        client_obj.google_docs_enabled = True
        client_obj.google_docs_config = new_config
        client_obj.save(update_fields=["google_docs_enabled", "google_docs_config"])

        # Auto-create default document if not existing
        try:
            create_google_doc(client_obj)
        except Exception as _e:
            logger.warning("Default document creation warning: %s", _e)

        return redirect(f"{frontend_url}/client/channels?gdocs_connected=true")


class GoogleDocsStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        config = client.google_docs_config or {}
        docs = list_client_docs(client)

        return Response({
            "connected": client.google_docs_enabled,
            "account_email": config.get("account_email", ""),
            "default_doc_name": config.get("default_doc_name", "UWOConnect Documents"),
            "default_doc_url": config.get("default_doc_url", ""),
            "docs_created_count": config.get("docs_created_count", 0),
            "recent_docs": docs,
            "last_sync_time": config.get("last_sync_time"),
        })


class GoogleDocsSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        try:
            config = client.google_docs_config or {}
            if not config.get("default_doc_id"):
                create_google_doc(client)

            docs = list_client_docs(client)
            return Response({
                "message": "Google Docs synced successfully.",
                "docs": docs,
                "default_doc_url": config.get("default_doc_url"),
            })
        except Exception as e:
            logger.error("Google Docs sync failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleDocsCreateDocView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        title = request.data.get("title", "").strip()
        content = request.data.get("content", "").strip()

        if not title:
            return Response({"error": "Title is required."}, status=400)

        try:
            doc_id, doc_url = create_google_doc(client, title=title, content=content)
            return Response({
                "message": "Document created successfully.",
                "doc_id": doc_id,
                "doc_url": doc_url,
                "recent_docs": list_client_docs(client),
            })
        except Exception as e:
            logger.error("Failed creating document: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleDocsDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        client.google_docs_enabled = False
        client.google_docs_config = {}
        client.save(update_fields=["google_docs_enabled", "google_docs_config"])

        return Response({"message": "Google Docs disconnected successfully."})


class GoogleDocsListView(APIView):
    """List Google Docs accessible to the client."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_docs_enabled:
            return Response({"connected": False, "docs": []})

        docs = list_client_docs(client)
        return Response({"connected": True, "docs": docs, "total": len(docs)})


class GoogleDocsDetailView(APIView):
    """Read content of a Google Doc or append text."""
    permission_classes = [IsAuthenticated]

    def get(self, request, doc_id=None):
        client = getattr(request.user, "client", None)
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        target_id = doc_id or request.query_params.get("doc_id")
        if not target_id:
            return Response({"error": "doc_id is required."}, status=400)

        try:
            doc_data = get_google_doc_content(client, target_id)
            return Response(doc_data)
        except Exception as e:
            logger.error("Failed fetching doc content %s: %s", target_id, e)
            return Response({"error": str(e)}, status=500)

    def post(self, request, doc_id=None):
        client = getattr(request.user, "client", None)
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        target_id = doc_id or request.data.get("doc_id")
        text = request.data.get("text", "").strip()
        if not text:
            return Response({"error": "text is required."}, status=400)

        try:
            success = append_text_to_doc(client, doc_id=target_id, text=text)
            return Response({"success": success, "doc_id": target_id, "message": "Content appended successfully."})
        except Exception as e:
            logger.error("Failed appending to doc %s: %s", target_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleDocsDeleteView(APIView):
    """Trashes a Google Doc."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        doc_id = request.data.get("doc_id")
        if not doc_id:
            return Response({"error": "doc_id is required."}, status=400)

        try:
            res = delete_google_doc(client, doc_id)
            return Response(res)
        except Exception as e:
            logger.error("Failed deleting doc %s: %s", doc_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleDocsAIGenerateView(APIView):
    """AI Document Builder: Generates structured document and saves real Google Doc."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_docs_enabled:
            return Response({"error": "Google Docs is not connected."}, status=400)

        prompt = request.data.get("prompt", "").strip()
        doc_type = request.data.get("doc_type", "PROPOSAL")
        if not prompt:
            return Response({"error": "Prompt is required."}, status=400)

        try:
            res = ai_generate_google_doc(client, prompt=prompt, doc_type=doc_type)
            return Response(res)
        except Exception as e:
            logger.error("AI Document Builder error: %s", e)
            return Response({"error": str(e)}, status=500)

