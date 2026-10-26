"""
Google Drive Service
Handles interaction with Google Drive API v3: token retrieval, file listing, folder creation,
file upload, renaming, and trashing.
"""
import os
import time
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def get_valid_drive_token(client_obj):
    """
    Retrieves a valid Google Drive OAuth access token for the given client.
    Requires google_drive_enabled to be True and checks google_drive_config.
    Refreshes automatically if expired.
    """
    if not getattr(client_obj, "google_drive_enabled", False):
        raise ValueError("Google Drive is not connected. Please connect Google Drive.")

    config = getattr(client_obj, "google_drive_config", {}) or {}
    access_token = config.get("access_token")
    refresh_token = config.get("refresh_token")
    expires_at = config.get("token_expires_at", 0)

    # Return cached valid token
    if access_token and time.time() < (expires_at - 60):
        return access_token

    # Refresh via Drive refresh token if present
    if refresh_token:
        client_id = os.getenv("GMAIL_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload, timeout=15)
            if resp.status_code == 200:
                tdata = resp.json()
                new_token = tdata.get("access_token")
                expires_in = tdata.get("expires_in", 3600)
                config["access_token"] = new_token
                config["token_expires_at"] = time.time() + expires_in
                client_obj.google_drive_config = config
                client_obj.save(update_fields=["google_drive_config"])
                return new_token
        except Exception as e:
            logger.warning("Drive token refresh failed: %s", e)

    raise ValueError("Google Drive token is invalid or expired. Please reconnect Google Drive.")


def list_drive_files(client_obj, mime_type=None, search=None, page_size=30, page_token=None):
    """
    List files and folders in the user's Google Drive.
    Supports filtering by mimeType, search term, and pagination.
    """
    token = get_valid_drive_token(client_obj)
    headers = {"Authorization": f"Bearer {token}"}

    query_parts = ["trashed = false"]
    if mime_type:
        if mime_type == "document":
            query_parts.append("mimeType = 'application/vnd.google-apps.document'")
        elif mime_type == "spreadsheet":
            query_parts.append("mimeType = 'application/vnd.google-apps.spreadsheet'")
        elif mime_type == "presentation":
            query_parts.append("mimeType = 'application/vnd.google-apps.presentation'")
        elif mime_type == "folder":
            query_parts.append("mimeType = 'application/vnd.google-apps.folder'")
        else:
            query_parts.append(f"mimeType = '{mime_type}'")

    if search:
        safe_search = search.replace("'", "\\'")
        query_parts.append(f"name contains '{safe_search}'")

    params = {
        "q": " and ".join(query_parts),
        "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, iconLink, thumbnailLink, shared)",
        "pageSize": min(int(page_size), 100),
        "orderBy": "modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token

    resp = requests.get(DRIVE_API_BASE, headers=headers, params=params, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed fetching Drive files: %s", resp.text)
        raise ValueError(f"Google Drive API error: {resp.text}")

    data = resp.json()
    files = data.get("files", [])

    # Update drive config telemetry
    try:
        cfg = getattr(client_obj, "google_drive_config", {}) or {}
        cfg["files_count"] = len(files)
        cfg["last_sync_time"] = datetime.now(timezone.utc).isoformat()
        client_obj.google_drive_config = cfg
        client_obj.save(update_fields=["google_drive_config"])
    except Exception:
        pass

    return {
        "files": files,
        "nextPageToken": data.get("nextPageToken"),
        "total": len(files),
    }


def create_drive_folder(client_obj, name, parent_id=None):
    """
    Create a new folder in Google Drive.
    """
    token = get_valid_drive_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        body["parents"] = [parent_id]

    resp = requests.post(DRIVE_API_BASE, json=body, headers=headers, timeout=15)
    if resp.status_code not in (200, 201):
        logger.error("Failed creating Drive folder: %s", resp.text)
        raise ValueError(f"Failed to create folder: {resp.text}")

    return resp.json()


def delete_drive_file(client_obj, file_id):
    """
    Trash a file in Google Drive (safe deletion).
    """
    token = get_valid_drive_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"trashed": True}
    resp = requests.patch(f"{DRIVE_API_BASE}/{file_id}", json=body, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed trashing Drive file %s: %s", file_id, resp.text)
        raise ValueError(f"Failed to delete file: {resp.text}")

    return {"success": True, "file_id": file_id}


def rename_drive_file(client_obj, file_id, new_name):
    """
    Rename a file in Google Drive.
    """
    token = get_valid_drive_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"name": new_name}
    resp = requests.patch(f"{DRIVE_API_BASE}/{file_id}", json=body, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed renaming Drive file %s: %s", file_id, resp.text)
        raise ValueError(f"Failed to rename file: {resp.text}")

    return resp.json()


def upload_drive_file(client_obj, filename, content_bytes, mime_type="application/octet-stream", parent_id=None):
    """
    Upload a binary file to Google Drive using multipart upload.
    """
    import json
    token = get_valid_drive_token(client_obj)

    metadata = {"name": filename}
    if parent_id:
        metadata["parents"] = [parent_id]

    boundary = "-------314159265358979323846"
    delimiter = f"\r\n--{boundary}\r\n"
    close_delim = f"\r\n--{boundary}--"

    multipart_body = (
        delimiter +
        "Content-Type: application/json; charset=UTF-8\r\n\r\n" +
        json.dumps(metadata) +
        delimiter +
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + content_bytes + close_delim.encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
        "Content-Length": str(len(multipart_body)),
    }

    resp = requests.post(DRIVE_UPLOAD_BASE, data=multipart_body, headers=headers, timeout=30)
    if resp.status_code not in (200, 201):
        logger.error("Drive file upload failed: %s", resp.text)
        raise ValueError(f"Failed uploading file to Drive: {resp.text}")

    return resp.json()
