"""
Google Sheets Service
Handles Google Sheets API v4 integration: token refresh, spreadsheet creation, appending lead rows, and reading recent rows.
"""
import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"

def _get_credentials():
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    return {
        "client_id": os.environ.get("GMAIL_CLIENT_ID", ""),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("GOOGLE_SHEETS_REDIRECT_URI") or os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:8080/api/auth/gmail/callback"),
    }

def get_valid_sheets_token(client_obj):
    """
    Get a valid access token for Google Sheets API.
    Refreshes automatically if expired.
    """
    config = client_obj.google_sheets_config or {}
    access_token = config.get("access_token")
    refresh_token = config.get("refresh_token")
    token_expires_at = config.get("token_expires_at", 0)

    now_ts = datetime.now(timezone.utc).timestamp()
    if access_token and token_expires_at > (now_ts + 300):
        return access_token

    if not refresh_token:
        raise ValueError("Google Sheets refresh token missing. Please re-authenticate.")

    creds = _get_credentials()
    payload = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed to refresh Google Sheets token: %s", resp.text)
        raise ValueError(f"Failed to refresh Google token: {resp.text}")

    data = resp.json()
    new_access_token = data.get("access_token")
    expires_in = data.get("expires_in", 3600)

    config["access_token"] = new_access_token
    config["token_expires_at"] = now_ts + expires_in
    client_obj.google_sheets_config = config
    client_obj.save(update_fields=["google_sheets_config"])

    return new_access_token

def create_default_spreadsheet(client_obj):
    """
    Create a new Google Spreadsheet titled 'UWOConnect Leads & Messages' with standard headers.
    """
    token = get_valid_sheets_token(client_obj)

    body = {
        "properties": {
            "title": f"UWOConnect Leads ({client_obj.business_name})",
        },
        "sheets": [
            {
                "properties": {
                    "title": "Leads & Messages",
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                },
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": [
                            {
                                "values": [
                                    {"userEnteredValue": {"stringValue": "Timestamp"}},
                                    {"userEnteredValue": {"stringValue": "Channel"}},
                                    {"userEnteredValue": {"stringValue": "Contact Name"}},
                                    {"userEnteredValue": {"stringValue": "Phone / Email"}},
                                    {"userEnteredValue": {"stringValue": "Lead Type"}},
                                    {"userEnteredValue": {"stringValue": "Message / Content"}},
                                    {"userEnteredValue": {"stringValue": "Status"}},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(SHEETS_API_BASE, json=body, headers=headers, timeout=20)
    if resp.status_code not in (200, 201):
        logger.error("Failed to create Google Spreadsheet: %s", resp.text)
        if "SERVICE_DISABLED" in resp.text or "has not been used in project" in resp.text:
            raise ValueError("Google Sheets API is disabled in your Google Cloud Console. Please enable Google Sheets API in Google Cloud Console.")
        raise ValueError(f"Failed to create Google Spreadsheet: {resp.text}")

    data = resp.json()
    spreadsheet_id = data.get("spreadsheetId")
    spreadsheet_url = data.get("spreadsheetUrl")

    config = client_obj.google_sheets_config or {}
    config["spreadsheet_id"] = spreadsheet_id
    config["spreadsheet_name"] = f"UWOConnect Leads ({client_obj.business_name})"
    config["sheet_name"] = "Leads & Messages"
    config["spreadsheet_url"] = spreadsheet_url
    client_obj.google_sheets_config = config
    client_obj.save(update_fields=["google_sheets_config"])

    return spreadsheet_id, spreadsheet_url

def append_lead_row(client_obj, channel, name, contact_info, lead_type, content, status="NEW"):
    """
    Append a single lead/message row to the connected Google Spreadsheet.
    """
    token = get_valid_sheets_token(client_obj)
    config = client_obj.google_sheets_config or {}
    spreadsheet_id = config.get("spreadsheet_id")

    if not spreadsheet_id:
        spreadsheet_id, _ = create_default_spreadsheet(client_obj)

    sheet_name = config.get("sheet_name", "Leads & Messages")
    range_name = f"'{sheet_name}'!A:G"

    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    row_values = [timestamp_str, str(channel), str(name), str(contact_info), str(lead_type), str(content), str(status)]

    url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}:append?valueInputOption=USER_ENTERED"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"values": [row_values]}

    resp = requests.post(url, json=body, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed appending row to Google Sheets: %s", resp.text)
        raise ValueError(f"Failed to append row to Google Sheets: {resp.text}")

    # Update synced row count
    config["rows_synced"] = config.get("rows_synced", 0) + 1
    config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
    client_obj.google_sheets_config = config
    client_obj.save(update_fields=["google_sheets_config"])

    return True

def read_sheet_rows(client_obj, max_rows=20):
    """
    Read the most recent rows from the connected Google Spreadsheet.
    """
    token = get_valid_sheets_token(client_obj)
    config = client_obj.google_sheets_config or {}
    spreadsheet_id = config.get("spreadsheet_id")

    if not spreadsheet_id:
        return []

    sheet_name = config.get("sheet_name", "Leads & Messages")
    range_name = f"'{sheet_name}'!A1:G100"

    url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_name}"
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.error("Failed reading rows from Google Sheets: %s", resp.text)
        return []

    values = resp.json().get("values", [])
    if len(values) <= 1:
        return []

    headers_row = values[0]
    data_rows = values[1:]
    
    formatted_rows = []
    for r in reversed(data_rows[-max_rows:]):
        formatted_rows.append({
            "timestamp": r[0] if len(r) > 0 else "",
            "channel": r[1] if len(r) > 1 else "",
            "name": r[2] if len(r) > 2 else "",
            "contact": r[3] if len(r) > 3 else "",
            "lead_type": r[4] if len(r) > 4 else "",
            "content": r[5] if len(r) > 5 else "",
            "status": r[6] if len(r) > 6 else "",
        })

    return formatted_rows


def list_client_spreadsheets(client_obj):
    """
    Returns spreadsheets from user's Google Drive and local tracked spreadsheets.
    """
    config = client_obj.google_sheets_config or {}
    local_id = config.get("spreadsheet_id")
    local_name = config.get("spreadsheet_name") or "UWOConnect Leads"
    local_url = config.get("spreadsheet_url") or (f"https://docs.google.com/spreadsheets/d/{local_id}/edit" if local_id else "")

    sheets = []
    if local_id:
        sheets.append({
            "spreadsheet_id": local_id,
            "title": local_name,
            "url": local_url,
            "created_at": config.get("connected_at"),
            "last_modified": config.get("last_sync_time"),
            "rows_count": config.get("rows_synced", 0),
            "is_default": True,
        })

    try:
        token = get_valid_sheets_token(client_obj)
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "q": "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
            "fields": "files(id, name, modifiedTime, webViewLink, iconLink)",
            "pageSize": 25,
            "orderBy": "modifiedTime desc",
        }
        resp = requests.get(DRIVE_API_BASE, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            drive_files = resp.json().get("files", [])
            seen_ids = {s["spreadsheet_id"] for s in sheets}
            for f in drive_files:
                f_id = f.get("id")
                if f_id not in seen_ids:
                    seen_ids.add(f_id)
                    sheets.append({
                        "spreadsheet_id": f_id,
                        "title": f.get("name", "Untitled Spreadsheet"),
                        "url": f.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{f_id}/edit",
                        "created_at": f.get("modifiedTime"),
                        "last_modified": f.get("modifiedTime"),
                        "is_default": False,
                    })
    except Exception as e:
        logger.warning("Could not list Google Sheets from Drive API: %s. Using default sheet.", e)

    return sheets


def read_full_spreadsheet(client_obj, spreadsheet_id=None, sheet_name=None, range_name=None, max_rows=100):
    """
    Reads the tabs, column headers, and data rows of a Google Spreadsheet.
    """
    token = get_valid_sheets_token(client_obj)
    config = client_obj.google_sheets_config or {}
    target_id = spreadsheet_id or config.get("spreadsheet_id")

    if not target_id:
        return {"headers": [], "rows": [], "sheets": [], "error": "No spreadsheet ID specified"}

    headers_auth = {"Authorization": f"Bearer {token}"}

    # 1. Fetch metadata (sheet tabs)
    meta_resp = requests.get(f"{SHEETS_API_BASE}/{target_id}?includeGridData=false", headers=headers_auth, timeout=15)
    sheets_info = []
    active_sheet_title = sheet_name or "Sheet1"
    if meta_resp.status_code == 200:
        meta_data = meta_resp.json()
        sheets_list = meta_data.get("sheets", [])
        for s in sheets_list:
            props = s.get("properties", {})
            title = props.get("title")
            if title:
                sheets_info.append(title)
        if sheets_info and not sheet_name:
            active_sheet_title = sheets_info[0]

    # 2. Fetch cell values
    grid_range = range_name or f"'{active_sheet_title}'!A1:Z{max_rows}"
    val_resp = requests.get(f"{SHEETS_API_BASE}/{target_id}/values/{grid_range}", headers=headers_auth, timeout=20)
    if val_resp.status_code != 200:
        logger.error("Failed reading values from sheet %s: %s", target_id, val_resp.text)
        return {
            "spreadsheet_id": target_id,
            "sheets": sheets_info,
            "active_sheet": active_sheet_title,
            "headers": [],
            "rows": [],
            "total_rows": 0,
        }

    values = val_resp.json().get("values", [])
    if not values:
        return {
            "spreadsheet_id": target_id,
            "sheets": sheets_info,
            "active_sheet": active_sheet_title,
            "headers": [],
            "rows": [],
            "total_rows": 0,
        }

    col_headers = values[0]
    data_rows = values[1:]

    formatted_rows = []
    for r in data_rows:
        row_obj = {}
        for idx, col in enumerate(col_headers):
            row_obj[col] = r[idx] if idx < len(r) else ""
        formatted_rows.append(row_obj)

    return {
        "spreadsheet_id": target_id,
        "sheets": sheets_info,
        "active_sheet": active_sheet_title,
        "headers": col_headers,
        "rows": formatted_rows,
        "raw_rows": data_rows,
        "total_rows": len(formatted_rows),
    }


def create_custom_spreadsheet(client_obj, title, headers_list, initial_rows=None, sheet_name="Sheet1"):
    """
    Creates a new Google Spreadsheet with custom title, column headers, and optional initial rows.
    """
    token = get_valid_sheets_token(client_obj)

    body = {
        "properties": {
            "title": title,
        },
        "sheets": [
            {
                "properties": {
                    "title": sheet_name,
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                },
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": [
                            {
                                "values": [{"userEnteredValue": {"stringValue": str(h)}} for h in headers_list]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    headers_auth = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(SHEETS_API_BASE, json=body, headers=headers_auth, timeout=20)
    if resp.status_code not in (200, 201):
        logger.error("Failed creating custom spreadsheet: %s", resp.text)
        raise ValueError(f"Failed to create spreadsheet: {resp.text}")

    data = resp.json()
    spreadsheet_id = data.get("spreadsheetId")
    spreadsheet_url = data.get("spreadsheetUrl")

    # Append initial rows if provided
    if initial_rows and isinstance(initial_rows, list):
        try:
            append_url = f"{SHEETS_API_BASE}/{spreadsheet_id}/values/'{sheet_name}'!A:Z:append?valueInputOption=USER_ENTERED"
            row_values = []
            for r in initial_rows:
                if isinstance(r, list):
                    row_values.append(r)
                elif isinstance(r, dict):
                    row_values.append([r.get(h, "") for h in headers_list])
            if row_values:
                requests.post(append_url, json={"values": row_values}, headers=headers_auth, timeout=15)
        except Exception as _e:
            logger.warning("Failed appending initial rows to %s: %s", spreadsheet_id, _e)

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": spreadsheet_url,
        "title": title,
        "headers": headers_list,
        "sheet_name": sheet_name,
    }


def delete_google_sheet(client_obj, spreadsheet_id):
    """
    Safely trashes a Google Spreadsheet via Drive API.
    """
    token = get_valid_sheets_token(client_obj)
    headers_auth = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(f"{DRIVE_API_BASE}/{spreadsheet_id}", json={"trashed": True}, headers=headers_auth, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed trashing spreadsheet %s: %s", spreadsheet_id, resp.text)
        raise ValueError(f"Failed to delete spreadsheet: {resp.text}")

    return {"success": True, "spreadsheet_id": spreadsheet_id}


def ai_generate_google_spreadsheet(client_obj, prompt):
    """
    Uses OpenAI to design a spreadsheet schema and sample data, then creates a real Google Spreadsheet.
    """
    import json
    from .ai_service import _get_client
    ai_client = _get_client()

    sys_prompt = (
        "You are an expert spreadsheet architect for UWO Connect. "
        "Based on the user's prompt, generate a JSON object with this exact structure:\n"
        "{\n"
        '  "title": "Spreadsheet Title",\n'
        '  "sheet_name": "Sheet1",\n'
        '  "headers": ["Col 1", "Col 2", "Col 3", "Col 4", "Col 5"],\n'
        '  "rows": [\n'
        '    ["Val 1A", "Val 1B", "Val 1C", "Val 1D", "Val 1E"],\n'
        '    ["Val 2A", "Val 2B", "Val 2C", "Val 2D", "Val 2E"]\n'
        "  ]\n"
        "}\n"
        "Include 5-7 meaningful column headers and 3-5 realistic data rows matching the user's business need. "
        "Do not output markdown codeblocks, only pure JSON."
    )

    sheet_schema = None
    if ai_client:
        try:
            completion = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Create a business spreadsheet for: {prompt}"}
                ],
                temperature=0.7,
                max_tokens=1500,
            )
            raw_text = completion.choices[0].message.content.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:].strip()
            sheet_schema = json.loads(raw_text)
        except Exception as e:
            logger.error("AI spreadsheet generation JSON error: %s", e)

    if not sheet_schema or not isinstance(sheet_schema, dict):
        sheet_schema = {
            "title": f"Tracker: {prompt[:35]}",
            "sheet_name": "Tracker Data",
            "headers": ["ID", "Item / Contact", "Category", "Status", "Assigned To", "Date Added", "Notes"],
            "rows": [
                ["TRK-001", "Client Lead Inflow", "Sales", "In Progress", "Sales Team", "Today", "Automated capture"],
                ["TRK-002", "Product Consultation", "Service", "Pending", "Consultant", "Tomorrow", "Meeting scheduled"],
                ["TRK-003", "Follow-up Dispatch", "Marketing", "Completed", "AI Bot", "Yesterday", "WhatsApp sent"],
            ]
        }

    title = sheet_schema.get("title") or f"Sheet - {prompt[:30]}"
    headers = sheet_schema.get("headers", ["Item", "Status", "Date"])
    rows = sheet_schema.get("rows", [])
    sheet_name = sheet_schema.get("sheet_name", "Sheet1")

    res = create_custom_spreadsheet(client_obj, title=title, headers_list=headers, initial_rows=rows, sheet_name=sheet_name)
    res["sample_rows_count"] = len(rows)
    return res

