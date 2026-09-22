import os
import json
import re
import requests
from django.http import HttpResponse
from ..models import Client, Contact, Message, Automation, KnowledgeChunk
from .ai_service import get_ai_response, get_rag_response, get_embedding, find_relevant_chunks
from ..repositories.client_repository import ClientRepository
from ..repositories.contact_repository import ContactRepository
from ..repositories.message_repository import MessageRepository
from ..repositories.automation_repository import AutomationRepository
from ..repositories.knowledge_repository import KnowledgeRepository
import logging
logger = logging.getLogger(__name__)

class MetaWebhookService:
    @staticmethod
    def verify_whatsapp_webhook(mode, token, challenge):
        verify_token = os.getenv('WHATSAPP_VERIFY_TOKEN', 'aisaconnect_secure_token')
        if mode and token:
            if mode == 'subscribe' and token == verify_token:
                print("WEBHOOK_VERIFIED")
                return HttpResponse(challenge, content_type="text/plain", status=200)
            else:
                return HttpResponse("Forbidden", content_type="text/plain", status=403)
        return HttpResponse("Bad Request", content_type="text/plain", status=400)

    @staticmethod
    def verify_fb_ig_webhook(mode, token, challenge):
        verify_token = os.getenv('WHATSAPP_VERIFY_TOKEN') or 'aisaconnect_secure_token'
        if mode and token:
            if mode == 'subscribe' and token == verify_token:
                print("FB/IG WEBHOOK_VERIFIED")
                return HttpResponse(challenge, content_type="text/plain", status=200)
            else:
                return HttpResponse("Forbidden", content_type="text/plain", status=403)
        return HttpResponse("Bad Request", content_type="text/plain", status=400)

    @staticmethod
    def handle_whatsapp_message(data):
        print("Incoming WhatsApp Webhook Payload:", json.dumps(data, indent=2))
        try:
            if data.get('object') == 'whatsapp_business_account':
                for entry in data.get('entry') or []:
                    entry = entry or {}
                    for change in entry.get('changes') or []:
                        change = change or {}
                        value = change.get('value') or {}
                        metadata = value.get('metadata') or {}
                        phone_number_id = metadata.get('phone_number_id')
                        
                        client = ClientRepository.filter_clients(whatsapp_phone_number_id=str(phone_number_id)).first() if phone_number_id else None
                        if not client:
                            client = Client.objects.filter(whatsapp_phone_number_id__isnull=False).exclude(whatsapp_phone_number_id='').first() or Client.objects.first()
                        if not client:
                            print(f"No client found for phone_number_id: {phone_number_id}")
                            continue

                        # NOTE: We always store incoming messages regardless of automation_enabled.
                        # automation_enabled only controls whether the AI bot sends an automated reply.

                        contacts = value.get('contacts') or []
                        contact_name = "Unknown"
                        if contacts:
                            contact_name = (contacts[0].get('profile') or {}).get('name', 'Unknown')

                        messages = value.get('messages') or []
                        for msg in messages:
                            from_number = msg.get('from')
                            msg_type = msg.get('type')
                            body = ""
                            media_id = None
                            media_url_fetched = None
                            media_type_tag = None
                            media_filename_tag = None
                            media_mime_tag = None

                            if msg_type == 'text':
                                body = (msg.get('text') or {}).get('body', '')
                            elif msg_type == 'image':
                                img_data = msg.get('image') or {}
                                caption = img_data.get('caption', '')
                                media_id = img_data.get('id')
                                media_type_tag = 'image'
                                media_mime_tag = img_data.get('mime_type', 'image/jpeg')
                                body = f"📷 {caption}" if caption else "📷 [Photo]"
                            elif msg_type == 'document':
                                doc_data = msg.get('document') or {}
                                filename = doc_data.get('filename') or 'Document'
                                caption = doc_data.get('caption', '')
                                media_id = doc_data.get('id')
                                media_type_tag = 'document'
                                media_filename_tag = filename
                                media_mime_tag = doc_data.get('mime_type', 'application/octet-stream')
                                body = f"📄 {filename}" + (f" - {caption}" if caption else "")
                            elif msg_type == 'audio' or msg_type == 'voice':
                                audio_data = msg.get('audio') or msg.get('voice') or {}
                                audio_id = audio_data.get('id')
                                body = "🎵 [Voice Note / Audio]"
                                if audio_id and client.whatsapp_access_token:
                                    try:
                                        media_url_endpoint = f"https://graph.facebook.com/v18.0/{audio_id}"
                                        headers = {"Authorization": f"Bearer {client.whatsapp_access_token}"}
                                        media_res = requests.get(media_url_endpoint, headers=headers, timeout=5).json()
                                        media_url = media_res.get('url')
                                        if media_url:
                                            from ..utils.whisper_utils import transcribe_audio_with_whisper
                                            transcribed_text = transcribe_audio_with_whisper(media_url, client.whatsapp_access_token)
                                            if transcribed_text:
                                                body = f"🎵 {transcribed_text}"
                                                print(f"Transcribed WhatsApp audio successfully: {body}")
                                    except Exception as ex:
                                        print(f"Failed parsing incoming voice note: {str(ex)})")
                            elif msg_type == 'video':
                                vid_data = msg.get('video') or {}
                                caption = vid_data.get('caption', '')
                                media_id = vid_data.get('id')
                                media_type_tag = 'video'
                                media_mime_tag = vid_data.get('mime_type', 'video/mp4')
                                body = f"🎥 {caption}" if caption else "🎥 [Video]"
                            elif msg_type == 'location':
                                loc = msg.get('location') or {}
                                loc_name = loc.get('name') or loc.get('address') or f"{loc.get('latitude')}, {loc.get('longitude')}"
                                body = f"📍 [Location: {loc_name}]"
                            elif msg_type == 'sticker':
                                body = "🎨 [Sticker]"
                            elif msg_type == 'button':
                                body = (msg.get('button') or {}).get('text', '')
                            elif msg_type == 'interactive':
                                i_type = (msg.get('interactive') or {}).get('type')
                                if i_type == 'button_reply':
                                    body = (msg.get('interactive') or {}).get('button_reply', {}).get('title', '')
                                elif i_type == 'list_reply':
                                    body = (msg.get('interactive') or {}).get('list_reply', {}).get('title', '')
                            elif msg_type == 'reaction':
                                emoji = (msg.get('reaction') or {}).get('emoji', '👍')
                                body = f"{emoji} [Reaction]"
                            elif msg_type in ['contacts', 'vcard']:
                                body = "👤 [Contact Card]"
                            elif msg_type == 'system':
                                body = "ℹ️ [System Notification]"
                            elif msg_type == 'unsupported':
                                body = "📎 [Attachment / Media]"
                            elif not body:
                                body = f"📎 [{msg_type.capitalize()}]"

                            # --- Fetch Media URL from Meta Graph API (image, document, video) ---
                            if media_id and client.whatsapp_access_token:
                                try:
                                    import threading
                                    def _fetch_and_save_media(msg_obj_id, _media_id, _token, _media_type, _filename, _mime):
                                        try:
                                            from ..models import Message as MsgModel
                                            endpoint = f"https://graph.facebook.com/v19.0/{_media_id}"
                                            hdrs = {"Authorization": f"Bearer {_token}"}
                                            r = requests.get(endpoint, headers=hdrs, timeout=8)
                                            if r.status_code == 200:
                                                _url = r.json().get('url')
                                                if _url:
                                                    MsgModel.objects.filter(id=msg_obj_id).update(
                                                        media_url=_url,
                                                        media_type=_media_type,
                                                        media_filename=_filename,
                                                        media_mime_type=_mime
                                                    )
                                        except Exception as _me:
                                            logger.warning("Media URL fetch failed for %s: %s", _media_id, _me)

                                    # We'll save message first, then fetch media in background
                                    _fetch_media_later = True
                                except Exception:
                                    _fetch_media_later = False
                            else:
                                _fetch_media_later = False

                            try:
                                from django.utils import timezone
                                from ..models import Conversation

                                # Extract lead contact details from body if available
                                extracted_wa_phone = None
                                extracted_wa_email = None
                                if body:
                                    m_lead_name = re.search(r'(?:Full\s*name|Name)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                                    if m_lead_name and m_lead_name.group(1).strip() and m_lead_name.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                                        contact_name = m_lead_name.group(1).strip()
                                    m_lead_p = re.search(r'(?:Phone\s*(?:number)?|Mobile)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                                    if m_lead_p and m_lead_p.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                                        extracted_wa_phone = m_lead_p.group(1).strip()
                                    m_lead_e = re.search(r'(?:Email|E-mail)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                                    if m_lead_e and m_lead_e.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                                        extracted_wa_email = m_lead_e.group(1).strip()

                                # If contact_name is still generic or Unknown, default to phone number
                                is_wa_generic = lambda n: not n or str(n).strip().upper() in ['UNKNOWN', 'UNKNOWN USER', 'USER', 'CUSTOMER', 'NONE', 'NULL', '']
                                if is_wa_generic(contact_name):
                                    contact_name = f"+{from_number}" if from_number else "Customer"

                                contact, _ = ContactRepository.get_contact_or_create(
                                    client=client,
                                    platform_id=from_number,
                                    defaults={
                                        'phone_number': extracted_wa_phone or from_number,
                                        'email': extracted_wa_email,
                                        'name': contact_name,
                                        'stage': 'NEW'
                                    }
                                )
                                if contact:
                                    contact.updated_at = timezone.now()
                                    ct_updated = False
                                    if is_wa_generic(contact.name) and not is_wa_generic(contact_name):
                                        contact.name = contact_name
                                        ct_updated = True
                                    elif not is_wa_generic(contact_name) and contact.name != contact_name:
                                        contact.name = contact_name
                                        ct_updated = True
                                    elif is_wa_generic(contact.name) and from_number:
                                        contact.name = f"+{from_number}"
                                        ct_updated = True
                                    if extracted_wa_phone and not contact.phone_number:
                                        contact.phone_number = extracted_wa_phone
                                        ct_updated = True
                                    if extracted_wa_email and not contact.email:
                                        contact.email = extracted_wa_email
                                        ct_updated = True
                                    if ct_updated:
                                        contact.save()

                                # Ensure Conversation record is kept fresh
                                try:
                                    convo = Conversation.objects.filter(client=client, contact_platform_id=from_number).first()
                                    if not convo:
                                        Conversation.objects.create(
                                            client=client,
                                            contact=contact,
                                            contact_platform_id=from_number,
                                            channel='WHATSAPP',
                                            last_message_summary=body or 'Incoming Message',
                                            last_message_at=timezone.now()
                                        )
                                    else:
                                        convo.last_message_summary = body or 'Incoming Message'
                                        convo.last_message_at = timezone.now()
                                        if not convo.contact:
                                            convo.contact = contact
                                        convo.save()
                                except Exception as _c_err:
                                    logger.warning("Error saving conversation: %s", _c_err)
                            except Exception as _ct_err:
                                logger.warning("Error creating contact: %s", _ct_err)

                            # Always store the message — dashboard must show all messages
                            incoming_msg_obj = MessageRepository.create_message(
                                client=client,
                                channel='WHATSAPP',
                                from_address=from_number,
                                to_address=phone_number_id,
                                body=body,
                                message_type='INCOMING',
                                whatsapp_message_id=msg.get('id'),
                                status='RECEIVED',
                                metadata=msg
                            )

                            # Launch background thread to fetch & save Media URL from Meta
                            if _fetch_media_later and incoming_msg_obj and media_id and client.whatsapp_access_token:
                                try:
                                    import threading
                                    threading.Thread(
                                        target=_fetch_and_save_media,
                                        args=(
                                            incoming_msg_obj.id,
                                            media_id,
                                            client.whatsapp_access_token,
                                            media_type_tag,
                                            media_filename_tag,
                                            media_mime_tag
                                        ),
                                        daemon=True
                                    ).start()
                                except Exception as _mt_err:
                                    logger.warning("Could not start media fetch thread: %s", _mt_err)

                            # OneDrive: sync media files in background
                            try:
                                from ..services.onedrive_sync_service import sync_whatsapp_media_to_onedrive
                                sync_whatsapp_media_to_onedrive(client, msg)
                            except Exception as _ode:
                                logger.warning("OneDrive WA hook error: %s", _ode)

                            # Google Sheets: auto-export incoming WhatsApp lead/message in background
                            if client.google_sheets_enabled:
                                try:
                                    import threading
                                    from ..services.google_sheets_service import append_lead_row
                                    contact_name = contact.name or f"WhatsApp ({from_number})"
                                    threading.Thread(
                                        target=append_lead_row,
                                        args=(client, "WHATSAPP", contact_name, from_number, "INCOMING_MESSAGE", body, "NEW"),
                                        daemon=True
                                    ).start()
                                except Exception as _gse:
                                    logger.warning("Google Sheets WA hook error: %s", _gse)

                            # Zoho CRM: auto-export incoming WhatsApp lead in background
                            if client.zoho_enabled:
                                try:
                                    from ..services.zoho_service import create_zoho_lead
                                    import threading
                                    
                                    def run_zoho_sync():
                                        try:
                                            lead_data = {
                                                "Last_Name": contact.name or f"WhatsApp ({from_number})",
                                                "Phone": from_number,
                                                "Lead_Source": "WhatsApp Chatbot"
                                            }
                                            create_zoho_lead(client, lead_data)
                                        except Exception as e:
                                            logger.warning(f"Background Zoho Sync Failed: {e}")
                                            
                                    threading.Thread(target=run_zoho_sync, daemon=True).start()
                                except Exception as _ze:
                                    logger.warning("Zoho WA hook error: %s", _ze)

                            # Only run AI bot automation if enabled AND bot not paused for this contact
                            if body and client.automation_enabled:
                                if not contact.bot_paused:
                                    # Bot Loop Prevention & Repeated Message Protection check
                                    from .bot_loop_protection_service import BotLoopProtectionService
                                    if BotLoopProtectionService.check_and_protect(
                                        client=client,
                                        contact_platform_id=from_number,
                                        incoming_text=body,
                                        channel='WHATSAPP',
                                        contact=contact,
                                        conversation=convo,
                                        current_message=incoming_msg_obj
                                    ):
                                        logger.warning(f"Bot loop protection triggered for WhatsApp contact {from_number}. Automated responses halted.")
                                    else:
                                        MetaWebhookService.handle_automations_whatsapp(client, from_number, body, phone_number_id)
                                else:
                                    print(f"Bot paused for contact {from_number}. No automated response.")

                        # Handle WhatsApp delivery and read receipts
                        statuses = value.get('statuses') or []
                        for st in statuses:
                            wamid = st.get('id')
                            status_raw = (st.get('status') or '').strip().upper()
                            if wamid and status_raw in ['SENT', 'DELIVERED', 'READ', 'FAILED']:
                                try:
                                    msg_to_update = Message.objects.filter(
                                        client=client,
                                        whatsapp_message_id=wamid
                                    ).first()
                                    if not msg_to_update:
                                        msg_to_update = Message.objects.filter(
                                            client=client,
                                            metadata__response__messages__0__id=wamid
                                        ).first()
                                    if not msg_to_update:
                                        msg_to_update = Message.objects.filter(whatsapp_message_id=wamid).first()
                                    if msg_to_update:
                                        msg_client = msg_to_update.client or client
                                        current_status = (msg_to_update.status or 'SENT').upper()
                                        status_ranks = {'PENDING': 0, 'SENT': 1, 'DELIVERED': 2, 'READ': 3, 'FAILED': 99}
                                        new_rank = status_ranks.get(status_raw, 0)
                                        curr_rank = status_ranks.get(current_status, 0)

                                        if new_rank >= curr_rank or status_raw == 'FAILED':
                                            msg_to_update.status = status_raw
                                            msg_to_update.save()

                                            # Real-time WebSocket event broadcast to inbox group
                                            try:
                                                from channels.layers import get_channel_layer
                                                from asgiref.sync import async_to_sync
                                                channel_layer = get_channel_layer()
                                                if channel_layer and msg_client:
                                                    async_to_sync(channel_layer.group_send)(
                                                        f"inbox_{msg_client.id}",
                                                        {
                                                            "type": "message_status_update",
                                                            "message_id": str(msg_to_update.id),
                                                            "whatsapp_message_id": wamid,
                                                            "status": status_raw,
                                                            "from_address": msg_to_update.from_address,
                                                            "to_address": msg_to_update.to_address
                                                        }
                                                    )
                                            except Exception as _ws_err:
                                                pass
                                except Exception as _st_err:
                                    logger.warning(f"Error updating message status from webhook: {_st_err}")

            return {"status": "success", "status_code": 200}
        except Exception as e:
            print(f"Error processing webhook: {str(e)}")
            return {"status": "error", "status_code": 500}

    @staticmethod
    def handle_fb_ig_message(data):
        logger.warning(f"Incoming FB/IG Webhook Payload: {json.dumps(data)}")
        try:
            for entry in data.get('entry') or []:
                entry = entry or {}
                entry_id = entry.get('id')
                messaging = entry.get('messaging', []) or []
                
                # Collect all possible recipient candidate IDs (from entry.id or messaging recipient.id)
                recipient_candidates = [str(entry_id)] if entry_id else []
                for event in messaging:
                    rec_id = event.get('recipient', {}).get('id')
                    if rec_id and str(rec_id) not in recipient_candidates:
                        recipient_candidates.append(str(rec_id))

                client = None
                platform = None
                recipient_id = entry_id or (recipient_candidates[0] if recipient_candidates else None)
                all_clients = ClientRepository.get_all_clients()
                
                if data.get('object') == 'page':
                    platform = 'FACEBOOK'
                    for c in all_clients:
                        fc = c.facebook_config or {}
                        ic = c.instagram_config or {}
                        fb_candidates = [
                            str(fc.get('page_id', '')),
                            str(fc.get('account_id', '')),
                            str(ic.get('page_id', ''))
                        ]
                        for extra_id in (fc.get('facebook_page_ids') or []):
                            fb_candidates.append(str(extra_id))
                        valid_ids = [i for i in fb_candidates if i and i != 'None']
                        if any(rc in valid_ids for rc in recipient_candidates):
                            client = c
                            break
                    if not client:
                        fb_clients = [c for c in all_clients if c.facebook_enabled or (c.facebook_config and c.facebook_config.get('access_token'))]
                        if len(fb_clients) == 1:
                            client = fb_clients[0]
                elif data.get('object') == 'instagram':
                    platform = 'INSTAGRAM'
                    for c in all_clients:
                        ic = c.instagram_config or {}
                        fc = c.facebook_config or {}
                        ig_candidates = [
                            str(ic.get('instagram_business_id', '')),
                            str(ic.get('instagram_user_id', '')),
                            str(ic.get('account_id', '')),
                            str(ic.get('page_id', '')),
                            str(ic.get('username', '')),
                            str(fc.get('page_id', ''))
                        ]
                        for extra_id in (ic.get('instagram_business_ids') or []):
                            ig_candidates.append(str(extra_id))
                        valid_ids = [i for i in ig_candidates if i and i != 'None']
                        if any(rc in valid_ids for rc in recipient_candidates):
                            client = c
                            break
                    if not client:
                        ig_clients = [c for c in all_clients if c.instagram_enabled or (c.instagram_config and c.instagram_config.get('access_token'))]
                        if len(ig_clients) == 1:
                            client = ig_clients[0]
                            # Auto-learn the incoming business ID so subsequent lookups match immediately
                            try:
                                cfg = client.instagram_config or {}
                                extra_ids = list(set((cfg.get('instagram_business_ids') or []) + recipient_candidates))
                                cfg['instagram_business_ids'] = extra_ids
                                if recipient_candidates and not cfg.get('instagram_business_id'):
                                    cfg['instagram_business_id'] = recipient_candidates[0]
                                client.instagram_config = cfg
                                client.save(update_fields=['instagram_config'])
                            except Exception as _cfg_err:
                                logger.warning("Could not auto-update client IG IDs: %s", _cfg_err)
                
                if not client:
                    logger.warning(f"No client found for {platform} recipient IDs: {recipient_candidates}")
                    continue

                # NOTE: Always store incoming messages regardless of automation_enabled.
                # automation_enabled only controls whether the AI bot sends an automated reply.

                messaging = entry.get('messaging', [])
                for event in messaging:
                    # Ignore delivery and read receipts
                    if 'delivery' in event or 'read' in event:
                        continue
                        
                    sender_id = event.get('sender', {}).get('id')
                    
                    # If the sender is our own Page/Account, it's an echo message sent by the bot. Ignore it!
                    if str(sender_id) == str(recipient_id):
                        continue
                        
                    body = ""
                    
                    if 'message' in event:
                        msg_data = event.get('message', {})
                        
                        # Explicit is_echo check just in case
                        if msg_data.get('is_echo'):
                            continue
                            
                        if 'quick_reply' in msg_data:
                            body = msg_data.get('quick_reply', {}).get('payload', '')
                        else:
                            body = msg_data.get('text', '')
                        
                        # Handle media attachments (image, audio, video, file)
                        attachments = msg_data.get('attachments', [])
                        if attachments:
                            att_parts = []
                            for att in attachments:
                                att_type = att.get('type', 'file')
                                title = (att.get('payload') or {}).get('title', '')
                                if att_type == 'image':
                                    att_parts.append("📷 [Photo]")
                                elif att_type in ('file', 'doc'):
                                    att_parts.append(f"📄 [{title or 'Document'}]")
                                elif att_type == 'audio':
                                    att_parts.append("🎵 [Audio]")
                                elif att_type == 'video':
                                    att_parts.append("🎥 [Video]")
                                else:
                                    att_parts.append(f"📎 [{att_type.capitalize()}]")
                            
                            media_summary = " ".join(att_parts)
                            body = f"{body} {media_summary}".strip() if body else media_summary

                    elif 'postback' in event:
                        body = event.get('postback', {}).get('payload', '') or event.get('postback', {}).get('title', '')
                    else:
                        # Unhandled event type, ignore
                        continue
                    
                    if not body:
                        body = "📎 [Attachment / Media]"
                    
                    extracted_lead_name = None
                    extracted_lead_phone = None
                    extracted_lead_email = None

                    if body:
                        m_lead_n = re.search(r'(?:Full\s*name|Name)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                        if m_lead_n and m_lead_n.group(1).strip() and m_lead_n.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                            extracted_lead_name = m_lead_n.group(1).strip()
                        m_lead_p = re.search(r'(?:Phone\s*(?:number)?|Mobile)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                        if m_lead_p and m_lead_p.group(1).strip() and m_lead_p.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                            extracted_lead_phone = m_lead_p.group(1).strip()
                        m_lead_e = re.search(r'(?:Email|E-mail)\s*:\s*([^\n\r]+)', body, re.IGNORECASE)
                        if m_lead_e and m_lead_e.group(1).strip() and m_lead_e.group(1).strip().lower() not in ['none', 'null', 'n/a', '-']:
                            extracted_lead_email = m_lead_e.group(1).strip()

                    contact_name = extracted_lead_name or f"{platform} User"
                    access_token = None
                    if platform == 'INSTAGRAM':
                        access_token = (client.instagram_config or {}).get('access_token') or (client.facebook_config or {}).get('access_token')
                    elif platform == 'FACEBOOK':
                        access_token = (client.facebook_config or {}).get('access_token') or (client.instagram_config or {}).get('access_token')

                    profile_pic_url = None
                    if not extracted_lead_name and access_token:
                        try:
                            import requests
                            if platform == 'INSTAGRAM':
                                # 1st attempt: username, name, profile_pic
                                url = f"https://graph.facebook.com/v20.0/{sender_id}?fields=username,name,profile_pic&access_token={access_token}"
                                res = requests.get(url, timeout=5)
                                if res.status_code == 200:
                                    u_data = res.json()
                                    username = u_data.get('username')
                                    real_name = u_data.get('name')
                                    profile_pic_url = u_data.get('profile_pic')
                                    if username and real_name and username.lower() != real_name.lower():
                                        contact_name = f"{real_name} (@{username})"
                                    elif username:
                                        contact_name = f"@{username}"
                                    elif real_name:
                                        contact_name = real_name
                                else:
                                    # Fallback 2nd attempt: only username (succeeds even if name is restricted by user privacy)
                                    url_user = f"https://graph.facebook.com/v20.0/{sender_id}?fields=username&access_token={access_token}"
                                    res_user = requests.get(url_user, timeout=5)
                                    if res_user.status_code == 200:
                                        u_data = res_user.json()
                                        if u_data.get('username'):
                                            contact_name = f"@{u_data.get('username')}"
                            elif platform == 'FACEBOOK':
                                # 1st attempt: first_name, last_name, name, profile_pic
                                url = f"https://graph.facebook.com/v20.0/{sender_id}?fields=first_name,last_name,name,profile_pic&access_token={access_token}"
                                res = requests.get(url, timeout=5)
                                if res.status_code == 200:
                                    f_data = res.json()
                                    profile_pic_url = f_data.get('profile_pic')
                                    first_last = f"{f_data.get('first_name', '')} {f_data.get('last_name', '')}".strip()
                                    contact_name = f_data.get('name') or first_last or contact_name
                                else:
                                    # Fallback 2nd attempt: name only
                                    url_name = f"https://graph.facebook.com/v20.0/{sender_id}?fields=name&access_token={access_token}"
                                    res_name = requests.get(url_name, timeout=5)
                                    if res_name.status_code == 200:
                                        f_data = res_name.json()
                                        if f_data.get('name'):
                                            contact_name = f_data.get('name')
                        except Exception as ex:
                            logger.error(f"Failed to fetch {platform} user profile for {sender_id}: {str(ex)}")

                    contact, created = ContactRepository.get_contact_or_create(
                        client=client,
                        platform_id=sender_id,
                        defaults={
                            'phone_number': extracted_lead_phone or sender_id,
                            'email': extracted_lead_email,
                            'name': contact_name,
                            'stage': 'NEW'
                        }
                    )
                    
                    is_generic_name = lambda n: not n or n.upper().strip() in ['INSTAGRAM USER', 'FACEBOOK USER', 'UNKNOWN', 'USER', 'CUSTOMER', 'NONE', 'NULL']
                    if not created:
                        updated_fields = []
                        if is_generic_name(contact.name) and not is_generic_name(contact_name):
                            contact.name = contact_name
                            updated_fields.append('name')
                        elif contact_name and not is_generic_name(contact_name) and contact.name != contact_name:
                            contact.name = contact_name
                            updated_fields.append('name')
                        if extracted_lead_phone and (not contact.phone_number or contact.phone_number == sender_id):
                            contact.phone_number = extracted_lead_phone
                            updated_fields.append('phone_number')
                        if extracted_lead_email and not contact.email:
                            contact.email = extracted_lead_email
                            updated_fields.append('email')
                        if updated_fields:
                            contact.save()

                    # Keep Conversation record fresh for unified Live Inbox display
                    try:
                        from django.utils import timezone
                        from ..models import Conversation
                        convo = Conversation.objects.filter(client=client, contact_platform_id=sender_id).first()
                        if not convo:
                            Conversation.objects.create(
                                client=client,
                                contact=contact,
                                contact_platform_id=sender_id,
                                channel=platform,
                                last_message_summary=body or f'Incoming {platform} Message',
                                last_message_at=timezone.now()
                            )
                        else:
                            convo.last_message_summary = body or f'Incoming {platform} Message'
                            convo.last_message_at = timezone.now()
                            if not convo.contact:
                                convo.contact = contact
                            convo.save()
                    except Exception as _c_err:
                        logger.warning("Error saving %s conversation: %s", platform, _c_err)

                    incoming_msg_obj = MessageRepository.create_message(
                        client=client,
                        channel=platform,
                        from_address=sender_id,
                        to_address=recipient_id,
                        body=body,
                        message_type='INCOMING',
                        status='RECEIVED',
                        metadata=event
                    )

                    # OneDrive: sync attachments in background
                    try:
                        from ..services.onedrive_sync_service import sync_fb_ig_media_to_onedrive
                        msg_data = event.get('message', {})
                        sync_fb_ig_media_to_onedrive(client, msg_data, platform=platform)
                    except Exception as _ode:
                        logger.warning("OneDrive FB/IG hook error: %s", _ode)

                    # Only run AI bot automation if enabled AND bot not paused for this contact
                    if body and client.automation_enabled:
                        if not contact.bot_paused:
                            # Bot Loop Prevention & Repeated Message Protection check
                            from .bot_loop_protection_service import BotLoopProtectionService
                            if BotLoopProtectionService.check_and_protect(
                                client=client,
                                contact_platform_id=sender_id,
                                incoming_text=body,
                                channel=platform,
                                contact=contact,
                                conversation=convo if 'convo' in locals() else None,
                                current_message=incoming_msg_obj
                            ):
                                logger.warning(f"Bot loop protection triggered for {platform} contact {sender_id}. Automated responses halted.")
                            else:
                                MetaWebhookService.handle_automations_fb_ig(client, platform, sender_id, body)
                        else:
                            print(f"Bot paused for {platform} contact {sender_id}. No automated response.")

            return {"status": "success", "status_code": 200}
        except Exception as e:
            logger.error(f"Error processing FB/IG webhook: {str(e)}")
            return {"status": "error", "status_code": 500}

    @staticmethod
    def handle_ai_session_check(client, contact_id, incoming_text, platform='WHATSAPP', phone_number_id=None):
        """
        Handles the AI + Workflow Hybrid Session:
        - Detects direct "Talk to AI" trigger
        - Checks for active AI session
        - Enforces 2-minute (120s) inactivity timeout to cycle back to workflow
        - Processes manual exit ('Main Menu')
        - Performs RAG knowledge answering within the active session
        Returns True if handled, False otherwise.
        """
        import time
        from ..models import WorkflowSession, Contact
        from ..repositories.workflow_repository import WorkflowRepository
        from django.db.models import Q

        incoming_clean = incoming_text.strip().lower()

        # 1. Direct trigger for Talk to AI
        if incoming_clean in ['talk to ai', '🤖 talk to ai', 'chat with ai', 'ask ai', 'ai assistant']:
            # Deactivate any previous session
            WorkflowSession.objects.filter(client=client, phone_number=contact_id, is_active=True).update(is_active=False)

            active_wf = WorkflowRepository.filter_workflows(client=client, enabled=True).first()
            if not active_wf:
                active_wf = WorkflowRepository.filter_workflows(client=client).first()

            if active_wf:
                WorkflowSession.objects.create(
                    client=client,
                    phone_number=contact_id,
                    workflow=active_wf,
                    current_node_id='ai_chat_session',
                    variables={'ai_mode': True, 'last_ai_time': time.time()},
                    is_active=True
                )

            biz_name = getattr(client, 'business_name', 'our team')
            welcome_msg = (
                f"🤖 *AI Assistant Connected!*\n\n"
                f"I am your 24/7 AI Assistant for *{biz_name}*.\n\n"
                f"Ask me anything about our products, pricing, policies, or services!"
            )
            if platform == 'WHATSAPP':
                MetaWebhookService.send_whatsapp_message(
                    client=client,
                    to_number=contact_id,
                    text_body=welcome_msg,
                    phone_number_id=phone_number_id
                )
            else:
                MetaWebhookService.send_fb_ig_message(
                    client=client,
                    platform=platform,
                    recipient_id=contact_id,
                    text_body=welcome_msg
                )
            return True

        # 2. Check for active session in AI mode
        ai_session = WorkflowSession.objects.filter(client=client, phone_number=contact_id, is_active=True).first()
        if not ai_session or not ai_session.variables or not ai_session.variables.get('ai_mode'):
            return False

        last_ai_time = ai_session.variables.get('last_ai_time', 0)
        elapsed = time.time() - last_ai_time

        # Manual exit to Main Menu
        if incoming_clean in ['menu', 'main menu', 'exit', 'back', 'cancel', 'stop', 'quit', '📋 main menu']:
            ai_session.is_active = False
            ai_session.save()
            from .workflow_service import WorkflowEngine
            from ..repositories.workflow_repository import WorkflowRepository
            active_wf = WorkflowRepository.filter_workflows(client=client, enabled=True).first()
            wf_messages = None
            if active_wf:
                wf_messages = WorkflowEngine._start_workflow(client, contact_id, active_wf)
            if wf_messages:
                for msg in wf_messages:
                    if platform == 'WHATSAPP':
                        MetaWebhookService.send_whatsapp_message(
                            client=client,
                            to_number=contact_id,
                            text_body=msg.get('body', ''),
                            phone_number_id=phone_number_id,
                            buttons=msg.get('buttons'),
                            media_url=msg.get('media_url'),
                            media_type=msg.get('type')
                        )
                    else:
                        MetaWebhookService.send_fb_ig_message(
                            client=client,
                            platform=platform,
                            recipient_id=contact_id,
                            text_body=msg.get('body', ''),
                            buttons=msg.get('buttons'),
                            media_url=msg.get('media_url'),
                            media_type=msg.get('type')
                        )
                return True
            return False

        # Human Handoff
        if incoming_clean in ['human', 'talk to human', 'agent', 'support', 'live agent', '👤 talk to human']:
            ai_session.is_active = False
            ai_session.save()
            ct = Contact.objects.filter(Q(client=client) & (Q(platform_id=contact_id) | Q(phone_number=contact_id))).first()
            if ct:
                ct.bot_paused = True
                ct.save()
            msg = "👤 You are being connected to our human support team. An agent will reply shortly!"
            if platform == 'WHATSAPP':
                MetaWebhookService.send_whatsapp_message(client, contact_id, msg, phone_number_id)
            else:
                MetaWebhookService.send_fb_ig_message(client, platform, contact_id, msg)
            return True

        # 2-Minute Inactivity Timeout Check: Cycle back to Workflow!
        if elapsed > 120:
            ai_session.is_active = False
            ai_session.save()

            from .workflow_service import WorkflowEngine
            from ..repositories.workflow_repository import WorkflowRepository

            wf_messages = WorkflowEngine.process_workflow(client, contact_id, incoming_text, platform)
            if not wf_messages:
                active_wf = WorkflowRepository.filter_workflows(client=client, enabled=True).first()
                if active_wf:
                    wf_messages = WorkflowEngine._start_workflow(client, contact_id, active_wf)

            if wf_messages:
                for msg in wf_messages:
                    if platform == 'WHATSAPP':
                        MetaWebhookService.send_whatsapp_message(
                            client=client,
                            to_number=contact_id,
                            text_body=msg.get('body', ''),
                            phone_number_id=phone_number_id,
                            buttons=msg.get('buttons'),
                            media_url=msg.get('media_url'),
                            media_type=msg.get('type')
                        )
                    else:
                        MetaWebhookService.send_fb_ig_message(
                            client=client,
                            platform=platform,
                            recipient_id=contact_id,
                            text_body=msg.get('body', ''),
                            buttons=msg.get('buttons'),
                            media_url=msg.get('media_url'),
                            media_type=msg.get('type')
                        )
                return True

            return False

        # Active AI Query within 2 minutes: Generate RAG response without buttons!
        ai_session.variables['last_ai_time'] = time.time()
        ai_session.save()

        from .ai_service import get_rag_response, get_ai_response, get_embedding, find_relevant_chunks
        from ..repositories.knowledge_repository import KnowledgeRepository

        ai_reply = None
        chunks = KnowledgeRepository.filter_chunks(client=client).exclude(embedding=[])
        if chunks.exists():
            query_embedding = get_embedding(incoming_text)
            if query_embedding:
                chunks_data = [{
                    'text': c.chunk_text,
                    'embedding': c.embedding,
                    'doc_title': getattr(c.document, 'title', 'Knowledge') if hasattr(c, 'document') and c.document else 'Knowledge'
                } for c in chunks.select_related('document')]
                relevant = find_relevant_chunks(query_embedding, chunks_data, top_k=5)

                if relevant and relevant[0]['score'] > 0.3:
                    ai_reply = get_rag_response(incoming_text, relevant, client_model=client)
                else:
                    ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)
            else:
                ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)
        else:
            ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)

        if not ai_reply:
            ai_reply = f"Thank you for contacting {client.business_name}. How can we assist you with our products or services today?"

        if platform == 'WHATSAPP':
            MetaWebhookService.send_whatsapp_message(
                client=client,
                to_number=contact_id,
                text_body=ai_reply,
                phone_number_id=phone_number_id
            )
        else:
            MetaWebhookService.send_fb_ig_message(
                client=client,
                platform=platform,
                recipient_id=contact_id,
                text_body=ai_reply
            )
        return True

    @staticmethod
    def handle_automations_whatsapp(client, to_number, incoming_text, phone_number_id):
        # Quick safety check: if contact bot is paused, do not proceed
        if client:
            from ..models import Contact
            from django.db.models import Q
            _contact = Contact.objects.filter(Q(client=client) & (Q(platform_id=to_number) | Q(phone_number=to_number))).first()
            if _contact and _contact.bot_paused:
                logger.info(f"Bot paused for WhatsApp contact {to_number}. Bypassing automations.")
                return

        # Check for active Hybrid AI Session or Talk to AI trigger
        if MetaWebhookService.handle_ai_session_check(client, to_number, incoming_text, 'WHATSAPP', phone_number_id):
            return

        # 1st Time Incoming Message check for Greeting Message
        msg_count = MessageRepository.filter_messages(client=client, channel='WHATSAPP', from_address=to_number, message_type='INCOMING').count()
        if (msg_count <= 1 and client.greeting_enabled) or (client.greeting_enabled and client.greeting_message and incoming_text.lower().strip() in ['hi', 'hello', 'hey', 'start']):
            greeting_text = client.greeting_message or f"Hello! Welcome to {client.business_name}. Thank you for contacting us! How can we assist you today?"
            MetaWebhookService.send_whatsapp_message(
                client=client,
                to_number=to_number,
                text_body=greeting_text,
                phone_number_id=phone_number_id,
                buttons=client.greeting_buttons or None
            )

        from .workflow_service import WorkflowEngine
        wf_messages = WorkflowEngine.process_workflow(client, to_number, incoming_text)
        if wf_messages:
            for msg in wf_messages:
                MetaWebhookService.send_whatsapp_message(
                    client=client,
                    to_number=to_number,
                    text_body=msg.get('body', ''),
                    phone_number_id=phone_number_id,
                    buttons=msg.get('buttons'),
                    media_url=msg.get('media_url'),
                    media_type=msg.get('media_type') or ('image' if msg.get('media_url') else None)
                )
            return

        automations = AutomationRepository.filter_automations(client=client, enabled=True, trigger_type='KEYWORD')
        incoming_text_lower = incoming_text.lower().strip()
        
        match_found = False
        for auto in automations:
            auto_channels = auto.channels or []
            if len(auto_channels) > 0 and 'WHATSAPP' not in auto_channels:
                continue

            if auto.keywords:
                for keyword in auto.keywords:
                    kw = keyword.lower().strip()
                    if kw in ['*', 'all', 'any', 'anything'] or (kw and (kw == incoming_text_lower or kw in incoming_text_lower)):
                        MetaWebhookService.send_whatsapp_message(client, to_number, auto.response, phone_number_id, auto.buttons)
                        match_found = True
                        break
        incoming_lower = incoming_text.lower().strip()

        # Automated Industrial Lead Qualification (Product & Pricing Intent Detection)
        from .lead_qualification_service import LeadQualificationService
        qualification = LeadQualificationService.qualify_and_update_contact(client, to_number, incoming_text)
        if qualification and qualification.get('matched_product') and qualification.get('intent') == 'PRICING':
            pricing_reply = LeadQualificationService.generate_pricing_reply(client, qualification['matched_product'])
            if pricing_reply:
                MetaWebhookService.send_whatsapp_message(client, to_number, pricing_reply, phone_number_id)
                return

        # Check for Buy Now action
        buy_keywords = ['buy now', '🛒 buy now', 'order now', 'buy product', 'purchase']
        if any(kw in incoming_lower for kw in buy_keywords):
            MetaWebhookService.handle_buy_now(client, to_number, 'WHATSAPP', phone_number_id)
            return

        # Check for Product Catalog queries
        catalog_keywords = ['product', 'products', 'catalog', 'browse products', 'shop', 'items', 'store', 'samaan']
        if any(kw in incoming_lower for kw in catalog_keywords):
            MetaWebhookService.send_catalog_products(client, to_number, 'WHATSAPP', phone_number_id)
            return

        # Check for address / location queries
        address_keywords = ['address', 'location', 'path', 'map', 'directions', 'dukaan', 'shop location', 'kaha par', 'kaha h', 'where are you located']
        if client.address and any(kw in incoming_lower for kw in address_keywords):
            import urllib.parse
            encoded_addr = urllib.parse.quote(client.address)
            maps_link = f"https://www.google.com/maps/dir/?api=1&destination={encoded_addr}"
            loc_msg = f"📍 *{client.business_name} Address & Location*:\n\n🏢 *Address*: {client.address}\n\n🗺️ *Get Directions / Map Path*:\n{maps_link}"
            MetaWebhookService.send_whatsapp_message(client, to_number, loc_msg, phone_number_id)
            return

        if not match_found and client.ai_enabled:
            ai_reply = None
            chunks = KnowledgeRepository.filter_chunks(client=client).exclude(embedding=[])
            if chunks.exists():
                query_embedding = get_embedding(incoming_text)
                if query_embedding:
                    chunks_data = [{
                        'text': c.chunk_text,
                        'embedding': c.embedding,
                        'doc_title': c.document.title
                    } for c in chunks.select_related('document')]
                    relevant = find_relevant_chunks(query_embedding, chunks_data, top_k=5)
                    
                    if relevant and relevant[0]['score'] > 0.3:
                        ai_reply = get_rag_response(incoming_text, relevant, client_model=client)
                    else:
                        ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)
                else:
                    ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)
            else:
                ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)

            if ai_reply:
                MetaWebhookService.send_whatsapp_message(client, to_number, ai_reply, phone_number_id)
                match_found = True

        if not match_found and client.greeting_enabled:
            greeting_text = client.greeting_message or f"Hello! Welcome to {client.business_name}. Thank you for contacting us! How can we assist you today?"
            MetaWebhookService.send_whatsapp_message(client, to_number, greeting_text, phone_number_id, client.greeting_buttons or None)

    @staticmethod
    def handle_automations_fb_ig(client, platform, sender_id, incoming_text):
        # Quick safety check: if contact bot is paused, do not proceed
        if client:
            from ..models import Contact
            _contact = Contact.objects.filter(client=client, platform_id=sender_id).first()
            if _contact and _contact.bot_paused:
                logger.info(f"Bot paused for {platform} contact {sender_id}. Bypassing automations.")
                return

        # Check for active Hybrid AI Session or Talk to AI trigger
        if MetaWebhookService.handle_ai_session_check(client, sender_id, incoming_text, platform):
            return

        msg_count = MessageRepository.filter_messages(client=client, channel=platform, from_address=sender_id, message_type='INCOMING').count()
        if (msg_count <= 1 and client.greeting_enabled) or (client.greeting_enabled and client.greeting_message and incoming_text.lower().strip() in ['hi', 'hello', 'hey', 'start']):
            greeting_text = client.greeting_message or f"Hello! Welcome to {client.business_name}. Thank you for contacting us! How can we assist you today?"
            MetaWebhookService.send_fb_ig_message(
                client=client,
                platform=platform,
                recipient_id=sender_id,
                text_body=greeting_text,
                buttons=client.greeting_buttons or None
            )

        from .workflow_service import WorkflowEngine
        wf_messages = WorkflowEngine.process_workflow(client, sender_id, incoming_text, platform)
        if wf_messages:
            for msg in wf_messages:
                MetaWebhookService.send_fb_ig_message(
                    client=client,
                    platform=platform,
                    recipient_id=sender_id,
                    text_body=msg.get('body', ''),
                    buttons=msg.get('buttons'),
                    media_url=msg.get('media_url'),
                    media_type=msg.get('media_type') or ('image' if msg.get('media_url') else None)
                )
            return

        automations = AutomationRepository.filter_automations(client=client, enabled=True, trigger_type='KEYWORD')
        incoming_text_lower = incoming_text.lower().strip()
        
        match_found = False
        for auto in automations:
            auto_channels = auto.channels or []
            if len(auto_channels) > 0 and platform not in auto_channels:
                continue
            if len(auto_channels) == 0 and platform != 'WHATSAPP':
                continue

            if auto.keywords:
                for keyword in auto.keywords:
                    kw = keyword.lower().strip()
                    if kw in ['*', 'all', 'any', 'anything'] or (kw and (kw == incoming_text_lower or kw in incoming_text_lower)):
                        MetaWebhookService.send_fb_ig_message(client, platform, sender_id, auto.response, auto.buttons)
                        match_found = True
                        break
        incoming_lower = incoming_text.lower().strip()

        # Automated Industrial Lead Qualification (Product & Pricing Intent Detection)
        from .lead_qualification_service import LeadQualificationService
        qualification = LeadQualificationService.qualify_and_update_contact(client, sender_id, incoming_text)
        if qualification and qualification.get('matched_product') and qualification.get('intent') == 'PRICING':
            pricing_reply = LeadQualificationService.generate_pricing_reply(client, qualification['matched_product'])
            if pricing_reply:
                MetaWebhookService.send_fb_ig_message(client, platform, sender_id, pricing_reply)
                return

        # Check for Buy Now action
        buy_keywords = ['buy now', '🛒 buy now', 'order now', 'buy product', 'purchase']
        if any(kw in incoming_lower for kw in buy_keywords):
            MetaWebhookService.handle_buy_now(client, sender_id, platform)
            return

        # Check for Product Catalog queries
        catalog_keywords = ['product', 'products', 'catalog', 'browse products', 'shop', 'items', 'store', 'samaan']
        if any(kw in incoming_lower for kw in catalog_keywords):
            MetaWebhookService.send_catalog_products(client, sender_id, platform)
            return

        # Check for address / location queries
        address_keywords = ['address', 'location', 'path', 'map', 'directions', 'dukaan', 'shop location', 'kaha par', 'kaha h', 'where are you located']
        if client.address and any(kw in incoming_lower for kw in address_keywords):
            import urllib.parse
            encoded_addr = urllib.parse.quote(client.address)
            maps_link = f"https://www.google.com/maps/dir/?api=1&destination={encoded_addr}"
            loc_msg = f"📍 {client.business_name} Address & Location:\n\n🏢 Address: {client.address}\n\n🗺️ Get Directions / Map Path:\n{maps_link}"
            MetaWebhookService.send_fb_ig_message(client, platform, sender_id, loc_msg)
            return

        if not match_found and client.ai_enabled:
            ai_reply = None
            chunks = KnowledgeRepository.filter_chunks(client=client).exclude(embedding=[])
            if chunks.exists():
                query_embedding = get_embedding(incoming_text)
                if query_embedding:
                    chunks_data = [{
                        'text': c.chunk_text,
                        'embedding': c.embedding,
                        'doc_title': c.document.title
                    } for c in chunks.select_related('document')]
                    relevant = find_relevant_chunks(query_embedding, chunks_data, top_k=5)
                    if relevant and relevant[0]['score'] > 0.3:
                        ai_reply = get_rag_response(incoming_text, relevant, client_model=client)
            
            if not ai_reply:
                ai_reply = get_ai_response(incoming_text, client.ai_context or "", client_model=client)
                
            if ai_reply:
                MetaWebhookService.send_fb_ig_message(client, platform, sender_id, ai_reply)
                match_found = True

        if not match_found and client.greeting_enabled:
            greeting_text = client.greeting_message or f"Hello! Welcome to {client.business_name}. Thank you for contacting us! How can we assist you today?"
            MetaWebhookService.send_fb_ig_message(client, platform, sender_id, greeting_text, client.greeting_buttons or None)

    @staticmethod
    def send_whatsapp_message(client, to_number, text_body, phone_number_id=None, buttons=None, media_url=None, media_type=None):
        import re
        if not phone_number_id:
            phone_number_id = getattr(client, 'whatsapp_phone_number_id', None) or '100000000000000'
        raw_to = str(to_number or '').strip()
        clean_num = re.sub(r'\D', '', raw_to)
        if len(clean_num) == 10:
            clean_num = '91' + clean_num
        formatted_to = clean_num or raw_to

        if text_body:
            frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
            text_body = text_body.replace('{{calendar_link}}', f"{frontend_url}/book/{client.id}")
            
        url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v19.0')}/{phone_number_id}/messages"
        token = client.whatsapp_access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Upgrade media_url to https if needed (Meta requires https for remote media)
        if media_url and isinstance(media_url, str):
            media_url = media_url.strip()
            if media_url.startswith('http://') and not ('127.0.0.1' in media_url or 'localhost' in media_url):
                media_url = 'https://' + media_url[7:]

        # Determine valid WhatsApp media type: 'image', 'video', or 'document'
        m_type = 'video' if any(ext in str(media_url or '').lower() for ext in ['.mp4', '.mov', '.avi']) else 'image'
        if media_type in ['image', 'video', 'document']:
            m_type = media_type

        if media_url and buttons and len(buttons) > 0:
            buttons_payload = []
            for i, btn_text in enumerate(buttons[:3]):
                buttons_payload.append({
                    "type": "reply",
                    "reply": {
                        "id": f"btn_{i}",
                        "title": btn_text[:20]
                    }
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "header": {
                        "type": m_type,
                        m_type: {
                            "link": media_url
                        }
                    },
                    "body": {"text": text_body or "Select an option:"},
                    "action": {"buttons": buttons_payload}
                }
            }
        elif media_url:
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_to,
                "type": m_type,
                m_type: {
                    "link": media_url
                }
            }
            if text_body:
                payload[m_type]["caption"] = text_body
        elif buttons and len(buttons) > 0:
            buttons_payload = []
            for i, btn_text in enumerate(buttons[:3]):
                buttons_payload.append({
                    "type": "reply",
                    "reply": {
                        "id": f"btn_{i}",
                        "title": btn_text[:20]
                    }
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text_body or "Select an option:"},
                    "action": {"buttons": buttons_payload}
                }
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_to,
                "type": "text",
                "text": {"body": text_body}
            }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            res_data = response.json()
            print(f"WhatsApp API Response: {res_data}")

            # If interactive message with media header was rejected by Meta (e.g., media host issue), retry without header
            if response.status_code != 200 and 'interactive' in payload and 'header' in payload.get('interactive', {}):
                print("[WARNING] Interactive message with media header failed. Retrying without media header...")
                fallback_payload = {
                    "messaging_product": "whatsapp",
                    "to": formatted_to,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": payload['interactive']['body'],
                        "action": payload['interactive']['action']
                    }
                }
                fb_res = requests.post(url, headers=headers, json=fallback_payload, timeout=10)
                if fb_res.status_code == 200:
                    response = fb_res
                    res_data = fb_res.json()
                    payload = fallback_payload

            return MessageRepository.create_message(
                client=client,
                channel='WHATSAPP',
                from_address=phone_number_id or 'WHATSAPP_SYSTEM',
                to_address=raw_to,
                body=text_body or f"[{media_type or 'Media'} Message]",
                message_type='OUTGOING',
                whatsapp_message_id=res_data.get('messages', [{}])[0].get('id') if 'messages' in res_data else None,
                status='SENT' if response.status_code == 200 else 'FAILED',
                metadata={"payload": payload, "response": res_data}
            )
        except Exception as e:
            print(f"Failed to send WhatsApp message: {str(e)}")
            try:
                return MessageRepository.create_message(
                    client=client,
                    channel='WHATSAPP',
                    from_address=phone_number_id or 'WHATSAPP_SYSTEM',
                    to_address=raw_to,
                    body=text_body or '[Message]',
                    message_type='OUTGOING',
                    status='SENT',
                    metadata={"error": str(e)}
                )
            except Exception:
                pass
            return None

    @staticmethod
    def mark_whatsapp_message_as_read(client, wamid, phone_number_id=None):
        """Mark an incoming WhatsApp message as read via Meta Graph API so customer sees blue double ticks."""
        if not wamid or not client or not client.whatsapp_access_token:
            return
        phone_id = phone_number_id or getattr(client, 'whatsapp_phone_number_id', None)
        if not phone_id:
            return
        url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v19.0')}/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {client.whatsapp_access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wamid
        }
        try:
            requests.post(url, headers=headers, json=payload, timeout=5)
        except Exception as _e:
            logger.warning(f"Error marking WhatsApp message as read: {_e}")

    @staticmethod
    def send_fb_ig_message(client, platform, recipient_id, text_body, buttons=None, media_url=None, media_type=None):
        if text_body:
            frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
            text_body = text_body.replace('{{calendar_link}}', f"{frontend_url}/book/{client.id}")
            
        config = client.facebook_config if platform == 'FACEBOOK' else (client.instagram_config or {})
        access_token = config.get('access_token') or (client.facebook_config or {}).get('access_token') or client.whatsapp_access_token
        
        if not access_token:
            print(f"No access token found for {platform} messaging")
            return
            
        if access_token.startswith('IG'):
            url = "https://graph.instagram.com/v20.0/me/messages"
        elif platform == 'INSTAGRAM':
            ig_id = (client.instagram_config or {}).get('instagram_business_id') or (client.facebook_config or {}).get('instagram_business_id') or '17841443390895451'
            url = f"https://graph.facebook.com/v20.0/{ig_id}/messages"
        else:
            url = "https://graph.facebook.com/v20.0/me/messages"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        message_payload = {}
        if media_url:
            m_type = media_type or 'image'
            if not media_type:
                m_type = 'video' if any(ext in media_url.lower() for ext in ['.mp4', '.mov', '.avi']) else 'image'
            message_payload = {
                "attachment": {
                    "type": m_type,
                    "payload": {
                        "url": media_url,
                        "is_reusable": True
                    }
                }
            }
        elif buttons and len(buttons) > 0:
            quick_replies = []
            for btn in buttons[:13]:
                quick_replies.append({
                    "content_type": "text",
                    "title": btn[:20],
                    "payload": btn
                })
            message_payload = {
                "text": text_body or "Please choose an option:",
                "quick_replies": quick_replies
            }
        else:
            message_payload = {
                "text": text_body
            }
            
        payload = {
            "recipient": {"id": recipient_id},
            "message": message_payload
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers)
            print(f"{platform} Send Response:", res.status_code, res.text)
            if res.status_code != 200:
                fallback_url = "https://graph.instagram.com/v20.0/me/messages" if access_token.startswith('IG') else "https://graph.facebook.com/v20.0/me/messages"
                res_fb = requests.post(fallback_url, json=payload, headers=headers)
                print(f"{platform} Fallback Send Response:", res_fb.status_code, res_fb.text)
            
            return MessageRepository.create_message(
                client=client,
                channel=platform,
                from_address='SYSTEM',
                to_address=recipient_id,
                body=text_body or f"[{media_type or 'Attachment'}]",
                message_type='OUTGOING',
                status='SENT'
            )
        except Exception as e:
            print(f"Failed to send {platform} message:", str(e))
            return None

    @staticmethod
    def send_catalog_products(client, recipient_id, platform='WHATSAPP', phone_number_id=None):
        from ..repositories.product_repository import ProductRepository
        products = ProductRepository.filter_products(client=client, in_stock=True)[:5]
        if not products:
            msg = "🛍️ Our product catalog is currently empty. Please check back soon!"
            if platform == 'WHATSAPP':
                MetaWebhookService.send_whatsapp_message(client, recipient_id, msg, phone_number_id)
            else:
                MetaWebhookService.send_fb_ig_message(client, platform, recipient_id, msg)
            return

        msg_body = f"🛍️ *{client.business_name} Product Catalog*:\n\n"
        first_product_image = None

        base_url = os.getenv('BACKEND_URL') or os.getenv('FRONTEND_URL') or 'https://uwoconnect.aisa24.com'
        base_url = base_url.rstrip('/')

        for p in products:
            if not first_product_image and getattr(p, 'image_url', None):
                first_product_image = p.image_url

            price_str = f"${p.price}" if p.price else "Contact for Price"
            msg_body += f"📦 *{p.name}* - {price_str}\n"
            if p.description:
                msg_body += f"  _{p.description}_\n"
            if getattr(p, 'product_url', None) or p.id:
                cta = getattr(p, 'cta_text', 'View Product') or 'View Product'
                tracking_url = f"{base_url}/api/products/{p.id}/redirect_link/"
                msg_body += f"  🔗 [{cta}]: {tracking_url}\n"
            msg_body += "\n"

        msg_body += "👉 Click a product link above or reply to order!"
        buttons = ["🛒 Buy Now", "💬 Talk to Support"]

        if platform == 'WHATSAPP':
            MetaWebhookService.send_whatsapp_message(
                client=client,
                to_number=recipient_id,
                text_body=msg_body,
                phone_number_id=phone_number_id,
                buttons=buttons,
                media_url=first_product_image,
                media_type='image'
            )
        else:
            MetaWebhookService.send_fb_ig_message(client, platform, recipient_id, msg_body, buttons)

    @staticmethod
    def handle_buy_now(client, recipient_id, platform='WHATSAPP', phone_number_id=None):
        from ..repositories.product_repository import ProductRepository
        from ..repositories.contact_repository import ContactRepository
        from ..repositories.order_repository import OrderRepository

        products = ProductRepository.filter_products(client=client, in_stock=True)
        if not products:
            msg = "No products available for order right now."
            if platform == 'WHATSAPP':
                MetaWebhookService.send_whatsapp_message(client, recipient_id, msg, phone_number_id)
            else:
                MetaWebhookService.send_fb_ig_message(client, platform, recipient_id, msg)
            return

        product = products[0]
        contact = ContactRepository.filter_contacts(client=client, platform_id=recipient_id).first()
        if not contact:
            contact = ContactRepository.create_contact(client=client, platform_id=recipient_id, name=f"Customer ({recipient_id})")

        order = OrderRepository.create_order(
            client=client,
            contact=contact,
            items=[{
                "product_id": str(product.id),
                "name": product.name,
                "price": float(product.price or 0),
                "quantity": 1
            }],
            total_amount=product.price or 0,
            payment_status='PENDING'
        )

        msg_body = f"✅ *Order Created Successfully!*\n\n📋 *Order ID*: #{order.id}\n📦 *Item*: {product.name}\n💰 *Total Amount*: ${product.price}\n💳 *Status*: PENDING\n\nThank you for shopping with {client.business_name}! Our team will contact you shortly to complete payment & delivery."
        
        if platform == 'WHATSAPP':
            MetaWebhookService.send_whatsapp_message(client, recipient_id, msg_body, phone_number_id)
        else:
            MetaWebhookService.send_fb_ig_message(client, platform, recipient_id, msg_body)
