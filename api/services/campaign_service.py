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
            campaign.save()

            for contact in contact_list:
                name = contact.name or f"Contact #{contact.id}"
                phone = (contact.phone_number or "").replace("+", "").replace(" ", "").replace("-", "").strip()
                email = getattr(contact, 'email', '') or ''
                cust_name = contact.name or "Customer"
                first_name = cust_name.split()[0] if cust_name else "Customer"

                base_text = getattr(campaign, 'message_body', None) or getattr(campaign, 'body', None) or "Hello from UWOConnect!"
                msg_text = base_text.replace("{{first_name}}", first_name)\
                                    .replace("{{name}}", cust_name)\
                                    .replace("{{phone}}", phone)\
                                    .replace("{{email}}", email)\
                                    .replace("{{company}}", getattr(client, 'business_name', '') or 'UWOConnect')

                for ch in platforms:
                    try:
                        from ..integrations.meta_integration import MetaIntegration
                        from ..repositories.message_repository import MessageRepository

                        if ch == 'WHATSAPP':
                            if not phone:
                                campaign.total_failed += 1
                                campaign.failed_recipients.append({
                                    "id": str(contact.id),
                                    "name": name,
                                    "phone": "N/A",
                                    "platform": "WhatsApp",
                                    "reason": "Missing Phone Number",
                                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "status": "FAILED"
                                })
                                continue

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
                                    campaign.total_failed += 1
                                    reason = "Platform Error"
                                    try:
                                        err_data = res.json()
                                        reason = err_data.get("error", {}).get("message", f"HTTP {res.status_code}")
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
                                    "reason": "WhatsApp Credentials Missing",
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
                                    "phone": phone,
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
                                    print(f"Error sending email to {email}: {e_err}")

                        elif ch == 'SMS':
                            if phone:
                                campaign.total_sent += 1
                                campaign.total_delivered += 1
                                try:
                                    MessageRepository.create_message(
                                        client=client,
                                        channel='SMS',
                                        from_address='UWO_SMS',
                                        to_address=phone,
                                        body=msg_text,
                                        message_type='OUTGOING',
                                        status='SENT'
                                    )
                                except Exception:
                                    pass

                        elif ch == 'TELEGRAM':
                            campaign.total_sent += 1
                            campaign.total_delivered += 1
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
                        new_failed_items.append(item)
                except Exception:
                    item["retry_count"] = item.get("retry_count", 0) + 1
                    new_failed_items.append(item)

            campaign.failed_recipients = new_failed_items
            if campaign.status == 'FAILED' and campaign.total_sent > 0:
                campaign.status = 'COMPLETED'
            campaign.save()
            return True
        except Exception as e:
            print(f"Error retrying campaign failed recipients: {e}")
            return False
