import base64
import email.message
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
from api.models import Message, Contact, EmailMessage, EmailAccount

def send_gmail_message(client, to_address, body, subject="New Message"):
    """
    Sends an email using the Gmail API on behalf of the client.
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

def should_skip_autoreply(sender_email, sender_name, subject, headers, client_email):
    """
    Returns True if incoming email is automated, a bounce, no-reply, or self-sent.
    """
    if not sender_email:
        return True
        
    s_email = sender_email.lower().strip()
    s_subj = (subject or "").lower()
    
    # Do not reply to self
    if client_email and s_email == client_email.lower().strip():
        return True

    # Senders to skip (bots, daemons, notifications, noreply)
    skip_sender_keywords = [
        'mailer-daemon', 'postmaster', 'no-reply', 'noreply', 'donotreply',
        'do-not-reply', 'bounce', 'system', 'notification', 'alert', 'support@razorpay',
        'downtime-alerts', 'em.linkedin.com', 'googlemail.com'
    ]
    if any(k in s_email for k in skip_sender_keywords):
        return True

    # Subjects indicating automated/bounce responses
    skip_subject_keywords = [
        'delivery status notification', 'undelivered mail', 'failure notice',
        'returned to sender', 'auto-reply', 'automatic reply', 'out of office',
        'vacation', 'mail delivery failed', 'failed delivery'
    ]
    if any(k in s_subj for k in skip_subject_keywords):
        return True

    # Check headers for automation flags
    for h in headers:
        h_name = h.get('name', '').lower()
        h_val = h.get('value', '').lower()
        if h_name == 'auto-submitted' and h_val != 'no':
            return True
        if h_name == 'precedence' and h_val in ['bulk', 'junk', 'list']:
            return True
        if h_name == 'x-autoreply' and h_val == 'yes':
            return True

    return False

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

                # Trigger Auto-Replies ONLY for legitimate incoming emails (skip bots, bounces, and self)
                client_email = config.get('email_address', '')
                if not should_skip_autoreply(sender_email, contact.name, subject, headers, client_email):
                    from api.models import EmailAutoReplyRule
                    active_rules = EmailAutoReplyRule.objects.filter(client=client, is_active=True)
                    for rule in active_rules:
                        # Match pattern
                        matches = True
                        if rule.subject_pattern and rule.subject_pattern.lower() not in subject.lower():
                            matches = False
                        if rule.sender_pattern and rule.sender_pattern.lower() not in sender_email.lower():
                            matches = False
                        if rule.keyword_match:
                            kw = rule.keyword_match.lower()
                            if kw not in subject.lower() and kw not in body_text.lower():
                                matches = False
                        
                        if matches:
                            # Personalize template
                            first_name = contact.name.split(' ')[0] if contact.name else "there"
                            last_name = contact.name.split(' ')[-1] if contact.name and ' ' in contact.name else ""
                            full_name = contact.name or "Valued Customer"
                            
                            r_body = rule.reply_body
                            r_body = r_body.replace('{{first_name}}', first_name)
                            r_body = r_body.replace('{{last_name}}', last_name)
                            r_body = r_body.replace('{{full_name}}', full_name)
                            r_body = r_body.replace('{{email}}', sender_email)
                            
                            r_subject = rule.reply_subject or f"Re: {subject}"
                            r_subject = r_subject.replace('{{first_name}}', first_name)
                            r_subject = r_subject.replace('{{last_name}}', last_name)
                            r_subject = r_subject.replace('{{full_name}}', full_name)
                            r_subject = r_subject.replace('{{email}}', sender_email)

                            try:
                                send_gmail_message(client, sender_email, r_body, r_subject)
                                # Log auto-reply as sent email
                                EmailMessage.objects.create(
                                    client=client,
                                    account=account,
                                    folder='sent',
                                    sender_email=client_email,
                                    sender_name=account.display_name or client_email,
                                    to_recipients=[sender_email],
                                    subject=r_subject,
                                    body_text=r_body,
                                    body_html=r_body,
                                    status='delivered',
                                    priority='normal',
                                    metadata={'reply_to_gmail_id': msg_id, 'auto_reply_rule_id': str(rule.id)}
                                )
                            except Exception as e:
                                print(f"AutoReply Send Error: {str(e)}")

        return new_messages_count
    except Exception as e:
        print(f"Gmail Sync Error: {str(e)}")
        return 0
