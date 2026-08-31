import os
import google_auth_oauthlib.flow
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.http import HttpResponseRedirect
from api.models import Client

from django.conf import settings

# Allow HTTP traffic strictly during local development debugging
if getattr(settings, 'DEBUG', False):
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_client_config():
    return {
        "web": {
            "client_id": os.environ.get("GMAIL_CLIENT_ID", ""),
            "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
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
        
        redirect_uri = os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:8080/api/auth/gmail/callback")
        flow.redirect_uri = redirect_uri
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',
            prompt='consent' # Force consent to ensure we get a refresh token
        )
        
        # Determine tenant origin dynamically
        client_origin = request.headers.get('Origin') or request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER', '')
        if client_origin and '://' in client_origin:
            parts = client_origin.split('/')
            client_origin = f"{parts[0]}//{parts[2]}"
        elif client.white_label_domain:
            client_origin = f"https://{client.white_label_domain}"
        else:
            client_origin = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

        # Save mapping from state to client info in cache for 1 hour
        cache.set(f'gmail_state_{state}', {'client_id': str(client.id), 'return_origin': client_origin}, timeout=3600)
        # Save the PKCE code_verifier
        if hasattr(flow, 'code_verifier'):
            cache.set(f'gmail_verifier_{state}', flow.code_verifier, timeout=3600)
        
        return Response({"url": authorization_url})

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
        
        # Check if state belongs to Google Calendar OAuth
        if state and cache.get(f'gcal_state_{state}'):
            from .google_calendar_views import GoogleCalendarCallbackView
            return GoogleCalendarCallbackView().get(request)

        # Check if state belongs to Google Sheets OAuth
        if state and cache.get(f'gsheets_state_{state}'):
            from .google_sheets_views import GoogleSheetsCallbackView
            return GoogleSheetsCallbackView().get(request)

        # Check if state belongs to Google Docs OAuth
        if state and cache.get(f'gdocs_state_{state}'):
            from .google_docs_views import GoogleDocsCallbackView
            return GoogleDocsCallbackView().get(request)

        # Check if state belongs to Google Slides OAuth
        if state and cache.get(f'gslides_state_{state}'):
            from .google_slides_views import GoogleSlidesCallbackView
            return GoogleSlidesCallbackView().get(request)

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error={error}")
            
        if not client_id:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error=invalid_state")
            
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error=client_not_found")
            
        client_config = get_client_config()
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            state=state
        )
        flow.redirect_uri = os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:8080/api/auth/gmail/callback")
        
        authorization_response = request.build_absolute_uri()
        # Fix http to https if behind a proxy
        if 'https' not in authorization_response and 'localhost' not in authorization_response:
             authorization_response = authorization_response.replace('http:', 'https:')
             
        # Add the code_verifier back to the flow for PKCE
        code_verifier = cache.get(f'gmail_verifier_{state}')
        if code_verifier:
            flow.code_verifier = code_verifier
             
        try:
            flow.fetch_token(authorization_response=authorization_response)
        except Exception as e:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?gmail_error={str(e)}")
            
        credentials = flow.credentials
        
        # Get user's email address using the token to store it
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email_address = profile.get('emailAddress', '')
        
        client.gmail_enabled = True
        client.gmail_config = {
            'email_address': email_address,
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
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

