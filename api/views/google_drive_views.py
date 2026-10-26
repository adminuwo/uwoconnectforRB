"""
Google Drive Integration Views
Handles listing, uploading, creating folders, renaming, and deleting Google Drive files.
"""
import os
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from ..services.google_drive_service import (
    get_valid_drive_token,
    list_drive_files,
    create_drive_folder,
    delete_drive_file,
    rename_drive_file,
    upload_drive_file,
)

logger = logging.getLogger(__name__)


class GoogleDriveStatusView(APIView):
    """Checks Google Drive connectivity status."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"connected": False, "error": "No associated client found."})

        # Check if any Google service with Drive scope is enabled
        connected = bool(
            getattr(client, "google_drive_enabled", False) or
            client.google_docs_enabled or
            client.google_sheets_enabled or
            client.google_slides_enabled or
            client.gmail_enabled
        )

        account_email = ""
        for cfg_name in ["google_drive_config", "google_docs_config", "google_sheets_config", "google_slides_config", "gmail_config"]:
            cfg = getattr(client, cfg_name, {}) or {}
            if cfg.get("account_email") or cfg.get("email_address"):
                account_email = cfg.get("account_email") or cfg.get("email_address")
                break

        cfg = getattr(client, "google_drive_config", {}) or {}
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
            logger.error("Failed fetching Google Drive files: %s", e)
            return Response({"error": str(e), "files": []}, status=500)


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
