import os
import django
import sys
import json
import requests
import smtplib
import pymongo

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
try:
    django.setup()
except Exception as e:
    print(f"[ERROR] Django Setup Error: {e}")
    sys.exit(1)

from django.conf import settings
from django.db import connection
from api.models import Client, User
from openai import OpenAI
import firebase_admin
from firebase_admin import auth
from azure.storage.blob import BlobServiceClient

def check_db():
    print("\n--- 1. DATABASE & MONGODB CONNECTION ---")
    try:
        connection.ensure_connection()
        print("[OK] Django DB: Connection established successfully!")
        client_count = Client.objects.count()
        user_count = User.objects.count()
        print(f"   Clients count in DB: {client_count}")
        print(f"   Users count in DB: {user_count}")
    except Exception as e:
        print(f"[ERROR] Django DB Error: {e}")

def check_openai():
    print("\n--- 2. OPENAI INTEGRATION ---")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARN] OpenAI: OPENAI_API_KEY is not set in environment.")
        return
    try:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "..."
        print(f"   API Key: {masked_key}")
        client = OpenAI(api_key=api_key)
        # Call a simple model list request to check validity
        models = client.models.list()
        print("[OK] OpenAI: Successfully connected! (API Key is valid)")
    except Exception as e:
        print(f"[ERROR] OpenAI Error: {e}")

def check_firebase():
    print("\n--- 3. FIREBASE INTEGRATION ---")
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        print("[WARN] Firebase: FIREBASE_SERVICE_ACCOUNT_JSON is not set in environment.")
        return
    try:
        sa_info = json.loads(sa_json)
        print(f"   Project ID: {sa_info.get('project_id')}")
        print(f"   Client Email: {sa_info.get('client_email')}")
        
        try:
            app = firebase_admin.get_app()
        except ValueError:
            cred = firebase_admin.credentials.Certificate(sa_info)
            app = firebase_admin.initialize_app(cred)
            
        auth.list_users(max_results=1)
        print("[OK] Firebase: Successfully authenticated and called Auth service!")
    except Exception as e:
        print(f"[ERROR] Firebase Error: {e}")

def check_azure():
    print("\n--- 4. AZURE STORAGE BLOB ---")
    account_name = os.getenv("AZURE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_ACCOUNT_KEY")
    container_name = os.getenv("AZURE_CONTAINER")
    if not account_name or not account_key or not container_name:
        print("[WARN] Azure: Configuration is incomplete in env (AZURE_ACCOUNT_NAME, AZURE_ACCOUNT_KEY, AZURE_CONTAINER).")
        return
    try:
        connect_str = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={account_key};EndpointSuffix=core.windows.net"
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_client = blob_service_client.get_container_client(container_name)
        if container_client.exists():
            print(f"[OK] Azure Storage: Connected successfully! Container '{container_name}' exists.")
        else:
            print(f"[ERROR] Azure Storage: Connected, but Container '{container_name}' does not exist.")
    except Exception as e:
        print(f"[ERROR] Azure Storage Error: {e}")

def check_smtp():
    print("\n--- 5. SMTP GMAIL CONNECTION ---")
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", 587))
    user = os.getenv("EMAIL_HOST_USER")
    password = os.getenv("EMAIL_HOST_PASSWORD")
    if not user or not password:
        print("[WARN] SMTP: Credentials not fully configured in env.")
        return
    try:
        print(f"   Connecting to {host}:{port} with user {user}...")
        server = smtplib.SMTP(host, port, timeout=10)
        server.starttls()
        server.login(user, password)
        server.quit()
        print("[OK] SMTP GMail: Login successful!")
    except Exception as e:
        print(f"[ERROR] SMTP Error: {e}")

def check_razorpay():
    print("\n--- 6. RAZORPAY API CONFIGURATION ---")
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        print("[WARN] Razorpay: Credentials not set in env.")
        return
    try:
        masked_secret = key_secret[:4] + "..." + key_secret[-2:] if len(key_secret) > 6 else "..."
        print(f"   Key ID: {key_id}")
        print(f"   Key Secret: {masked_secret}")
        url = "https://api.razorpay.com/v1/orders?count=1"
        res = requests.get(url, auth=(key_id, key_secret), timeout=10)
        if res.status_code == 200:
            print("[OK] Razorpay: Authentication successful! (API call returned 200 OK)")
        else:
            print(f"[ERROR] Razorpay: API call failed with status {res.status_code}. Response: {res.text}")
    except Exception as e:
        print(f"[ERROR] Razorpay Error: {e}")

def check_facebook_app():
    print("\n--- 7. FACEBOOK / META SYSTEM APP CONFIG ---")
    app_id = os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("FACEBOOK_APP_SECRET")
    if not app_id or not app_secret:
        print("[WARN] Facebook App: Configuration missing in env.")
        return
    try:
        print(f"   App ID: {app_id}")
        url = f"https://graph.facebook.com/oauth/access_token?client_id={app_id}&client_secret={app_secret}&grant_type=client_credentials"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("[OK] Facebook App: App ID and App Secret are valid! App Access Token obtained successfully.")
        else:
            print(f"[ERROR] Facebook App: Validation failed (status {res.status_code}): {res.text}")
    except Exception as e:
        print(f"[ERROR] Facebook App Error: {e}")

def check_microsoft_credentials():
    print("\n--- 8. MICROSOFT INTEGRATION CREDENTIALS ---")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID") or os.getenv("MICROSOFT_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET") or os.getenv("MICROSOFT_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[WARN] Microsoft/OneDrive: Client credentials missing in env.")
        return
    try:
        print(f"   Client ID: {client_id}")
        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default"
        }
        res = requests.post(url, data=data, timeout=10)
        res_json = res.json()
        error_code = res_json.get("error")
        error_desc = res_json.get("error_description", "")
        if error_code == "invalid_client":
            print(f"[ERROR] Microsoft: Invalid Client ID or Client Secret. Details: {error_desc}")
        elif error_code in ["unauthorized_client", "invalid_request", "invalid_grant"] or res.status_code == 200:
            if "invalid client secret" in error_desc.lower() or "AADSTS7000215" in error_desc:
                print(f"[ERROR] Microsoft: Invalid Client Secret! ({error_desc})")
            elif "not found in the directory" in error_desc or "AADSTS700016" in error_desc:
                print(f"[ERROR] Microsoft: Application ID not found in directory! ({error_desc})")
            else:
                print(f"[OK] Microsoft: Client credentials (ID & Secret) are VALID. (Confirmed by authority endpoint: {error_code})")
        else:
            print(f"[?] Microsoft: Status {res.status_code}, Error: {error_code} - {error_desc}")
    except Exception as e:
        print(f"[ERROR] Microsoft Error: {e}")

def check_client_integrations():
    print("\n--- 9. CLIENT INTEGRATIONS REPORT ---")
    clients = Client.objects.all()
    if not clients.exists():
        print("   No clients found in database.")
        return
    for c in clients:
        print(f"\n================ CLIENT: {c.business_name} (ID: {c.id}) ================")
        
        # WhatsApp Check
        ws_conn = getattr(c, 'whatsapp_access_token', None) and getattr(c, 'whatsapp_phone_number_id', None)
        print(f"* WhatsApp API: {'[OK] ENABLED & SET' if ws_conn else '[OFFLINE] NOT CONNECTED'}")
        if ws_conn:
            print(f"  - Phone ID: {c.whatsapp_phone_number_id}")
            print(f"  - WABA ID: {c.whatsapp_waba_id}")
            try:
                url = f"https://graph.facebook.com/v19.0/{c.whatsapp_phone_number_id}?access_token={c.whatsapp_access_token}"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    print("  - Meta Graph API status: [OK] WhatsApp token is VALID and working!")
                else:
                    print(f"  - Meta Graph API status: [ERROR] INVALID WhatsApp token (status {res.status_code}): {res.json().get('error', {}).get('message')}")
            except Exception as e:
                print(f"  - Meta Graph API check failed: {e}")
        
        # Facebook Page Check
        fb_enabled = getattr(c, 'facebook_enabled', False)
        print(f"* Facebook Page: {'[OK] ENABLED' if fb_enabled else '[OFFLINE] DISABLED'}")
        fb_config = getattr(c, 'facebook_config', {})
        if fb_config:
            print(f"  - Page Name: {fb_config.get('page_name', 'N/A')}")
            print(f"  - Page ID: {fb_config.get('page_id', 'N/A')}")
            fb_token = fb_config.get('access_token', fb_config.get('page_access_token'))
            if fb_token:
                try:
                    url = f"https://graph.facebook.com/v19.0/me?access_token={fb_token}"
                    res = requests.get(url, timeout=10)
                    if res.status_code == 200:
                        print("  - Meta Graph API status: [OK] Page access token is VALID and working!")
                    else:
                        print(f"  - Meta Graph API status: [ERROR] INVALID Page access token (status {res.status_code}): {res.json().get('error', {}).get('message')}")
                except Exception as e:
                    print(f"  - Meta Graph API check failed: {e}")
            else:
                print("  - Token status: [ERROR] MISSING Page Access Token in facebook_config")

        # Instagram Check
        ig_enabled = getattr(c, 'instagram_enabled', False)
        print(f"* Instagram Business: {'[OK] ENABLED' if ig_enabled else '[OFFLINE] DISABLED'}")
        ig_config = getattr(c, 'instagram_config', {})
        if ig_config:
            print(f"  - Business ID: {ig_config.get('instagram_business_id') or ig_config.get('instagram_business_account_id') or 'N/A'}")
            ig_token = ig_config.get('access_token')
            if ig_token:
                try:
                    url = f"https://graph.facebook.com/v19.0/me?access_token={ig_token}"
                    res = requests.get(url, timeout=10)
                    if res.status_code == 200:
                        print("  - Meta Graph API status: [OK] Instagram access token is VALID and working!")
                    else:
                        print(f"  - Meta Graph API status: [ERROR] INVALID Instagram access token (status {res.status_code}): {res.json().get('error', {}).get('message')}")
                except Exception as e:
                    print(f"  - Meta Graph API check failed: {e}")
            else:
                print("  - Token status: [ERROR] MISSING access_token in instagram_config")

        # Google Services Checks (Gmail, Calendar, Sheets, Docs, Slides, YouTube)
        google_services = [
            ("Gmail", "gmail_enabled", "gmail_config"),
            ("Google Calendar", "google_calendar_enabled", "google_calendar_config"),
            ("Google Sheets", "google_sheets_enabled", "google_sheets_config"),
            ("Google Docs", "google_docs_enabled", "google_docs_config"),
            ("Google Slides", "google_slides_enabled", "google_slides_config"),
            ("YouTube", "youtube_enabled", "youtube_config"),
        ]
        for service_name, enabled_field, config_field in google_services:
            enabled = getattr(c, enabled_field, False)
            config = getattr(c, config_field, {}) or {}
            print(f"* {service_name}: {'[OK] ENABLED' if enabled else '[OFFLINE] DISABLED'}")
            if enabled or config:
                token_val = config.get('token') or config.get('access_token')
                refresh_val = config.get('refresh_token')
                print(f"  - Token stored: {'Yes' if token_val else 'No'}")
                print(f"  - Refresh Token stored: {'Yes' if refresh_val else 'No'}")
                if refresh_val:
                    try:
                        g_client_id = os.getenv("GMAIL_CLIENT_ID")
                        g_client_secret = os.getenv("GMAIL_CLIENT_SECRET")
                        if g_client_id and g_client_secret:
                            token_url = "https://oauth2.googleapis.com/token"
                            data = {
                                "client_id": g_client_id,
                                "client_secret": g_client_secret,
                                "refresh_token": refresh_val,
                                "grant_type": "refresh_token"
                            }
                            res = requests.post(token_url, data=data, timeout=10)
                            if res.status_code == 200:
                                print(f"  - Google OAuth status: [OK] Refresh Token is VALID and working!")
                            else:
                                print(f"  - Google OAuth status: [ERROR] INVALID Refresh Token or configuration (status {res.status_code}): {res.text}")
                        else:
                            print("  - Google OAuth status: [WARN] Missing GMAIL_CLIENT_ID or GMAIL_CLIENT_SECRET to verify")
                    except Exception as e:
                        print(f"  - Google OAuth token verify failed: {e}")

        # OneDrive Check
        onedrive_enabled = getattr(c, 'onedrive_enabled', False)
        onedrive_config = getattr(c, 'onedrive_config', {}) or {}
        print(f"* OneDrive: {'[OK] ENABLED' if onedrive_enabled else '[OFFLINE] DISABLED'}")
        if onedrive_enabled or onedrive_config:
            token_val = onedrive_config.get('token') or onedrive_config.get('access_token')
            refresh_val = onedrive_config.get('refresh_token')
            print(f"  - Token stored: {'Yes' if token_val else 'No'}")
            print(f"  - Refresh Token stored: {'Yes' if refresh_val else 'No'}")
            if refresh_val:
                try:
                    ms_client_id = os.getenv("ONEDRIVE_CLIENT_ID")
                    ms_client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
                    if ms_client_id and ms_client_secret:
                        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
                        data = {
                            "client_id": ms_client_id,
                            "client_secret": ms_client_secret,
                            "refresh_token": refresh_val,
                            "grant_type": "refresh_token",
                            "scope": "files.readwrite.all offline_access"
                        }
                        res = requests.post(token_url, data=data, timeout=10)
                        if res.status_code == 200:
                            print(f"  - Microsoft OAuth status: [OK] OneDrive Refresh Token is VALID!")
                        else:
                            print(f"  - Microsoft OAuth status: [ERROR] INVALID Refresh Token or configuration (status {res.status_code}): {res.text}")
                    else:
                        print("  - Microsoft OAuth status: [WARN] Missing ONEDRIVE_CLIENT_ID or ONEDRIVE_CLIENT_SECRET to verify")
                except Exception as e:
                    print(f"  - Microsoft token verify failed: {e}")

if __name__ == "__main__":
    print("==============================================")
    print("          UWOConnect Connector Diagnostics     ")
    print("==============================================")
    check_db()
    check_openai()
    check_firebase()
    check_azure()
    check_smtp()
    check_razorpay()
    check_facebook_app()
    check_microsoft_credentials()
    check_client_integrations()
    print("\n==============================================")
    print("          Diagnostics Completed               ")
    print("==============================================")
