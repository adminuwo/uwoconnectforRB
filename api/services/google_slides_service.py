import os
import time
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SLIDES_API_BASE = "https://slides.googleapis.com/v1/presentations"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"

def get_valid_slides_token(client_obj):
    """
    Retrieves a valid Google Slides OAuth access token for the given client.
    Refreshes automatically if expired.
    """
    config = client_obj.google_slides_config or {}
    access_token = config.get("access_token")
    refresh_token = config.get("refresh_token")
    expires_at = config.get("token_expires_at", 0)

    # Return access token if still valid (with 60s buffer)
    if access_token and time.time() < (expires_at - 60):
        return access_token

    if not refresh_token:
        raise ValueError("Google Slides refresh token missing. Please re-authenticate.")

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
        logger.error("Failed to refresh Google Slides token: %s", resp.text)
        raise ValueError("Failed to refresh Google Slides access token.")

    token_data = resp.json()
    new_access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    config["access_token"] = new_access_token
    config["token_expires_at"] = time.time() + expires_in
    client_obj.google_slides_config = config
    client_obj.save(update_fields=["google_slides_config"])

    return new_access_token


def create_google_presentation(client_obj, title=None, topic=None):
    """
    Creates a new Google Presentation in Google Drive with title slide.
    Returns (presentation_id, presentation_url).
    """
    token = get_valid_slides_token(client_obj)

    if not title:
        biz_name = getattr(client_obj, 'business_name', 'Client') or 'Client'
        title = f"UWOConnect Presentation ({biz_name})"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Create blank presentation
    body = {"title": title}
    resp = requests.post(SLIDES_API_BASE, json=body, headers=headers, timeout=20)
    if resp.status_code not in (200, 201):
        logger.error("Failed to create Google Presentation: %s", resp.text)
        if "SERVICE_DISABLED" in resp.text or "has not been used in project" in resp.text:
            raise ValueError("Google Slides API is disabled in your Google Cloud Console. Please enable Google Slides API.")
        raise ValueError(f"Failed to create Google Presentation: {resp.text}")

    data = resp.json()
    presentation_id = data.get("presentationId")
    presentation_url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"

    # 2. Add slide content if topic provided
    if topic:
        requests_list = [
            {
                "createSlide": {
                    "slideLayoutPath": {
                        "predefinedLayout": "SECTION_HEADER"
                    }
                }
            }
        ]
        requests.post(f"{SLIDES_API_BASE}/{presentation_id}:batchUpdate", json={"requests": requests_list}, headers=headers, timeout=15)

    # 3. Update client config with presentation metadata
    config = client_obj.google_slides_config or {}
    config["default_presentation_id"] = presentation_id
    config["default_presentation_name"] = title
    config["default_presentation_url"] = presentation_url
    config["presentations_created_count"] = config.get("presentations_created_count", 0) + 1
    config["last_sync_time"] = datetime.now(timezone.utc).isoformat()

    recent_presentations = config.get("recent_presentations", [])
    presentation_entry = {
        "presentation_id": presentation_id,
        "title": title,
        "topic": topic or "General Presentation",
        "url": presentation_url,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    recent_presentations.insert(0, presentation_entry)
    config["recent_presentations"] = recent_presentations[:10]  # keep top 10

    client_obj.google_slides_config = config
    client_obj.save(update_fields=["google_slides_config"])

    return presentation_id, presentation_url


def get_presentation_details(client_obj, presentation_id):
    """
    Fetches details and slide elements of a Google Slides presentation.
    """
    token = get_valid_slides_token(client_obj)
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(f"{SLIDES_API_BASE}/{presentation_id}", headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed fetching presentation %s: %s", presentation_id, resp.text)
        raise ValueError(f"Failed to fetch presentation: {resp.text}")

    data = resp.json()
    slides = data.get("slides", [])
    title = data.get("title", "Untitled Presentation")

    return {
        "presentation_id": presentation_id,
        "title": title,
        "slides_count": len(slides),
        "slides": slides,
        "presentation_url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
    }


def add_slide_to_presentation(client_obj, presentation_id, title=None, bullet_points=None, layout="TITLE_AND_BODY"):
    """
    Adds a new slide with optional title and content text to an existing presentation.
    """
    import uuid
    token = get_valid_slides_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    slide_id = f"slide_{uuid.uuid4().hex[:10]}"
    reqs = [
        {
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutPath": {
                    "predefinedLayout": layout
                }
            }
        }
    ]

    resp = requests.post(f"{SLIDES_API_BASE}/{presentation_id}:batchUpdate", json={"requests": reqs}, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed adding slide to presentation %s: %s", presentation_id, resp.text)
        raise ValueError(f"Failed to add slide: {resp.text}")

    return {
        "success": True,
        "slide_id": slide_id,
        "presentation_id": presentation_id,
        "message": "Slide created successfully.",
    }


def delete_google_presentation(client_obj, presentation_id):
    """
    Safely trashes a Google Slides presentation via Drive API and updates local metadata.
    """
    token = get_valid_slides_token(client_obj)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(f"{DRIVE_API_BASE}/{presentation_id}", json={"trashed": True}, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed trashing Google Presentation %s: %s", presentation_id, resp.text)
        raise ValueError(f"Failed to delete presentation: {resp.text}")

    # Remove from recent_presentations
    config = client_obj.google_slides_config or {}
    recent = config.get("recent_presentations", [])
    config["recent_presentations"] = [p for p in recent if p.get("presentation_id") != presentation_id]
    client_obj.google_slides_config = config
    client_obj.save(update_fields=["google_slides_config"])

    return {"success": True, "presentation_id": presentation_id}


def list_client_presentations(client_obj):
    """
    Returns presentations from user's Google Drive combined with local tracked presentations.
    """
    config = client_obj.google_slides_config or {}
    local_pres = config.get("recent_presentations", [])

    try:
        token = get_valid_slides_token(client_obj)
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "q": "mimeType = 'application/vnd.google-apps.presentation' and trashed = false",
            "fields": "files(id, name, modifiedTime, webViewLink, iconLink, thumbnailLink)",
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
                    "presentation_id": f_id,
                    "title": f.get("name", "Untitled Presentation"),
                    "url": f.get("webViewLink") or f"https://docs.google.com/presentation/d/{f_id}/edit",
                    "thumbnail_url": f.get("thumbnailLink"),
                    "created_at": f.get("modifiedTime"),
                    "last_modified": f.get("modifiedTime"),
                })
            for lp in local_pres:
                if lp.get("presentation_id") not in seen_ids:
                    combined.append(lp)
            return combined[:30]
    except Exception as e:
        logger.warning("Could not list Google Presentations from Drive API: %s. Using local list.", e)

    return local_pres


def ai_generate_google_presentation(client_obj, prompt, slide_count=5):
    """
    Uses OpenAI to generate a structured presentation outline with slide titles and bullet points,
    then creates a real Google Slides presentation via Google Slides API.
    """
    import json
    from .ai_service import _get_client
    ai_client = _get_client()

    sys_prompt = (
        "You are an expert presentation designer for UWO Connect. "
        "Based on the user's prompt, generate a JSON object with this exact structure:\n"
        "{\n"
        '  "title": "Presentation Main Title",\n'
        '  "subtitle": "Subtitle or business focus",\n'
        '  "slides": [\n'
        '    {"title": "Slide Title", "bullets": ["Point 1", "Point 2", "Point 3"]}\n'
        "  ]\n"
        "}\n"
        "Do not output markdown codeblocks, only pure JSON."
    )

    deck_data = None
    if ai_client:
        try:
            completion = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Create a {slide_count}-slide presentation for: {prompt}"}
                ],
                temperature=0.7,
                max_tokens=1500,
            )
            raw_text = completion.choices[0].message.content.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:].strip()
            deck_data = json.loads(raw_text)
        except Exception as e:
            logger.error("AI presentation generation JSON error: %s", e)

    if not deck_data or not isinstance(deck_data, dict):
        deck_data = {
            "title": f"Presentation: {prompt[:40]}",
            "subtitle": "Generated with UWO Connect AI",
            "slides": [
                {"title": "Overview", "bullets": ["Background & Context", "Key Goals", "Target Audience"]},
                {"title": "Key Features & Benefits", "bullets": ["Automated Workflows", "Unified Multi-Channel Inbox", "24/7 AI Assistance"]},
                {"title": "Implementation & Roadmap", "bullets": ["Phase 1: Setup & Integrations", "Phase 2: Automation Launch", "Phase 3: Scaling"]},
                {"title": "Next Steps", "bullets": ["Team Onboarding", "Performance Review", "Support Channels"]},
            ]
        }

    pres_title = deck_data.get("title") or f"Presentation - {getattr(client_obj, 'business_name', 'Client')}"
    pres_id, pres_url = create_google_presentation(client_obj, title=pres_title, topic=deck_data.get("subtitle"))

    # Add remaining slides
    slides = deck_data.get("slides", [])
    for slide_info in slides:
        try:
            s_title = slide_info.get("title", "Topic")
            bullets = slide_info.get("bullets", [])
            add_slide_to_presentation(client_obj, pres_id, title=s_title, bullet_points=bullets)
        except Exception as _e:
            logger.warning("Failed adding generated slide to %s: %s", pres_id, _e)

    return {
        "success": True,
        "presentation_id": pres_id,
        "presentation_url": pres_url,
        "title": pres_title,
        "slides_count": len(slides) + 1,
        "outline": deck_data,
    }

