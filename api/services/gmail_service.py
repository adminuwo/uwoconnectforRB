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
        token_uri=config.get('token_uri'),
        client_id=config.get('client_id'),
        client_secret=config.get('client_secret'),
        scopes=config.get('scopes')
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
                    
            # Extract plain text body
            body = ""
            if 'parts' in full_msg['payload']:
                for part in full_msg['payload']['parts']:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data')
                        if data:
                            body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif 'body' in full_msg['payload'] and 'data' in full_msg['payload']['body']:
                data = full_msg['payload']['body']['data']
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                
            if not body:
                body = "[No readable text content]"

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

            # Check if this message was already synced
            if not Message.objects.filter(client=client, channel='GMAIL', metadata__gmail_id=msg_id).exists():
                Message.objects.create(
                    client=client,
                    channel='GMAIL',
                    from_address=sender_email,
                    to_address=config.get('email_address', ''),
                    body=f"Subject: {subject}\n\n{body}",
                    message_type='INCOMING',
                    status='DELIVERED',
                    metadata={'gmail_id': msg_id}
                )
                
            # Check if already synced in EmailMessage
            if not EmailMessage.objects.filter(client=client, account=account, metadata__gmail_id=msg_id).exists():
                incoming_msg = EmailMessage.objects.create(
                    client=client,
                    account=account,
                    folder='inbox',
                    sender_email=sender_email,
                    sender_name=contact.name,
                    to_recipients=[config.get('email_address', '')],
                    subject=subject,
                    body_text=body,
                    body_html=body,
                    is_read='UNREAD' not in full_msg.get('labelIds', []),
                    status='delivered',
                    priority='normal',
                    metadata={'gmail_id': msg_id}
                )
                new_messages_count += 1

                # Trigger Auto-Replies
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
                        if kw not in subject.lower() and kw not in body.lower():
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
                                sender_email=config.get('email_address', ''),
                                sender_name=account.display_name or config.get('email_address', ''),
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
