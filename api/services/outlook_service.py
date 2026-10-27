import requests
import os
import logging
from datetime import datetime, timezone
from api.models import EmailMessage, EmailAccount

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common"
TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
SCOPES = "Mail.Read Mail.Send Mail.ReadWrite Calendars.ReadWrite Chat.ReadWrite OnlineMeetings.ReadWrite Contacts.ReadWrite Files.ReadWrite User.Read offline_access"

def refresh_outlook_token(client):
    config = client.outlook_config or {}
    refresh_token = config.get('refresh_token')
    if not refresh_token:
        return None

    client_id = os.environ.get('MICROSOFT_CLIENT_ID', '')
    client_secret = os.environ.get('MICROSOFT_CLIENT_SECRET', '')
    
    try:
        ref_res = requests.post(TOKEN_ENDPOINT, data={
            'client_id': client_id,
            'scope': SCOPES,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'client_secret': client_secret,
        }, timeout=10)
        
        if ref_res.status_code == 200:
            new_tokens = ref_res.json()
            new_access_token = new_tokens.get('access_token')
            if new_access_token:
                config['access_token'] = new_access_token
                # if refresh_token is rotated, update it too
                if new_tokens.get('refresh_token'):
                    config['refresh_token'] = new_tokens.get('refresh_token')
                client.outlook_config = config
                client.save()
                return new_access_token
    except Exception as e:
        logger.error(f"Failed to refresh Outlook token: {e}")
    return None

def sync_outlook_emails(client):
    """
    Fetches recent emails from Outlook via Microsoft Graph API
    and saves them to the EmailMessage model.
    """
    if not client.outlook_enabled or not client.outlook_config:
        return 0

    config = client.outlook_config
    access_token = config.get('access_token')
    
    if not access_token or access_token.startswith('simulated_'):
        return 0
        
    def _fetch_emails(token):
        url = f"{GRAPH_API_BASE}/me/messages?$top=30&$select=id,subject,bodyPreview,body,sender,toRecipients,receivedDateTime,isRead,hasAttachments"
        res = requests.get(
            url,
            headers={'Authorization': f"Bearer {token}"},
            timeout=15
        )
        return res

    res = _fetch_emails(access_token)
    
    if res.status_code == 401:
        # Token might be expired, attempt refresh
        new_token = refresh_outlook_token(client)
        if new_token:
            res = _fetch_emails(new_token)
            
    if res.status_code != 200:
        logger.error(f"Failed to fetch outlook emails: {res.text}")
        return 0
        
    messages_data = res.json().get('value', [])
    if not messages_data:
        return 0

    # Ensure EmailAccount exists
    account, _ = EmailAccount.objects.get_or_create(
        client=client,
        provider='outlook',
        email_address=config.get('email_address', ''),
        defaults={'display_name': config.get('display_name', '')}
    )

    synced_count = 0
    for msg in messages_data:
        graph_id = msg.get('id')
        
        # Check if already synced
        if EmailMessage.objects.filter(client=client, account=account, metadata__graph_id=graph_id).exists():
            continue
            
        subject = msg.get('subject') or "(No Subject)"
        body_preview = msg.get('bodyPreview') or ""
        body_content = msg.get('body', {}).get('content') or ""
        is_read = msg.get('isRead', False)
        
        sender_email = msg.get('sender', {}).get('emailAddress', {}).get('address', '')
        sender_name = msg.get('sender', {}).get('emailAddress', {}).get('name', '')
        
        to_recipients = []
        for r in msg.get('toRecipients', []):
            addr = r.get('emailAddress', {}).get('address')
            if addr:
                to_recipients.append(addr)
                
        # Basic mapping of folders (by default we just put them in inbox for now)
        folder = 'inbox'
        
        received_date = msg.get('receivedDateTime')
        
        incoming_msg = EmailMessage.objects.create(
            client=client,
            account=account,
            folder=folder,
            sender_email=sender_email,
            sender_name=sender_name,
            to_recipients=to_recipients,
            subject=subject,
            body_text=body_preview,
            body_html=body_content,
            is_read=is_read,
            status='delivered',
            priority='normal',
            metadata={'graph_id': graph_id, 'original_date': received_date}
        )
        synced_count += 1

        # Evaluate Automation via Enterprise Idempotency & Classification Engine
        from .email_automation_engine import process_incoming_email_automation
        try:
            process_incoming_email_automation(
                client=client,
                account=account,
                provider_message_id=graph_id,
                sender_email=sender_email,
                sender_name=sender_name,
                subject=subject,
                body_text=body_preview or body_content,
                incoming_email_message=incoming_msg,
                provider='outlook'
            )
        except Exception as auto_err:
            logger.error(f"[OutlookSync] Automation error: {auto_err}")
        
    if synced_count > 0:
        now_str = datetime.now(timezone.utc).isoformat()
        config['last_sync'] = now_str
        client.outlook_config = config
        client.save()
        
    return synced_count
