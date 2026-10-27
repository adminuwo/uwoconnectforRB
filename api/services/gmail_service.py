import base64
import email.message
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
from api.models import Message, Contact, EmailMessage, EmailAccount

def send_gmail_message(client, to_address, body, subject="New Message", cc=None, bcc=None):
    """
    Sends an email using the Gmail API on behalf of the client. Supports CC and BCC headers.
    """
    if not client.gmail_enabled or not client.gmail_config:
        raise Exception("Gmail is not enabled or configured for this client.")
        
    config = client.gmail_config
    
    # Reconstruct credentials object
    creds = Credentials(
        token=config.get('token'),
        refresh_token=config.get('refresh_token'),
        token_uri=config.get('token_uri') or 'https://oauth2.googleapis.com/token',
        client_id=config.get('client_id') or os.environ.get('GMAIL_CLIENT_ID'),
        client_secret=config.get('client_secret') or os.environ.get('GMAIL_CLIENT_SECRET'),
        scopes=config.get('scopes') or ['https://www.googleapis.com/auth/gmail.modify']
    )
    
    # Check if we have credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            # Update the stored token if it was refreshed
            client.gmail_config['token'] = creds.token
            client.save()
        else:
            raise Exception("Invalid Gmail credentials. Please reconnect Gmail.")

    try:
        service = build('gmail', 'v1', credentials=creds)
        
        message = email.message.EmailMessage()
        message.set_content(body)
        
        message['To'] = to_address
        message['From'] = config.get('email_address', '')
        message['Subject'] = subject
        if cc:
            message['Cc'] = cc
        if bcc:
            message['Bcc'] = bcc

        # Encode the message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        create_message = {
            'raw': encoded_message
        }
        
        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        
        return {
            "success": True,
            "message_id": send_message.get('id')
        }
    except Exception as e:
        print(f"Failed to send Gmail message: {str(e)}")
        raise Exception(f"Gmail API Error: {str(e)}")

import html
import re

def html_to_plain_text(html_content):
    if not html_content:
        return ""
    text = re.sub(r'<(script|style)[^>]*>[\s\S]*?</\1>', '', html_content, flags=re.IGNORECASE)
    text = re.sub(r'</?(p|div|tr|h[1-6]|li|br|hr)[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return '\n'.join(clean_lines)

def extract_email_body(payload, snippet=""):
    """
    Recursively extracts plain text or HTML body from a Gmail message payload.
    Falls back to message snippet if no readable part is found.
    """
    body_text = ""
    body_html = ""

    def _walk_parts(parts):
        nonlocal body_text, body_html
        for part in parts:
            mime = part.get('mimeType', '')
            data = part.get('body', {}).get('data')
            if data:
                try:
                    decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    if mime == 'text/plain' and not body_text:
                        body_text = decoded
                    elif mime == 'text/html' and not body_html:
                        body_html = decoded
                except Exception:
                    pass
            if 'parts' in part:
                _walk_parts(part['parts'])

    if 'parts' in payload:
        _walk_parts(payload['parts'])
    elif 'body' in payload and 'data' in payload['body']:
        mime = payload.get('mimeType', '')
        data = payload['body']['data']
        try:
            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            if mime == 'text/html':
                body_html = decoded
            else:
                body_text = decoded
        except Exception:
            pass

    # If body_text is missing but HTML is available, convert to clean plain text
    if not body_text and body_html:
        body_text = html_to_plain_text(body_html)

    # Fallback to snippet if text is still empty
    if not body_text:
        body_text = snippet or "[No readable text content]"

    if not body_html:
        body_html = body_text

    return body_text, body_html

def should_skip_autoreply(sender_email, sender_name, subject, headers, client_email, body_text="", gmail_labels=None):
    """
    Returns True if incoming email is automated, a bounce, no-reply, promotional,
    newsletter, advertisement, or self-sent.
    Uses multi-signal classification.
    """
    if not sender_email:
        return True

    from .email_classifier import EmailClassifier
    result = EmailClassifier.classify(
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        headers=headers,
        body_text=body_text,
        gmail_labels=gmail_labels,
        client_email=client_email
    )
    return result.is_unwanted


def sync_incoming_gmails(client):
    """
    Fetches unread emails from the connected Gmail account,
    saves them as Messages, and removes the UNREAD label.
    """
    if not client.gmail_enabled or not client.gmail_config:
        return 0

    config = client.gmail_config
    creds = Credentials(
        token=config.get('token'),
        refresh_token=config.get('refresh_token'),
        token_uri=config.get('token_uri'),
        client_id=config.get('client_id'),
        client_secret=config.get('client_secret'),
        scopes=config.get('scopes')
    )
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            client.gmail_config['token'] = creds.token
            client.save()
        else:
            return 0

    try:
        service = build('gmail', 'v1', credentials=creds)
        
        # Get recent messages in inbox (max 15 to avoid long initial syncs)
        results = service.users().messages().list(userId='me', q="label:inbox", maxResults=15).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return 0
            
        new_messages_count = 0
            
        for msg in messages:
            msg_id = msg['id']
            full_msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            headers = full_msg['payload'].get('headers', [])
            subject = "No Subject"
            sender = "Unknown"
            
            for header in headers:
                if header['name'].lower() == 'subject':
                    subject = header['value']
                elif header['name'].lower() == 'from':
                    sender = header['value']
                    
            # Extract recursive text body or fallback to snippet
            snippet = full_msg.get('snippet', '')
            body_text, body_html = extract_email_body(full_msg['payload'], snippet)

            # Clean sender email from "Name <email>" format
            import re
            email_match = re.search(r'<([^>]+)>', sender)
            if email_match:
                sender_email = email_match.group(1)
            else:
                sender_email = sender
                
            # Create Contact if doesn't exist
            contact, _ = Contact.objects.get_or_create(
                client=client,
                platform_id=sender_email,
                defaults={
                    'name': sender.split('<')[0].strip(),
                    'email': sender_email,
                    'stage': 'NEW'
                }
            )

            # Ensure EmailAccount exists
            account, _ = EmailAccount.objects.get_or_create(
                client=client,
                provider='gmail',
                email_address=config.get('email_address', ''),
                defaults={'display_name': config.get('email_address', '')}
            )

            # Check if this message was already synced in Message
            if not Message.objects.filter(client=client, channel='GMAIL', metadata__gmail_id=msg_id).exists():
                Message.objects.create(
                    client=client,
                    channel='GMAIL',
                    from_address=sender_email,
                    to_address=config.get('email_address', ''),
                    body=f"Subject: {subject}\n\n{body_text}",
                    message_type='INCOMING',
                    status='DELIVERED',
                    metadata={'gmail_id': msg_id}
                )
                
            # Check if already synced in EmailMessage
            if not EmailMessage.objects.filter(client=client, account=account, metadata__gmail_id=msg_id).exists():
                is_bounce_or_failure = (
                    'mailer-daemon' in sender_email.lower() or
                    'postmaster' in sender_email.lower() or
                    'delivery status notification' in subject.lower() or
                    'undelivered mail' in subject.lower()
                )
                target_folder = 'trash' if is_bounce_or_failure else 'inbox'

                incoming_msg = EmailMessage.objects.create(
                    client=client,
                    account=account,
                    folder=target_folder,
                    sender_email=sender_email,
                    sender_name=contact.name,
                    to_recipients=[config.get('email_address', '')],
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    is_read='UNREAD' not in full_msg.get('labelIds', []),
                    status='delivered',
                    priority='normal',
                    metadata={'gmail_id': msg_id}
                )
                new_messages_count += 1
                # Evaluate Automation via Enterprise Idempotency & Classification Engine
                from .email_automation_engine import process_incoming_email_automation
                try:
                    process_incoming_email_automation(
                        client=client,
                        account=account,
                        provider_message_id=msg_id,
                        sender_email=sender_email,
                        sender_name=contact.name,
                        subject=subject,
                        body_text=body_text,
                        headers=headers,
                        gmail_labels=full_msg.get('labelIds', []),
                        incoming_email_message=incoming_msg,
                        provider='gmail'
                    )
                except Exception as auto_err:
                    print(f"Gmail Automation Engine Error: {str(auto_err)}")

        return new_messages_count
    except Exception as e:
        print(f"Gmail Sync Error: {str(e)}")
        return 0
