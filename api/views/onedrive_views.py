"""
OneDrive Integration Views
- OAuth 2.0 flow with Microsoft Identity Platform
- Drive status & sync stats
- Manual sync trigger
- Disconnect
"""
import os
import json
import hashlib
import logging
from datetime import datetime, timezone

import requests
from django.core.cache import cache
from django.http import HttpResponseRedirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..models import Client

logger = logging.getLogger(__name__)

# ── Microsoft Graph constants ──────────────────────────────────────
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common"
TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
AUTH_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/authorize"

SCOPES = "Files.ReadWrite.All User.Read offline_access"

# ── Folder structure for auto-creation ─────────────────────────────
ONEDRIVE_FOLDER_TREE = {
    "UWOConnect": {
        "WhatsApp": ["Images", "Documents", "Audio", "Video"],
        "Facebook": ["Images", "Documents", "Attachments"],
        "Instagram": ["Images", "Documents"],
        "Telegram": [],
        "Gmail": [],
        "Outlook": [],
        "Teams": [],
        "Slack": [],
        "Discord": [],
        "Website Chat": [],
        "AI Chat": [],
        "CRM": [],
        "Orders": [],
        "Invoices": [],
        "Knowledge Base": [],
        "Team": ["Employee Documents", "Shared Files", "Reports"],
        "Workflow Files": [],
        "Backups": [],
    }
}

# ── File-type → sub-folder mapping ─────────────────────────────────
FILE_TYPE_FOLDER_MAP = {
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".webp": "Images", ".svg": "Images", ".ico": "Images",
    # Documents
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".txt": "Documents", ".rtf": "Documents", ".odt": "Documents",
    # Spreadsheets
    ".xls": "Documents", ".xlsx": "Documents", ".csv": "Documents", ".ods": "Documents",
    # Presentations
    ".ppt": "Documents", ".pptx": "Documents", ".odp": "Documents",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".ogg": "Audio", ".m4a": "Audio",
    ".flac": "Audio", ".aac": "Audio",
    # Video
    ".mp4": "Video", ".avi": "Video", ".mov": "Video", ".mkv": "Video",
    ".wmv": "Video", ".webm": "Video",
    # Archives
    ".zip": "Documents", ".rar": "Documents", ".7z": "Documents",
    ".tar": "Documents", ".gz": "Documents",
}

CONNECTOR_FOLDER_MAP = {
    "WHATSAPP": "WhatsApp",
    "FACEBOOK": "Facebook",
    "INSTAGRAM": "Instagram",
    "GMAIL": "Gmail",
    "TELEGRAM": "Telegram",
    "OUTLOOK": "Outlook",
    "TEAMS": "Teams",
    "SLACK": "Slack",
    "DISCORD": "Discord",
    "WEBSITE_CHAT": "Website Chat",
    "AI_CHAT": "AI Chat",
    "CRM": "CRM",
    "ORDERS": "Orders",
    "INVOICES": "Invoices",
    "KNOWLEDGE_BASE": "Knowledge Base",
    "TEAM": "Team",
    "WORKFLOW": "Workflow Files",
    "BACKUPS": "Backups",
}


def _get_onedrive_credentials():
    """Return client_id, client_secret, redirect_uri from env."""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    return {
        "client_id": os.environ.get("ONEDRIVE_CLIENT_ID", ""),
        "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get(
            "ONEDRIVE_REDIRECT_URI",
            "http://localhost:8080/api/onedrive/callback",
        ),
    }


def _refresh_access_token(client_obj):
    """
    Refresh the Microsoft access token using the stored refresh token.
    Updates the client record in-place and returns the new access_token.
    """
    config = client_obj.onedrive_config or {}
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh token stored – user must re-authenticate.")

    creds = _get_onedrive_credentials()
    payload = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPES,
    }
    resp = requests.post(TOKEN_ENDPOINT, data=payload, timeout=30)
    if resp.status_code != 200:
        logger.error("Token refresh failed: %s", resp.text)
        raise ValueError("Token refresh failed. User may need to re-authenticate.")

    data = resp.json()
    config["access_token"] = data["access_token"]
    if "refresh_token" in data:
        config["refresh_token"] = data["refresh_token"]
    config["token_expires_at"] = (
        datetime.now(timezone.utc).timestamp() + data.get("expires_in", 3600)
    )
    client_obj.onedrive_config = config
    client_obj.save(update_fields=["onedrive_config"])
    return data["access_token"]


def _get_valid_token(client_obj):
    """Return a valid access token, refreshing if needed."""
    config = client_obj.onedrive_config or {}
    expires_at = config.get("token_expires_at", 0)
    if datetime.now(timezone.utc).timestamp() >= expires_at - 120:
        return _refresh_access_token(client_obj)
    return config.get("access_token", "")


def _graph_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _ensure_folder(token, parent_path, folder_name):
    """Create folder via Graph API if it doesn't exist. Returns driveItem id."""
    url = f"{GRAPH_API_BASE}/me/drive/root:/{parent_path}/{folder_name}"
    resp = requests.get(url, headers=_graph_headers(token), timeout=15)
    if resp.status_code == 200:
        return resp.json().get("id")

    # Create the folder
    parent_url = f"{GRAPH_API_BASE}/me/drive/root:/{parent_path}:/children"
    body = {
        "name": folder_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "fail",
    }
    resp = requests.post(parent_url, headers=_graph_headers(token), json=body, timeout=15)
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    # Might already exist (race condition)
    if resp.status_code == 409:
        resp2 = requests.get(url, headers=_graph_headers(token), timeout=15)
        return resp2.json().get("id") if resp2.status_code == 200 else None
    logger.warning("Folder creation failed %s/%s: %s", parent_path, folder_name, resp.text)
    return None


def _create_folder_tree(token):
    """Ensure the full UWOConnect folder hierarchy exists in OneDrive."""
    for root, children in ONEDRIVE_FOLDER_TREE.items():
        _ensure_folder(token, "", root)
        for sub, leaves in children.items():
            _ensure_folder(token, root, sub)
            for leaf in leaves:
                _ensure_folder(token, f"{root}/{sub}", leaf)


def get_target_folder(connector, file_extension):
    """Determine the target OneDrive folder path for a file."""
    connector_folder = CONNECTOR_FOLDER_MAP.get(connector.upper(), connector)
    sub_folder = FILE_TYPE_FOLDER_MAP.get(file_extension.lower(), "Documents")
    return f"UWOConnect/{connector_folder}/{sub_folder}"


def upload_file_to_onedrive(client_obj, file_bytes, file_name, connector, employee_name=None):
    """
    Upload a file to OneDrive in the correct folder.
    For team files, specify employee_name to route to Team/<Name>/.
    Returns dict with upload result or raises.
    """
    token = _get_valid_token(client_obj)
    ext = os.path.splitext(file_name)[1]

    if employee_name:
        target_path = f"UWOConnect/Team/{employee_name}"
        _ensure_folder(token, "UWOConnect/Team", employee_name)
    else:
        target_path = get_target_folder(connector, ext)
        # Ensure the target folder exists
        parts = target_path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            _ensure_folder(token, parent, parts[i])

    # Duplicate detection via content hash
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]

    # Upload (simple upload for files < 4 MB, otherwise use upload session)
    if len(file_bytes) < 4 * 1024 * 1024:
        upload_url = f"{GRAPH_API_BASE}/me/drive/root:/{target_path}/{file_name}:/content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        }
        resp = requests.put(upload_url, headers=headers, data=file_bytes, timeout=60)
    else:
        # Create upload session for larger files
        session_url = f"{GRAPH_API_BASE}/me/drive/root:/{target_path}/{file_name}:/createUploadSession"
        session_resp = requests.post(
            session_url,
            headers=_graph_headers(token),
            json={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
            timeout=30,
        )
        if session_resp.status_code not in (200, 201):
            raise ValueError(f"Upload session creation failed: {session_resp.text}")

        upload_url = session_resp.json()["uploadUrl"]
        chunk_size = 10 * 1024 * 1024  # 10 MB chunks
        total = len(file_bytes)
        for start in range(0, total, chunk_size):
            end = min(start + chunk_size, total)
            chunk = file_bytes[start:end]
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end - 1}/{total}",
            }
            resp = requests.put(upload_url, headers=headers, data=chunk, timeout=120)

    if resp.status_code in (200, 201):
        result = resp.json()
        # Update last sync time
        config = client_obj.onedrive_config or {}
        config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
        client_obj.onedrive_config = config
        client_obj.save(update_fields=["onedrive_config"])
        return {
            "success": True,
            "file_id": result.get("id"),
            "file_name": file_name,
            "web_url": result.get("webUrl"),
            "target_path": target_path,
        }
    else:
        raise ValueError(f"Upload failed ({resp.status_code}): {resp.text}")


# ══════════════════════════════════════════════════════════════════
# REST API Views
# ══════════════════════════════════════════════════════════════════

class OneDriveConnectView(APIView):
    """Initiate Microsoft OAuth2 flow for OneDrive access."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        creds = _get_onedrive_credentials()
        if not creds["client_id"] or not creds["client_secret"]:
            return Response(
                {"error": "OneDrive OAuth credentials not configured on backend."},
                status=503,
            )

        # Generate state parameter
        import secrets
        state = secrets.token_urlsafe(32)
        cache.set(f"onedrive_state_{state}", client.id, timeout=3600)

        auth_url = (
            f"{AUTH_ENDPOINT}"
            f"?client_id={creds['client_id']}"
            f"&response_type=code"
            f"&redirect_uri={creds['redirect_uri']}"
            f"&response_mode=query"
            f"&scope={SCOPES}"
            f"&state={state}"
            f"&prompt=select_account"
        )
        return Response({"url": auth_url})


class OneDriveCallbackView(APIView):
    """Handle OAuth2 callback from Microsoft."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        state = request.GET.get("state")
        code = request.GET.get("code")
        error = request.GET.get("error")

        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

        if error:
            return HttpResponseRedirect(
                f"{frontend_url}/client/channels?onedrive_error={error}"
            )

        client_id_cached = cache.get(f"onedrive_state_{state}")
        if not client_id_cached:
            return HttpResponseRedirect(
                f"{frontend_url}/client/channels?onedrive_error=invalid_state"
            )

        try:
            client_obj = Client.objects.get(id=client_id_cached)
        except Client.DoesNotExist:
            return HttpResponseRedirect(
                f"{frontend_url}/client/channels?onedrive_error=client_not_found"
            )

        # Exchange code for tokens
        creds = _get_onedrive_credentials()
        token_payload = {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "code": code,
            "redirect_uri": creds["redirect_uri"],
            "grant_type": "authorization_code",
            "scope": SCOPES,
        }
        token_resp = requests.post(TOKEN_ENDPOINT, data=token_payload, timeout=30)
        if token_resp.status_code != 200:
            logger.error("OneDrive token exchange failed: %s", token_resp.text)
            err_msg = "token_exchange_failed"
            try:
                err_msg = token_resp.json().get("error_description", token_resp.text[:100])
            except Exception:
                pass
            import urllib.parse
            encoded_err = urllib.parse.quote(str(err_msg))
            return HttpResponseRedirect(
                f"{frontend_url}/client/channels?onedrive_error={encoded_err}"
            )

        token_data = token_resp.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")

        # Fetch user profile
        user_resp = requests.get(
            f"{GRAPH_API_BASE}/me",
            headers=_graph_headers(access_token),
            timeout=15,
        )
        user_info = user_resp.json() if user_resp.status_code == 200 else {}

        # Fetch drive info
        drive_resp = requests.get(
            f"{GRAPH_API_BASE}/me/drive",
            headers=_graph_headers(access_token),
            timeout=15,
        )
        drive_info = drive_resp.json() if drive_resp.status_code == 200 else {}

        # Store config
        client_obj.onedrive_enabled = True
        client_obj.onedrive_config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": (
                datetime.now(timezone.utc).timestamp()
                + token_data.get("expires_in", 3600)
            ),
            "account_name": user_info.get("displayName", ""),
            "account_email": user_info.get("mail") or user_info.get("userPrincipalName", ""),
            "drive_id": drive_info.get("id", ""),
            "drive_name": drive_info.get("name", "OneDrive"),
            "drive_type": drive_info.get("driveType", ""),
            "storage_total": drive_info.get("quota", {}).get("total", 0),
            "storage_used": drive_info.get("quota", {}).get("used", 0),
            "web_url": drive_info.get("webUrl", ""),
            "last_sync_time": None,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        client_obj.save()

        # Create folder structure in background (best-effort)
        try:
            _create_folder_tree(access_token)
        except Exception as e:
            logger.warning("Folder tree creation failed: %s", e)

        # Clean up state
        cache.delete(f"onedrive_state_{state}")

        return HttpResponseRedirect(
            f"{frontend_url}/client/channels?onedrive_connected=true"
        )


class OneDriveStatusView(APIView):
    """Return OneDrive connection status, drive info, and sync stats."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client or not client.onedrive_enabled:
            return Response({"connected": False})

        config = client.onedrive_config or {}

        # Optionally refresh drive info from Graph
        try:
            token = _get_valid_token(client)
            drive_resp = requests.get(
                f"{GRAPH_API_BASE}/me/drive",
                headers=_graph_headers(token),
                timeout=15,
            )
            if drive_resp.status_code == 200:
                drive_data = drive_resp.json()
                config["storage_total"] = drive_data.get("quota", {}).get("total", 0)
                config["storage_used"] = drive_data.get("quota", {}).get("used", 0)
                config["drive_name"] = drive_data.get("name", config.get("drive_name", ""))
                config["web_url"] = drive_data.get("webUrl", config.get("web_url", ""))
                client.onedrive_config = config
                client.save(update_fields=["onedrive_config"])
        except Exception as e:
            logger.warning("OneDrive status refresh failed: %s", e)

        return Response({
            "connected": True,
            "drive_info": {
                "account_name": config.get("account_name", ""),
                "account_email": config.get("account_email", ""),
                "drive_id": config.get("drive_id", ""),
                "drive_name": config.get("drive_name", ""),
                "storage_total": config.get("storage_total", 0),
                "storage_used": config.get("storage_used", 0),
                "web_url": config.get("web_url", ""),
            },
            "sync_stats": {
                "last_sync_time": config.get("last_sync_time"),
                "synced_count": config.get("synced_count", 0),
                "pending_count": config.get("pending_count", 0),
                "failed_count": config.get("failed_count", 0),
                "queue_items": config.get("queue_items", []),
            },
        })


class OneDriveSyncView(APIView):
    """Trigger a manual sync (re-create folder structure, sync all existing media files & update stats)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.onedrive_enabled:
            return Response({"error": "OneDrive is not connected."}, status=400)

        try:
            token = _get_valid_token(client)
            _create_folder_tree(token)

            # Sync all existing media messages in background
            from ..models import Message
            from ..services.onedrive_sync_service import sync_whatsapp_media_to_onedrive, sync_fb_ig_media_to_onedrive
            
            media_msgs = Message.objects.filter(client=client)
            for m in media_msgs:
                meta = m.metadata or {}
                m_type = meta.get('type')
                if m.channel == 'WHATSAPP' and m_type in ('document', 'image', 'audio', 'video'):
                    sync_whatsapp_media_to_onedrive(client, meta)
                elif m.channel in ('FACEBOOK', 'INSTAGRAM') and meta.get('message', {}).get('attachments'):
                    sync_fb_ig_media_to_onedrive(client, meta.get('message', {}), platform=m.channel)

            config = client.onedrive_config or {}
            config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
            client.onedrive_config = config
            client.save(update_fields=["onedrive_config"])

            return Response({"success": True, "message": "Sync completed. Existing files are syncing to OneDrive."})
        except Exception as e:
            logger.error("OneDrive sync failed: %s", e)
            return Response({"error": str(e)}, status=500)


class OneDriveDisconnectView(APIView):
    """Disconnect OneDrive integration."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated."}, status=400)

        client.onedrive_enabled = False
        client.onedrive_config = {}
        client.save(update_fields=["onedrive_enabled", "onedrive_config"])

        # Return updated client data
        from ..serializers import ClientSerializer
        serializer = ClientSerializer(client)
        return Response(serializer.data)
