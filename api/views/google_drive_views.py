"""
Google Drive Integration Views
Handles listing, uploading, creating folders, renaming, and deleting Google Drive files.
"""
import os
import time
import logging
import requests
from datetime import datetime, timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.core.cache import cache
from django.shortcuts import redirect

from ..models import Client
from ..services.google_oauth_service import (
    DRIVE_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
    generate_google_auth_url,
)
from ..services.google_drive_service import (
    get_valid_drive_token,
    list_drive_files,
    create_drive_folder,
    delete_drive_file,
    rename_drive_file,
    upload_drive_file,
)

logger = logging.getLogger(__name__)


class GoogleDriveConnectView(APIView):
    """Initiates Google Drive OAuth flow."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No associated client found."}, status=400)

        auth_data = generate_google_auth_url("drive", client.id, scopes=DRIVE_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({"auth_url": auth_data["url"], "url": auth_data["url"]})


class GoogleDriveCallbackView(APIView):
    """Handles Google Drive OAuth callback and stores drive credentials."""
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        frontend_url = state_meta.get("frontend_url") or get_frontend_return_url(request=request)

        if error:
            logger.error("Google Drive OAuth error: %s", error)
            return redirect(f"{frontend_url}/client/channels?gdrive_error=access_denied")

        client_id_str = state_meta.get("client_id") or cache.get(f"gdrive_state_{state}")
        if not client_id_str and state and "__" in state:
            potential_client_id = state.split("__")[0]
            if Client.objects.filter(id=potential_client_id).exists():
                client_id_str = potential_client_id

        if not client_id_str:
            logger.error("Invalid or expired state token for Google Drive: %s", state)
            return redirect(f"{frontend_url}/client/channels?gdrive_error=invalid_state")

        cache.delete(f"gdrive_state_{state}")
        cache.delete(f"google_oauth_state_{state}")

        try:
            client_obj = Client.objects.get(id=client_id_str)
        except Client.DoesNotExist:
            return redirect(f"{frontend_url}/client/channels?gdrive_error=client_not_found")

        creds = get_google_credentials()
        primary_redirect_uri = state_meta.get("redirect_uri") or get_google_redirect_uri("drive", request=request)
        candidate_uris = [
            primary_redirect_uri,
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-drive/callback/",
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
                logger.info("Google Drive token exchange successful using redirect_uri: %s", cand_uri)
                break

        if not token_resp or token_resp.status_code != 200:
            logger.error("Token exchange failed for Google Drive: %s", token_resp.text if token_resp else "No response")
            return redirect(f"{frontend_url}/client/channels?gdrive_error=token_exchange_failed")

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

        existing_config = getattr(client_obj, "google_drive_config", {}) or {}
        new_config = {
            "account_email": email,
            "access_token": access_token,
            "refresh_token": refresh_token or existing_config.get("refresh_token"),
            "token_expires_at": time.time() + expires_in,
            "connected": True,
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
            "files_count": existing_config.get("files_count", 0),
        }

        client_obj.google_drive_enabled = True
        client_obj.google_drive_config = new_config
        client_obj.save(update_fields=["google_drive_enabled", "google_drive_config"])

        return redirect(f"{frontend_url}/client/channels?gdrive_connected=true")


class GoogleDriveDisconnectView(APIView):
    """Disconnects Google Drive without affecting other Google services."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No associated client account found."}, status=400)

        client.google_drive_enabled = False
        client.google_drive_config = {}
        client.save(update_fields=["google_drive_enabled", "google_drive_config"])

        return Response({"success": True, "message": "Google Drive disconnected successfully."})


class GoogleDriveStatusView(APIView):
    """Checks Google Drive connectivity status strictly for Drive."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"connected": False, "error": "No associated client found."})

        cfg = getattr(client, "google_drive_config", {}) or {}
        connected = bool(
            getattr(client, "google_drive_enabled", False) or
            bool(cfg.get("access_token")) or
            bool(cfg.get("connected"))
        )

        account_email = cfg.get("account_email", "")
        return Response({
            "connected": connected,
            "account_email": account_email,
            "last_sync_time": cfg.get("last_sync_time"),
            "files_count": cfg.get("files_count", 0),
        })


class GoogleDriveFilesView(APIView):
    """Lists files and folders from user's Google Drive."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        mime_type = request.query_params.get("type")
        search = request.query_params.get("search")
        page_size = request.query_params.get("page_size", 30)
        page_token = request.query_params.get("page_token")

        try:
            result = list_drive_files(
                client_obj=client,
                mime_type=mime_type,
                search=search,
                page_size=page_size,
                page_token=page_token,
            )
            return Response(result)
        except ValueError as e:
            logger.warning("Google Drive client configuration/API error: %s", e)
            return Response({"error": str(e), "files": [], "connected": False}, status=400)
        except Exception as e:
            logger.warning("Failed fetching Google Drive files: %s", e)
            return Response({"error": str(e), "files": [], "connected": False}, status=400)


class GoogleDriveCreateFolderView(APIView):
    """Creates a new folder in Google Drive."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        name = request.data.get("name", "").strip()
        parent_id = request.data.get("parent_id")
        if not name:
            return Response({"error": "Folder name is required."}, status=400)

        try:
            folder = create_drive_folder(client, name=name, parent_id=parent_id)
            return Response({"success": True, "folder": folder, "message": f"Folder '{name}' created."})
        except Exception as e:
            logger.error("Create Drive folder failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleDriveUploadView(APIView):
    """Uploads a file directly to Google Drive."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"error": "No file uploaded."}, status=400)

        parent_id = request.data.get("parent_id")
        filename = uploaded_file.name
        content_type = uploaded_file.content_type or "application/octet-stream"

        try:
            file_bytes = uploaded_file.read()
            res = upload_drive_file(
                client_obj=client,
                filename=filename,
                content_bytes=file_bytes,
                mime_type=content_type,
                parent_id=parent_id,
            )
            return Response({"success": True, "file": res, "message": f"File '{filename}' uploaded successfully."})
        except Exception as e:
            logger.error("Drive upload failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleDriveDeleteView(APIView):
    """Trashes a file or folder in Google Drive."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        file_id = request.data.get("file_id")
        if not file_id:
            return Response({"error": "file_id is required."}, status=400)

        try:
            res = delete_drive_file(client, file_id)
            return Response(res)
        except Exception as e:
            logger.error("Drive delete failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleDriveRenameView(APIView):
    """Renames a file or folder in Google Drive."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        file_id = request.data.get("file_id")
        new_name = request.data.get("name", "").strip()
        if not file_id or not new_name:
            return Response({"error": "file_id and name are required."}, status=400)

        try:
            res = rename_drive_file(client, file_id, new_name)
            return Response({"success": True, "file": res, "message": "File renamed successfully."})
        except Exception as e:
            logger.error("Drive rename failed: %s", e)
            return Response({"error": str(e)}, status=500)
