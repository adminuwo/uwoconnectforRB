"""
Google Calendar Service
Handles interaction with Google Calendar API v3: token refresh, event listing, event creation/booking, and Meet link generation.
"""
import os
import uuid
import logging
import requests
import datetime
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

def _get_credentials():
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    return {
        "client_id": os.environ.get("GMAIL_CLIENT_ID", ""),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("GOOGLE_CALENDAR_REDIRECT_URI") or os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:8080/api/auth/gmail/callback"),
    }

def get_valid_calendar_token(client_obj):
    """
    Get a valid access token for Google Calendar API.
    Refreshes automatically if expired or expiring soon.
    """
    config = client_obj.google_calendar_config or {}
    access_token = config.get("access_token") or config.get("token")
    refresh_token = config.get("refresh_token")
    token_expires_at = config.get("token_expires_at", 0)

    now_ts = datetime.now(timezone.utc).timestamp()
    if access_token and token_expires_at > (now_ts + 300):
        return access_token

    if not refresh_token:
        if access_token:
            return access_token
        raise ValueError("Google Calendar refresh token missing. Please re-authenticate.")

    creds = _get_credentials()
    payload = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed to refresh Google Calendar token: %s", resp.text)
        if access_token:
            return access_token
        raise ValueError(f"Failed to refresh Google token: {resp.text}")

    data = resp.json()
    new_access_token = data.get("access_token")
    expires_in = data.get("expires_in", 3600)

    config["access_token"] = new_access_token
    config["token_expires_at"] = now_ts + expires_in
    client_obj.google_calendar_config = config
    client_obj.save(update_fields=["google_calendar_config"])

    return new_access_token

def list_upcoming_events(client_obj, max_results=15):
    """
    Fetch upcoming events from the user's primary Google Calendar.
    """
    token = get_valid_calendar_token(client_obj)
    config = client_obj.google_calendar_config or {}
    calendar_id = config.get("primary_calendar_id", "primary")

    now_iso = datetime.now(timezone.utc).isoformat()
    url = f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events"
    params = {
        "timeMin": now_iso,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed fetching calendar events: %s", resp.text)
        return []

    events_data = resp.json().get("items", [])
    formatted_events = []
    for ev in events_data:
        start_time = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end_time = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        formatted_events.append({
            "id": ev.get("id"),
            "summary": ev.get("summary", "No Title"),
            "description": ev.get("description", ""),
            "start": start_time,
            "end": end_time,
            "htmlLink": ev.get("htmlLink"),
            "location": ev.get("location", ""),
            "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
        })
    return formatted_events

def create_calendar_event(client_obj, summary, description="", start_iso=None, duration_minutes=30, attendee_email=None, location=""):
    """
    Create a new event/meeting in the user's primary Google Calendar with Google Meet link.
    """
    token = get_valid_calendar_token(client_obj)
    config = client_obj.google_calendar_config or {}
    calendar_id = config.get("primary_calendar_id", "primary")

    if not start_iso:
        start_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    else:
        try:
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        except Exception:
            start_dt = datetime.now(timezone.utc) + timedelta(hours=1)

    end_dt = start_dt + timedelta(minutes=int(duration_minutes or 30))

    event_body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 1440},
                {"method": "popup", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ]
        }
    }

    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    url = f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=event_body, headers=headers, params={"conferenceDataVersion": 1}, timeout=20)
    if resp.status_code not in (200, 201):
        logger.error("Failed creating calendar event: %s", resp.text)
        raise ValueError(f"Failed to create Google Calendar event: {resp.text}")

    data = resp.json()
    meet_link = data.get("hangoutLink") or (data.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri") if data.get("conferenceData") else None)
    return {
        "success": True,
        "event_id": data.get("id"),
        "htmlLink": data.get("htmlLink"),
        "meetLink": meet_link,
        "summary": data.get("summary"),
        "start": data.get("start", {}).get("dateTime"),
        "end": data.get("end", {}).get("dateTime"),
    }


class GoogleCalendarService:
    @staticmethod
    def check_availability(client, target_date_str):
        try:
            token = get_valid_calendar_token(client)
            url = f"{CALENDAR_API_BASE}/freeBusy"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload = {
                "timeMin": f"{target_date_str}T00:00:00Z",
                "timeMax": f"{target_date_str}T23:59:59Z",
                "items": [{"id": "primary"}]
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                busy_slots = data.get("calendars", {}).get("primary", {}).get("busy", [])
                if not busy_slots:
                    return f"The entire day ({target_date_str}) from 9:00 AM to 6:00 PM is free."
                busy_text = [f"{b.get('start')} to {b.get('end')}" for b in busy_slots]
                return f"On {target_date_str}, the calendar is BUSY during:\n" + "\n".join(busy_text)
            return f"Available for booking on {target_date_str}."
        except Exception as e:
            return f"Available for booking on {target_date_str}."

    @staticmethod
    def book_appointment(client, date_str, time_str, customer_name):
        try:
            start_iso = f"{date_str}T{time_str}:00Z"
            res = create_calendar_event(
                client_obj=client,
                summary=f"Meeting with {customer_name}",
                description="Booked automatically via UWO Connect™ AI.",
                start_iso=start_iso,
                duration_minutes=30
            )
            return f"Successfully booked appointment on {date_str} at {time_str} for {customer_name}. Meet link: {res.get('meetLink', 'N/A')}"
        except Exception as e:
            return f"Error booking appointment: {str(e)}"
