import os
import requests
import google_auth_oauthlib.flow
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.http import HttpResponseRedirect
from api.models import Client

from django.conf import settings

# Unconditionally allow OAuth transport across reverse proxies (Cloud Run, local dev, etc.)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from ..services.google_oauth_service import (
    GMAIL_SCOPES,
    get_google_credentials,
    get_google_redirect_uri,
    get_frontend_return_url,
)

SCOPES = GMAIL_SCOPES

def get_client_config():
    creds = get_google_credentials()
    return {
        "web": {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

class GmailConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "User does not have an associated client."}, status=400)
            
        client_config = get_client_config()
        if not client_config['web']['client_id'] or not client_config['web']['client_secret']:
            return Response({"error": "Gmail OAuth credentials not configured on backend."}, status=500)
        
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config,
            scopes=SCOPES
        )
        
        redirect_uri = get_google_redirect_uri("gmail", request=request)
        flow.redirect_uri = redirect_uri
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',
            prompt='consent' # Force consent to ensure we get a refresh token
        )
        
        # Determine tenant origin dynamically
        client_origin = get_frontend_return_url(client=client, request=request)

        # Save mapping from state to client info in cache for 1 hour
        cache.set(f'gmail_state_{state}', {'client_id': str(client.id), 'return_origin': client_origin, 'redirect_uri': redirect_uri}, timeout=3600)
        cache.set(f'google_oauth_state_{state}', {'client_id': str(client.id), 'service': 'gmail', 'redirect_uri': redirect_uri, 'frontend_url': client_origin}, timeout=3600)
        # Save the PKCE code_verifier
        if hasattr(flow, 'code_verifier'):
            cache.set(f'gmail_verifier_{state}', flow.code_verifier, timeout=3600)
        
        return Response({"url": authorization_url, "auth_url": authorization_url})

class GmailCallbackView(APIView):
    # This endpoint is called by Google, so no auth classes
    permission_classes = []
    authentication_classes = []
    
    def get(self, request):
        state = request.GET.get('state')
        error = request.GET.get('error')
        
        state_data = cache.get(f'gmail_state_{state}')
        client_id = state_data.get('client_id') if isinstance(state_data, dict) else state_data
        frontend_url = state_data.get('return_origin') if isinstance(state_data, dict) else os.environ.get('FRONTEND_URL', 'http://localhost:3000')
        
        state_meta = cache.get(f"google_oauth_state_{state}") or {}
        service = state_meta.get("service", "").lower().replace("google_", "").strip()

        # Check if state belongs to Google Sheets OAuth
        if service == "sheets" or (state and cache.get(f'gsheets_state_{state}')):
            from .google_sheets_views import GoogleSheetsCallbackView
            return GoogleSheetsCallbackView().get(request)

        # Check if state belongs to Google Docs OAuth
        if service == "docs" or (state and cache.get(f'gdocs_state_{state}')):
            from .google_docs_views import GoogleDocsCallbackView
            return GoogleDocsCallbackView().get(request)

        # Check if state belongs to Google Slides OAuth
        if service == "slides" or (state and cache.get(f'gslides_state_{state}')):
            from .google_slides_views import GoogleSlidesCallbackView
            return GoogleSlidesCallbackView().get(request)

        # Check if state belongs to Google Calendar OAuth
        if service == "calendar" or (state and cache.get(f'gcal_state_{state}')):
            from .google_calendar_views import GoogleCalendarCallbackView
            return GoogleCalendarCallbackView().get(request)

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error={error}")
            
        if not client_id:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error=invalid_state")
            
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error=client_not_found")
            
        creds = get_google_credentials()
        redirect_uri = (
            state_data.get('redirect_uri')
            if isinstance(state_data, dict) and state_data.get('redirect_uri')
            else os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:8080/api/auth/gmail/callback")
        )
        code = request.GET.get('code')
        code_verifier = cache.get(f'gmail_verifier_{state}')

        access_token = None
        refresh_token = None
        email_address = ''

        # 1. Primary: Direct HTTPS token exchange (completely immune to oauthlib InsecureTransportError)
        try:
            token_payload = {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            if code_verifier:
                token_payload["code_verifier"] = code_verifier

            token_res = requests.post("https://oauth2.googleapis.com/token", data=token_payload, timeout=20)
            token_data = token_res.json()
            if "access_token" in token_data:
                access_token = token_data.get("access_token")
                refresh_token = token_data.get("refresh_token")
            else:
                err_msg = token_data.get("error_description") or token_data.get("error") or "Direct exchange failed"
                raise Exception(err_msg)
        except Exception as direct_err:
            # 2. Fallback: Google Auth Flow
            try:
                client_config = get_client_config()
                flow = google_auth_oauthlib.flow.Flow.from_client_config(
                    client_config,
                    scopes=SCOPES,
                    state=state
                )
                flow.redirect_uri = redirect_uri
                authorization_response = request.build_absolute_uri()
                if 'https' not in authorization_response and 'localhost' not in authorization_response:
                    authorization_response = authorization_response.replace('http:', 'https:')
                if code_verifier:
                    flow.code_verifier = code_verifier
                flow.fetch_token(authorization_response=authorization_response)
                access_token = flow.credentials.token
                refresh_token = flow.credentials.refresh_token
            except Exception as flow_err:
                return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error={str(direct_err or flow_err)}")

        # Fetch user's email address
        try:
            user_info = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15
            ).json()
            email_address = user_info.get("email", "")
        except Exception:
            pass

        if not email_address:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                g_creds = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=creds['client_id'],
                    client_secret=creds['client_secret'],
                    scopes=SCOPES
                )
                service = build('gmail', 'v1', credentials=g_creds)
                profile = service.users().getProfile(userId='me').execute()
                email_address = profile.get('emailAddress', '')
            except Exception:
                pass

        client.gmail_enabled = True
        existing_cfg = client.gmail_config or {}
        client.gmail_config = {
            'email_address': email_address,
            'token': access_token,
            'access_token': access_token,
            'refresh_token': refresh_token or existing_cfg.get('refresh_token', ''),
            'token_uri': 'https://oauth2.googleapis.com/token',
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
            'scopes': SCOPES
        }
        client.save()
        
        return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_connected=true")

class GmailSyncView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        client = request.user.client
        if not client or not client.gmail_enabled:
            return Response({"error": "Gmail is not connected."}, status=400)
            
        try:
            from api.services.gmail_service import sync_incoming_gmails
            count = sync_incoming_gmails(client)
            return Response({"success": True, "synced_count": count})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class GmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "User does not have an associated client."}, status=400)
            
        client.gmail_enabled = False
        client.gmail_config = {}
        client.save()
        
        return Response({"success": True, "message": "Gmail disconnected successfully."})

