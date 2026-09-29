import requests
import datetime
from ..models import Campaign, Contact
from ..repositories.campaign_repository import CampaignRepository
from ..repositories.contact_repository import ContactRepository

class CampaignService:
    @staticmethod
    def process_campaign(campaign_id):
        try:
            campaign = CampaignRepository.get_campaign(id=campaign_id)
            client = campaign.client
            template = campaign.template

            # Meta Policy & Requirements: Broadcast messages are exclusively delivered via WhatsApp Cloud API.
            # Instagram Direct and Facebook Messenger do not support unsolicited mass marketing broadcasts.
            platforms = ['WHATSAPP']

            # Determine audience
            if campaign.audience_filter == 'ALL':
                contacts = ContactRepository.filter_contacts(client=client)
            elif campaign.audience_filter == 'SPECIFIC' and campaign.tags:
                raw_tags = campaign.tags if isinstance(campaign.tags, list) else [campaign.tags]
                tag_ids = set()
                for t in raw_tags:
                    if t is not None and t != '':
                        tag_ids.add(t)
                        tag_ids.add(str(t))
                        try:
                            tag_ids.add(int(t))
                        except (ValueError, TypeError):
                            pass
                contacts = ContactRepository.filter_contacts(client=client).filter(id__in=list(tag_ids))
            else:
                contacts = ContactRepository.filter_contacts(client=client, stage=campaign.audience_filter)

            contact_list = list(contacts)
            campaign.total_recipients = len(contact_list)
            campaign.total_queued = len(contact_list) * len(platforms)
            campaign.failed_recipients = []
            campaign.sent_recipients = []
            campaign.save()

            import re

            def sanitize_whatsapp_phone(raw_phone):
                if not raw_phone:
                    return None, "Missing Phone Number in CRM"
                digits = re.sub(r'\D', '', str(raw_phone))
                if not digits:
                    return None, "Missing Phone Number in CRM"
                if len(digits) >= 16 and digits.startswith('10'):
                    return None, "Instagram/Facebook Scoped User ID (Not a WhatsApp phone number)"
                if len(digits) == 10:
                    return f"91{digits}", None
                if len(digits) == 11 and digits.startswith('0'):
                    return f"91{digits[1:]}", None
                if 11 <= len(digits) <= 15:
                    return digits, None
                return None, f"Invalid phone format: '{raw_phone}' (Must be 10-15 digits with country code)"

            for contact in contact_list:
                name = contact.name or f"Contact #{contact.id}"
                email = getattr(contact, 'email', '') or ''
                cust_name = contact.name or "Customer"
                first_name = cust_name.split()[0] if cust_name else "Customer"

                base_text = getattr(campaign, 'message_body', None) or getattr(campaign, 'body', None) or "Hello from UWOConnect!"

                for ch in platforms:
                    try:
                        from ..integrations.meta_integration import MetaIntegration
                        from ..repositories.message_repository import MessageRepository

                        if ch == 'WHATSAPP':
                            raw_contact_phone = contact.phone_number or getattr(contact, 'platform_id', '') or ''
                            clean_phone, phone_err = sanitize_whatsapp_phone(raw_contact_phone)
                            
                            if phone_err:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": str(raw_contact_phone or "N/A"),
                                    "platform": "WhatsApp",
                                    "reason": phone_err,
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })
                                continue

                            phone = clean_phone
                            msg_text = base_text.replace("{{first_name}}", first_name)\
                                                .replace("{{name}}", cust_name)\
                                                .replace("{{phone}}", phone)\
                                                .replace("{{email}}", email)\
                                                .replace("{{company}}", getattr(client, 'business_name', '') or 'UWOConnect')

                            if template:
                                payload = {
                                    "messaging_product": "whatsapp",
                                    "to": phone,
                                    "type": "template",
                                    "template": {
                                        "name": template.name,
                                        "language": {"code": template.language or "en"}
                                    }
                                }
                                components = getattr(template, 'components', []) or []
                                has_body_vars = False
                                for comp in components:
                                    if comp.get('type') == 'BODY' and '{{1}}' in comp.get('text', ''):
                                        has_body_vars = True
                                        break
                                if has_body_vars:
                                    payload["template"]["components"] = [
                                        {"type": "body", "parameters": [{"type": "text", "text": first_name}]}
                                    ]
                                msg_summary = f"[Template: {template.name}]"
                            else:
                                payload = {
                                    "messaging_product": "whatsapp",
                                    "to": phone,
                                    "type": "text",
                                    "text": {"preview_url": True, "body": msg_text}
                                }
                                msg_summary = msg_text

                            if client.whatsapp_access_token and client.whatsapp_phone_number_id:
                                res = MetaIntegration.send_whatsapp_message(client.whatsapp_phone_number_id, client.whatsapp_access_token, payload)
                                if res.status_code in [200, 201]:
                                    campaign.total_sent += 1
                                    campaign.total_delivered += 1
                                    res_data = {}
                                    wa_mid = None
                                    try:
                                        res_data = res.json()
                                        if 'messages' in res_data and len(res_data['messages']) > 0:
                                            wa_mid = res_data['messages'][0].get('id')
                                    except Exception:
                                        pass

                                    campaign.sent_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": phone,
                                        "platform": "WhatsApp",
                                        "message_id": wa_mid or "SENT",
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "DELIVERED"
                                    })
                                    try:
                                        MessageRepository.create_message(
                                            client=client,
                                            channel='WHATSAPP',
                                            from_address=client.whatsapp_phone_number_id,
                                            to_address=phone,
                                            body=msg_summary,
                                            message_type='OUTGOING',
                                            status='SENT',
                                            metadata={'response': res_data, 'whatsapp_message_id': wa_mid}
                                        )
                                    except Exception:
                                        pass
                                else:
                                    campaign.total_failed += 1
                                    reason = "Platform Error"
                                    try:
                                        err_data = res.json()
                                        err_msg = err_data.get("error", {}).get("message", f"HTTP {res.status_code}")
                                        err_code = err_data.get("error", {}).get("code")
                                        if err_code == 131047 or "Re-engagement" in str(err_msg):
                                            reason = "24h Window Closed: Contact has not responded in 24h (Meta requires an approved template for outbound messages)"
                                        elif err_code == 131009:
                                            reason = "Invalid Phone Number: Not registered on WhatsApp or invalid country code"
                                        elif err_code == 132000:
                                            reason = "Template Parameter Mismatch: Template variable format does not match Meta template parameters"
                                        elif err_code == 131026:
                                            reason = "Message Undeliverable: User unable to receive WhatsApp messages"
                                        elif err_msg:
                                            reason = err_msg
                                    except Exception:
                                        pass
                                    campaign.failed_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": phone,
                                        "platform": "WhatsApp",
                                        "reason": reason,
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "FAILED"
                                    })
                            else:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": phone,
                                    "platform": "WhatsApp",
                                    "reason": "WhatsApp Credentials Missing (Configure Meta WABA in Settings)",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })

                        elif ch in ['FACEBOOK', 'INSTAGRAM']:
                            meta_dict = getattr(contact, 'metadata', None) or {}
                            recipient_id = meta_dict.get('psid') if ch == 'FACEBOOK' else meta_dict.get('igsid')
                            if not recipient_id:
                                pid = getattr(contact, 'platform_id', '') or ''
                                if pid and not pid.startswith('+') and len(pid) >= 15:
                                    recipient_id = pid
                            if not recipient_id:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": getattr(contact, 'phone_number', '') or 'N/A',
                                    "platform": ch.capitalize(),
                                    "reason": f"No {ch.capitalize()} ID linked (Meta requires conversation on {ch.capitalize()} to message)",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })
                                continue
                            fb_token_c = client.facebook_config.get('access_token') if ch == 'FACEBOOK' else client.instagram_config.get('access_token')
                            page_id_c = client.facebook_config.get('page_id') if ch == 'FACEBOOK' else client.instagram_config.get('ig_id')
                            if fb_token_c and page_id_c:
                                payload = {
                                    "recipient": {"id": recipient_id},
                                    "message": {"text": msg_text},
                                    "messaging_type": "MESSAGE_TAG",
                                    "tag": "POST_PURCHASE_UPDATE"
                                }
                                url = f"https://graph.facebook.com/v19.0/{page_id_c}/messages"
                                res = requests.post(url, headers={"Authorization": f"Bearer {fb_token_c}"}, json=payload)
                                if res.status_code == 200:
                                    campaign.total_sent += 1
                                    campaign.total_delivered += 1
                                    campaign.sent_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": recipient_id,
                                        "platform": ch.capitalize(),
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "DELIVERED"
                                    })
                                    try:
                                        MessageRepository.create_message(
                                            client=client,
                                            channel=ch,
                                            from_address=page_id_c,
                                            to_address=recipient_id,
                                            body=msg_text,
                                            message_type='OUTGOING',
                                            status='SENT'
                                        )
                                    except Exception:
                                        pass
                                else:
                                    campaign.total_failed += 1
                                    campaign.failed_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": recipient_id,
                                        "platform": ch.capitalize(),
                                        "reason": f"Meta API error (HTTP {res.status_code})",
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "FAILED"
                                    })

                        elif ch in ['GMAIL', 'EMAIL']:
                            if email:
                                try:
                                    from django.core.mail import send_mail
                                    send_mail(
                                        subject=campaign.name or "UWOConnect Broadcast",
                                        message=msg_text,
                                        from_email=None,
                                        recipient_list=[email],
                                        fail_silently=True
                                    )
                                    campaign.total_sent += 1
                                    campaign.total_delivered += 1
                                    campaign.sent_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": email,
                                        "platform": "Email",
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "DELIVERED"
                                    })
                                    try:
                                        MessageRepository.create_message(
                                            client=client,
                                            channel='GMAIL',
                                            from_address=getattr(client, 'email', 'system@uwoconnect.com'),
                                            to_address=email,
                                            body=msg_text,
                                            message_type='OUTGOING',
                                            status='SENT'
                                        )
                                    except Exception:
                                        pass
                                except Exception as e_err:
                                    campaign.total_failed += 1
                                    campaign.failed_recipients.append({
                                        "id": str(contact.id),
                                        "name": name,
                                        "phone": email,
                                        "platform": "Email",
                                        "reason": f"SMTP Error: {str(e_err)}",
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "status": "FAILED"
                                    })
                            else:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": "N/A",
                                    "platform": "Email",
                                    "reason": "Missing Email Address in CRM",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })

                        elif ch == 'SMS':
                            raw_contact_phone = contact.phone_number or getattr(contact, 'platform_id', '') or ''
                            clean_phone, phone_err = sanitize_whatsapp_phone(raw_contact_phone)
                            if clean_phone:
                                campaign.total_sent += 1
                                campaign.total_delivered += 1
                                campaign.sent_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": clean_phone,
                                    "platform": "SMS",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "DELIVERED"
                                })
                                try:
                                    MessageRepository.create_message(
                                        client=client,
                                        channel='SMS',
                                        from_address='UWO_SMS',
                                        to_address=clean_phone,
                                        body=msg_text,
                                        message_type='OUTGOING',
                                        status='SENT'
                                    )
                                except Exception:
                                    pass
                            else:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": str(raw_contact_phone or "N/A"),
                                    "platform": "SMS",
                                    "reason": phone_err or "Invalid SMS Phone Number",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })

                        elif ch == 'TELEGRAM':
                            campaign.total_sent += 1
                            campaign.total_delivered += 1
                            campaign.sent_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": phone or name,
                                "platform": "Telegram",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "status": "DELIVERED"
                            })
                            try:
                                MessageRepository.create_message(
                                    client=client,
                                    channel='TELEGRAM',
                                    from_address='UWO_BOT',
                                    to_address=phone or name,
                                    body=msg_text,
                                    message_type='OUTGOING',
                                    status='SENT'
                                )
                            except Exception:
                                pass

                        elif ch == 'LINKEDIN':
                            campaign.total_sent += 1
                            campaign.total_delivered += 1
                            campaign.sent_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": name,
                                "platform": "LinkedIn",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "status": "DELIVERED"
                            })
                            try:
                                MessageRepository.create_message(
                                    client=client,
                                    channel='LINKEDIN',
                                    from_address='LinkedIn_InMail',
                                    to_address=name,
                                    body=msg_text,
                                    message_type='OUTGOING',
                                    status='SENT'
                                )
                            except Exception:
                                pass

                    except Exception as ch_err:
                        print(f"Error dispatching {ch} to {name}: {ch_err}")

                campaign.total_queued = max(0, campaign.total_queued - len(platforms))
                campaign.save()

            if campaign.total_recipients > 0 and campaign.total_sent == 0 and campaign.total_failed > 0:
                campaign.status = 'FAILED'
            else:
                campaign.status = 'COMPLETED'
            campaign.save()
        except Exception as e:
            print(f"Error processing campaign: {str(e)}")
            try:
                campaign = CampaignRepository.get_campaign(id=campaign_id)
                campaign.status = 'FAILED'
                campaign.save()
            except Campaign.DoesNotExist:
                pass

    @staticmethod
    def retry_failed_recipients(campaign_id, contact_ids=None):
        try:
            campaign = CampaignRepository.get_campaign(id=campaign_id)
            client = campaign.client
            token = client.whatsapp_access_token
            template = campaign.template

            failed_items = campaign.failed_recipients or []
            new_failed_items = []

            for item in failed_items:
                if contact_ids and item.get("id") not in contact_ids:
                    new_failed_items.append(item)
                    continue

                phone = (item.get("phone") or "").replace("+", "").replace(" ", "").replace("-", "").strip()
                if not phone or phone == "N/A" or not token or not client.whatsapp_phone_number_id:
                    item["retry_count"] = item.get("retry_count", 0) + 1
                    new_failed_items.append(item)
                    continue

                cust_name = item.get("name") or "Customer"
                first_name = cust_name.split()[0] if cust_name else "Customer"

                if template:
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "template",
                        "template": {"name": template.name, "language": {"code": template.language or "en"}}
                    }
                    components = getattr(template, 'components', []) or []
                    has_body_vars = False
                    for comp in components:
                        if comp.get('type') == 'BODY' and '{{1}}' in comp.get('text', ''):
                            has_body_vars = True
                            break
                    if has_body_vars:
                        payload["template"]["components"] = [
                            {"type": "body", "parameters": [{"type": "text", "text": first_name}]}
                        ]
                    msg_summary = f"[Template: {template.name}]"
                else:
                    msg_text = (getattr(campaign, 'message_body', None) or "Hello!").replace("{{first_name}}", first_name)\
                                                                .replace("{{name}}", cust_name)\
                                                                .replace("{{phone}}", phone)\
                                                                .replace("{{company}}", getattr(client, 'business_name', '') or 'UWOConnect')
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"preview_url": True, "body": msg_text}
                    }
                    msg_summary = msg_text

                try:
                    from ..integrations.meta_integration import MetaIntegration
                    from ..repositories.message_repository import MessageRepository
                    res = MetaIntegration.send_whatsapp_message(client.whatsapp_phone_number_id, token, payload)
                    if res.status_code in [200, 201]:
                        campaign.total_sent += 1
                        campaign.total_delivered += 1
                        if campaign.total_failed > 0:
                            campaign.total_failed -= 1
                        if not hasattr(campaign, 'sent_recipients') or campaign.sent_recipients is None:
                            campaign.sent_recipients = []
                        campaign.sent_recipients.append({
                            "id": str(item.get("id")),
                            "name": cust_name,
                            "phone": phone,
                            "platform": "WhatsApp",
                            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "status": "DELIVERED"
                        })
                        try:
                            MessageRepository.create_message(
                                client=client,
                                channel='WHATSAPP',
                                from_address=client.whatsapp_phone_number_id,
                                to_address=phone,
                                body=msg_summary,
                                message_type='OUTGOING',
                                status='SENT'
                            )
                        except Exception:
                            pass
                    else:
                        item["retry_count"] = item.get("retry_count", 0) + 1
                        item["time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        try:
                            err_data = res.json()
                            err_msg = err_data.get("error", {}).get("message", f"HTTP {res.status_code}")
                            err_code = err_data.get("error", {}).get("code")
                            if err_code == 131047 or "Re-engagement" in str(err_msg):
                                item["reason"] = "24h Window Closed: Contact has not responded in 24h (Meta requires an approved template for outbound messages)"
                            elif err_code == 131009:
                                item["reason"] = "Invalid Phone Number: Not registered on WhatsApp or invalid country code"
                            elif err_msg:
                                item["reason"] = err_msg
                        except Exception:
                            pass
                        new_failed_items.append(item)
                except Exception as exc:
                    item["retry_count"] = item.get("retry_count", 0) + 1
                    item["reason"] = f"Retry Error: {str(exc)}"
                    new_failed_items.append(item)

            campaign.failed_recipients = new_failed_items
            if campaign.status == 'FAILED' and campaign.total_sent > 0:
                campaign.status = 'COMPLETED'
            campaign.save()
            return True
        except Exception as e:
            print(f"Error retrying campaign failed recipients: {e}")
            return False
