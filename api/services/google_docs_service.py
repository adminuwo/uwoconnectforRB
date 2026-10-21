import os
import time
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"

def get_valid_docs_token(client_obj):
    """
    Retrieves a valid Google Docs OAuth access token for the given client.
    Refreshes automatically if expired.
    """
    config = client_obj.google_docs_config or {}
    access_token = config.get("access_token")
    refresh_token = config.get("refresh_token")
    expires_at = config.get("token_expires_at", 0)

    # Return access token if still valid (with 60s buffer)
    if access_token and time.time() < (expires_at - 60):
        return access_token

    if not refresh_token:
        raise ValueError("Google Docs refresh token missing. Please re-authenticate.")

    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    resp = requests.post(TOKEN_URL, data=payload, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed to refresh Google Docs token: %s", resp.text)
        raise ValueError("Failed to refresh Google Docs access token.")

    token_data = resp.json()
    new_access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    config["access_token"] = new_access_token
    config["token_expires_at"] = time.time() + expires_in
    client_obj.google_docs_config = config
    client_obj.save(update_fields=["google_docs_config"])

    return new_access_token


def create_google_doc(client_obj, title=None, content=None):
    """
    Creates a new Google Document in Google Drive with initial text content.
    Returns (doc_id, doc_url).
    """
    token = get_valid_docs_token(client_obj)

    if not title:
        biz_name = getattr(client_obj, 'business_name', 'Client') or 'Client'
        title = f"UWOConnect Document ({biz_name})"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Create blank document
    body = {"title": title}
    resp = requests.post(DOCS_API_BASE, json=body, headers=headers, timeout=20)
    if resp.status_code not in (200, 201):
        logger.error("Failed to create Google Document: %s", resp.text)
        if "SERVICE_DISABLED" in resp.text or "has not been used in project" in resp.text:
            raise ValueError("Google Docs API is disabled in your Google Cloud Console. Please enable Google Docs API.")
        raise ValueError(f"Failed to create Google Document: {resp.text}")

    data = resp.json()
    doc_id = data.get("documentId")
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    # 2. Insert initial content if provided
    if content:
        insert_req = {
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": content + "\n\n"
                    }
                }
            ]
        }
        requests.post(f"{DOCS_API_BASE}/{doc_id}:batchUpdate", json=insert_req, headers=headers, timeout=15)

    # 3. Update client config with document metadata
    config = client_obj.google_docs_config or {}
    config["default_doc_id"] = doc_id
    config["default_doc_name"] = title
    config["default_doc_url"] = doc_url
    config["docs_created_count"] = config.get("docs_created_count", 0) + 1
    config["last_sync_time"] = datetime.now(timezone.utc).isoformat()

    recent_docs = config.get("recent_docs", [])
    doc_entry = {
        "doc_id": doc_id,
        "title": title,
        "url": doc_url,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    recent_docs.insert(0, doc_entry)
    config["recent_docs"] = recent_docs[:10]  # keep top 10

    client_obj.google_docs_config = config
    client_obj.save(update_fields=["google_docs_config"])

    return doc_id, doc_url


def append_text_to_doc(client_obj, doc_id=None, text=""):
    """
    Appends text content to an existing Google Document.
    """
    token = get_valid_docs_token(client_obj)
    config = client_obj.google_docs_config or {}

    if not doc_id:
        doc_id = config.get("default_doc_id")
        if not doc_id:
            doc_id, _ = create_google_doc(client_obj)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Fetch document structure to find end index
    resp = requests.get(f"{DOCS_API_BASE}/{doc_id}", headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed to read Google Document %s: %s", doc_id, resp.text)
        raise ValueError("Failed to read Google Document.")

    doc_data = resp.json()
    content_list = doc_data.get("body", {}).get("content", [])
    end_index = 1
    if content_list:
        end_index = content_list[-1].get("endIndex", 1) - 1
        if end_index < 1:
            end_index = 1

    timestamp_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    formatted_text = f"\n--- [{timestamp_str}] ---\n{text}\n"

    batch_req = {
        "requests": [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": formatted_text
                }
            }
        ]
    }

    append_resp = requests.post(f"{DOCS_API_BASE}/{doc_id}:batchUpdate", json=batch_req, headers=headers, timeout=15)
    if append_resp.status_code != 200:
        logger.error("Failed appending text to Google Document %s: %s", doc_id, append_resp.text)
        return False

    config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
    client_obj.google_docs_config = config
    client_obj.save(update_fields=["google_docs_config"])

    return True


def get_google_doc_content(client_obj, doc_id):
    """
    Fetches the full text content and metadata of a Google Document.
    """
    token = get_valid_docs_token(client_obj)
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(f"{DOCS_API_BASE}/{doc_id}", headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed fetching Google Doc %s: %s", doc_id, resp.text)
        raise ValueError(f"Failed to fetch document: {resp.text}")

    data = resp.json()
    title = data.get("title", "Untitled Document")

    # Extract clean text from document body
    body_content = data.get("body", {}).get("content", [])
    extracted_text = []
    for elem in body_content:
        paragraph = elem.get("paragraph")
        if paragraph:
            for p_elem in paragraph.get("elements", []):
                text_run = p_elem.get("textRun")
                if text_run and text_run.get("content"):
                    extracted_text.append(text_run.get("content"))

    full_text = "".join(extracted_text)
    return {
        "doc_id": doc_id,
        "title": title,
        "content": full_text,
        "doc_url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def delete_google_doc(client_obj, doc_id):
    """
    Safely trashes a Google Document via Drive API and updates local metadata.
    """
    token = get_valid_docs_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(f"{DRIVE_API_BASE}/{doc_id}", json={"trashed": True}, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed trashing Google Doc %s: %s", doc_id, resp.text)
        raise ValueError(f"Failed to delete document: {resp.text}")

    # Remove from recent_docs
    config = client_obj.google_docs_config or {}
    recent = config.get("recent_docs", [])
    config["recent_docs"] = [d for d in recent if d.get("doc_id") != doc_id]
    client_obj.google_docs_config = config
    client_obj.save(update_fields=["google_docs_config"])

    return {"success": True, "doc_id": doc_id}


def list_client_docs(client_obj):
    """
    Returns documents from user's Google Drive combined with local tracked docs.
    """
    config = client_obj.google_docs_config or {}
    local_docs = config.get("recent_docs", [])

    try:
        token = get_valid_docs_token(client_obj)
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "q": "mimeType = 'application/vnd.google-apps.document' and trashed = false",
            "fields": "files(id, name, modifiedTime, webViewLink, iconLink)",
            "pageSize": 25,
            "orderBy": "modifiedTime desc",
        }
        resp = requests.get(DRIVE_API_BASE, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            drive_files = resp.json().get("files", [])
            seen_ids = set()
            combined = []
            for f in drive_files:
                f_id = f.get("id")
                seen_ids.add(f_id)
                combined.append({
                    "doc_id": f_id,
                    "title": f.get("name", "Untitled Document"),
                    "url": f.get("webViewLink") or f"https://docs.google.com/document/d/{f_id}/edit",
                    "created_at": f.get("modifiedTime"),
                    "last_modified": f.get("modifiedTime"),
                })
            for ld in local_docs:
                if ld.get("doc_id") not in seen_ids:
                    combined.append(ld)
            return combined[:30]
    except Exception as e:
        logger.warning("Could not list Google Docs from Drive API: %s. Using local list.", e)

    return local_docs


def ai_generate_google_doc(client_obj, prompt, doc_type="PROPOSAL"):
    """
    Uses OpenAI to draft structured document content, then saves it as a real Google Document.
    """
    from .ai_service import _get_client
    ai_client = _get_client()

    sys_prompt = (
        "You are an expert executive document writer for UWO Connect. "
        "Generate a well-structured, professional business document based on the user's prompt. "
        "Include a clear Document Title on the first line prefixed with 'TITLE: ', "
        "followed by an Executive Summary, Objectives, Detailed Proposal/Plan, Deliverables, Timeline, and Conclusion. "
        "Use clean text formatting without Markdown symbols like hashtags."
    )

    if ai_client:
        try:
            completion = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Document Type: {doc_type}\nPrompt: {prompt}"}
                ],
                temperature=0.7,
                max_tokens=1500,
            )
            raw_output = completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error("AI Document Generation error: %s", e)
            raw_output = f"TITLE: {doc_type.title()} Document\n\nExecutive Summary\n{prompt}\n\nGenerated via UWO Connect AI."
    else:
        raw_output = f"TITLE: {doc_type.title()} - {prompt[:40]}\n\nExecutive Summary\n{prompt}\n\nGenerated via UWO Connect."

    # Parse title
    title = f"{doc_type.title()} - {getattr(client_obj, 'business_name', 'Business')}"
    body_text = raw_output
    if raw_output.startswith("TITLE:"):
        lines = raw_output.split("\n", 1)
        title = lines[0].replace("TITLE:", "").strip()
        body_text = lines[1].strip() if len(lines) > 1 else raw_output

    doc_id, doc_url = create_google_doc(client_obj, title=title, content=body_text)
    return {
        "success": True,
        "doc_id": doc_id,
        "doc_url": doc_url,
        "title": title,
        "preview_text": body_text[:400] + ("..." if len(body_text) > 400 else ""),
    }

