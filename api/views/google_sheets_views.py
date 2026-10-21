"""
Google Sheets Integration Views
Handles OAuth2 connection, status checking, spreadsheet row appending, sync, and disconnection.
"""
import os
import secrets
import logging
import requests
from datetime import datetime, timezone

from django.core.cache import cache
from django.http import HttpResponseRedirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..services.google_sheets_service import (
    _get_credentials,
    create_default_spreadsheet,
    append_lead_row,
    read_sheet_rows,
    get_valid_sheets_token,
    list_client_spreadsheets,
    read_full_spreadsheet,
    create_custom_spreadsheet,
    delete_google_sheet,
    ai_generate_google_spreadsheet,
)
from ..serializers import ClientSerializer

from ..services.google_oauth_service import (
    SHEETS_SCOPES,
    GOOGLE_AUTH_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_USERINFO_ENDPOINT,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
    generate_google_auth_url,
)

logger = logging.getLogger(__name__)


class GoogleSheetsConnectView(APIView):
    """Initiate Google OAuth flow for Google Sheets integration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        auth_data = generate_google_auth_url("sheets", client.id, scopes=SHEETS_SCOPES, request=request)
        if "error" in auth_data:
            return Response({"error": auth_data["error"]}, status=auth_data.get("status_code", 503))

        return Response({"url": auth_data["url"], "auth_url": auth_data["url"]})


class GoogleSheetsCallbackView(APIView):
    """Callback view called by Google after user approves Sheets access."""
    permission_classes = []

    def get(self, request):
        state = request.query_params.get("state")
        code = request.query_params.get("code")
        error = request.query_params.get("error")

        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        frontend_url = state_meta.get("frontend_url") or get_frontend_return_url(request=request)

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_error={error}")

        if not code or not state:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_error=missing_code_or_state")

        client_id_val = state_meta.get("client_id") or cache.get(f"gsheets_state_{state}")
        if not client_id_val:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_error=invalid_or_expired_state")

        cache.delete(f"gsheets_state_{state}")
        cache.delete(f"google_oauth_state_{state}")

        try:
            from api.models import Client
            client_obj = Client.objects.get(id=client_id_val)
        except Exception:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_error=client_not_found")

        creds = _get_credentials()
        primary_redirect_uri = (
            state_meta.get("redirect_uri")
            or get_google_redirect_uri("sheets", request=request)
            or creds.get("redirect_uri")
        )
        candidate_uris = [
            primary_redirect_uri,
            creds.get("redirect_uri"),
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-sheets/callback/",
            "https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google-sheets/callback",
            "https://uwoconnect.aisa24.com/api/auth/gmail/callback",
            "http://localhost:8080/api/auth/gmail/callback",
        ]
        # Remove duplicates while preserving order
        candidate_uris = [u for i, u in enumerate(candidate_uris) if u and u not in candidate_uris[:i]]

        token_resp = None
        for cand_uri in candidate_uris:
            token_payload = {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "code": code,
                "redirect_uri": cand_uri,
                "grant_type": "authorization_code",
            }
            token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload, timeout=20)
            if token_resp.status_code == 200:
                logger.info("Google Sheets token exchange successful using redirect_uri: %s", cand_uri)
                break
            else:
                logger.warning("Google Sheets token exchange attempt with %s failed (%s): %s", cand_uri, token_resp.status_code, token_resp.text)

        if not token_resp or token_resp.status_code != 200:
            logger.error("Google Sheets token exchange failed: %s", token_resp.text if token_resp else "No response")
            return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_error=token_exchange_failed")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        now_ts = datetime.now(timezone.utc).timestamp()

        # Fetch user info (email & profile)
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        email = userinfo_resp.json().get("email", "") if userinfo_resp.status_code == 200 else ""

        existing_config = client_obj.google_sheets_config or {}
        client_obj.google_sheets_enabled = True
        client_obj.google_sheets_config = {
            "account_email": email,
            "access_token": access_token,
            "refresh_token": refresh_token or existing_config.get("refresh_token"),
            "token_expires_at": now_ts + expires_in,
            "auto_export_leads": True,
            "auto_export_orders": True,
            "auto_export_crm": True,
            "rows_synced": existing_config.get("rows_synced", 0),
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_time": datetime.now(timezone.utc).isoformat(),
        }
        client_obj.save()

        # Create default spreadsheet if not existing
        try:
            create_default_spreadsheet(client_obj)
        except Exception as _e:
            logger.warning("Default spreadsheet creation error: %s", _e)

        return HttpResponseRedirect(f"{frontend_url}/client/channels?google_sheets_connected=true")


class GoogleSheetsStatusView(APIView):
    """Retrieve Google Sheets connection status and recent rows preview."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client or not client.google_sheets_enabled:
            return Response({"connected": False})

        config = client.google_sheets_config or {}
        rows = []
        try:
            rows = read_sheet_rows(client, max_rows=15)
        except Exception as e:
            logger.warning("Failed reading Google Sheets preview rows: %s", e)

        return Response({
            "connected": True,
            "account_email": config.get("account_email", ""),
            "spreadsheet_id": config.get("spreadsheet_id", ""),
            "spreadsheet_name": config.get("spreadsheet_name", "UWOConnect Leads"),
            "sheet_name": config.get("sheet_name", "Leads & Messages"),
            "spreadsheet_url": config.get("spreadsheet_url", ""),
            "auto_export_leads": config.get("auto_export_leads", True),
            "auto_export_orders": config.get("auto_export_orders", True),
            "auto_export_crm": config.get("auto_export_crm", True),
            "rows_synced": config.get("rows_synced", 0),
            "last_sync_time": config.get("last_sync_time"),
            "rows": rows,
        })


class GoogleSheetsSyncView(APIView):
    """Refresh Google Sheets connection and verify spreadsheet structure."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        try:
            config = client.google_sheets_config or {}
            if not config.get("spreadsheet_id"):
                create_default_spreadsheet(client)

            rows = read_sheet_rows(client, max_rows=20)
            config = client.google_sheets_config or {}
            config["last_sync_time"] = datetime.now(timezone.utc).isoformat()
            client.google_sheets_config = config
            client.save(update_fields=["google_sheets_config"])

            return Response({
                "success": True,
                "rows_synced": config.get("rows_synced", 0),
                "rows": rows,
                "message": "Google Sheets synced successfully.",
            })
        except Exception as e:
            logger.error("Google Sheets sync error: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleSheetsAppendRowView(APIView):
    """Manually append a lead/order row to Google Sheets."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        channel = request.data.get("channel", "MANUAL")
        name = request.data.get("name", "Unknown Contact")
        contact_info = request.data.get("contact", "")
        lead_type = request.data.get("lead_type", "INQUIRY")
        content = request.data.get("content", "")
        status = request.data.get("status", "NEW")

        try:
            append_lead_row(
                client_obj=client,
                channel=channel,
                name=name,
                contact_info=contact_info,
                lead_type=lead_type,
                content=content,
                status=status,
            )
            return Response({"success": True, "message": "Row appended to Google Sheets."})
        except Exception as e:
            logger.error("Append Google Sheets row failed: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleSheetsDisconnectView(APIView):
    """Disconnect Google Sheets integration."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated."}, status=400)

        client.google_sheets_enabled = False
        client.google_sheets_config = {}
        client.save(update_fields=["google_sheets_enabled", "google_sheets_config"])

        serializer = ClientSerializer(client)
        return Response(serializer.data)


class GoogleSheetsListView(APIView):
    """Lists spreadsheets accessible to the client."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_sheets_enabled:
            return Response({"connected": False, "spreadsheets": []})

        sheets = list_client_spreadsheets(client)
        return Response({"connected": True, "spreadsheets": sheets, "total": len(sheets)})


class GoogleSheetsDetailView(APIView):
    """Reads tabs, columns, and tabular rows from a Google Spreadsheet."""
    permission_classes = [IsAuthenticated]

    def get(self, request, spreadsheet_id=None):
        client = getattr(request.user, "client", None)
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        target_id = spreadsheet_id or request.query_params.get("spreadsheet_id")
        sheet_name = request.query_params.get("sheet_name")
        max_rows = request.query_params.get("max_rows", 100)

        try:
            data = read_full_spreadsheet(
                client_obj=client,
                spreadsheet_id=target_id,
                sheet_name=sheet_name,
                max_rows=int(max_rows),
            )
            return Response(data)
        except Exception as e:
            logger.error("Failed reading spreadsheet %s: %s", target_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleSheetsCreateSpreadsheetView(APIView):
    """Creates a custom Google Spreadsheet with defined title and column headers."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        title = request.data.get("title", "").strip()
        headers = request.data.get("headers", [])
        sheet_name = request.data.get("sheet_name", "Sheet1")
        initial_rows = request.data.get("initial_rows", [])

        if not title:
            return Response({"error": "title is required."}, status=400)
        if not headers or not isinstance(headers, list):
            headers = ["Item", "Category", "Status", "Date", "Notes"]

        try:
            res = create_custom_spreadsheet(
                client_obj=client,
                title=title,
                headers_list=headers,
                initial_rows=initial_rows,
                sheet_name=sheet_name,
            )
            return Response({"success": True, "spreadsheet": res, "message": "Spreadsheet created successfully."})
        except Exception as e:
            logger.error("Failed creating spreadsheet: %s", e)
            return Response({"error": str(e)}, status=500)


class GoogleSheetsDeleteView(APIView):
    """Trashes a Google Spreadsheet."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        spreadsheet_id = request.data.get("spreadsheet_id")
        if not spreadsheet_id:
            return Response({"error": "spreadsheet_id is required."}, status=400)

        try:
            res = delete_google_sheet(client, spreadsheet_id)
            return Response(res)
        except Exception as e:
            logger.error("Failed deleting spreadsheet %s: %s", spreadsheet_id, e)
            return Response({"error": str(e)}, status=500)


class GoogleSheetsAIGenerateView(APIView):
    """AI Spreadsheet Builder: generates structure and real Google Spreadsheet."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client or not client.google_sheets_enabled:
            return Response({"error": "Google Sheets is not connected."}, status=400)

        prompt = request.data.get("prompt", "").strip()
        if not prompt:
            return Response({"error": "Prompt is required."}, status=400)

        try:
            res = ai_generate_google_spreadsheet(client, prompt=prompt)
            return Response({"success": True, "spreadsheet": res, "message": "AI Spreadsheet created successfully."})
        except Exception as e:
            logger.error("AI Spreadsheet Builder error: %s", e)
            return Response({"error": str(e)}, status=500)

