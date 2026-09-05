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

            channel = getattr(campaign, 'channel', 'WHATSAPP')

            if channel == 'WHATSAPP':
                token = client.whatsapp_access_token
                if not token or not client.whatsapp_phone_number_id:
                    if not template and not getattr(campaign, 'message_body', None):
                        campaign.status = 'FAILED'
                        campaign.save()
                        return
            elif channel in ['FACEBOOK', 'INSTAGRAM']:
                body = getattr(campaign, 'body', '') or getattr(campaign, 'message_body', '')
                fb_token = client.facebook_config.get('access_token') if channel == 'FACEBOOK' else client.instagram_config.get('access_token')
                page_id = client.facebook_config.get('page_id') if channel == 'FACEBOOK' else client.instagram_config.get('ig_id')
                if not body or not fb_token or not page_id:
                    campaign.status = 'FAILED'
                    campaign.save()
                    return
            else:
                campaign.status = 'FAILED'
                campaign.save()
                return

            # Determine audience
            if campaign.audience_filter == 'ALL':
                contacts = ContactRepository.filter_contacts(client=client)
            elif campaign.audience_filter == 'SPECIFIC' and campaign.tags:
                # If SPECIFIC, tags field contains the list of selected contact IDs
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
            campaign.total_queued = len(contact_list)
            campaign.failed_recipients = []
            campaign.save()

            for contact in contact_list:
                name = contact.name or f"Contact #{contact.id}"
                phone = (contact.phone_number or "").replace("+", "").replace(" ", "").replace("-", "").strip()

                try:
                    from ..integrations.meta_integration import MetaIntegration
                    from ..repositories.message_repository import MessageRepository

                    if channel == 'WHATSAPP':
                        if not phone:
                            campaign.total_failed += 1
                            campaign.failed_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": "N/A",
                                "platform": "WhatsApp",
                                "reason": "Missing Phone Number",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "retry_count": 0,
                                "status": "FAILED"
                            })
                            campaign.save()
                            continue

                        cust_name = contact.name or "Customer"
                        first_name = cust_name.split()[0] if cust_name else "Customer"

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
                            # Check if template body requires parameters (e.g. {{1}})
                            components = getattr(template, 'components', []) or []
                            has_body_vars = False
                            for comp in components:
                                if comp.get('type') == 'BODY' and '{{1}}' in comp.get('text', ''):
                                    has_body_vars = True
                                    break
                            if has_body_vars:
                                payload["template"]["components"] = [
                                    {
                                        "type": "body",
                                        "parameters": [
                                            {"type": "text", "text": first_name}
                                        ]
                                    }
                                ]
                            msg_summary = f"[Template: {template.name}]"
                        else:
                            msg_text = getattr(campaign, 'message_body', None) or "Hello from UWOConnect!"
                            msg_text = msg_text.replace("{{first_name}}", first_name)\
                                               .replace("{{name}}", cust_name)\
                                               .replace("{{phone}}", phone)\
                                               .replace("{{email}}", getattr(contact, 'email', '') or '')\
                                               .replace("{{company}}", getattr(client, 'business_name', '') or 'UWOConnect')
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
                                # Log in Message repository so it shows in Inbox & CRM conversation history
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
                                except Exception as m_err:
                                    print(f"[CampaignService] Outgoing message log error: {m_err}")
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
                                    "retry_count": 0,
                                    "status": "FAILED"
                                })
                        else:
                            campaign.total_failed += 1
                            campaign.failed_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": phone,
                                "platform": "WhatsApp",
                                "reason": "WhatsApp Credentials Missing in Workspace Settings",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "retry_count": 0,
                                "status": "FAILED"
                            })

                    elif channel in ['FACEBOOK', 'INSTAGRAM']:
                        recipient_id = contact.metadata.get('psid') if channel == 'FACEBOOK' else contact.metadata.get('igsid')
                        if not recipient_id:
                            campaign.total_failed += 1
                            campaign.failed_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": phone or "N/A",
                                "platform": channel,
                                "reason": "Missing recipient platform ID (PSID/IGSID)",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "retry_count": 0,
                                "status": "FAILED"
                            })
                            campaign.save()
                            continue

                        fb_token_c = client.facebook_config.get('access_token') if channel == 'FACEBOOK' else client.instagram_config.get('access_token')
                        page_id_c = client.facebook_config.get('page_id') if channel == 'FACEBOOK' else client.instagram_config.get('ig_id')
                        payload = {
                            "recipient": {"id": recipient_id},
                            "message": {"text": getattr(campaign, 'body', '') or getattr(campaign, 'message_body', '')},
                            "messaging_type": "MESSAGE_TAG",
                            "tag": "POST_PURCHASE_UPDATE"
                        }
                        url = f"https://graph.facebook.com/v19.0/{page_id_c}/messages"
                        res = requests.post(url, headers={"Authorization": f"Bearer {fb_token_c}"}, json=payload)
                        if res.status_code == 200:
                            campaign.total_sent += 1
                            campaign.total_delivered += 1
                        else:
                            campaign.total_failed += 1
                            campaign.failed_recipients.append({
                                "id": str(contact.id),
                                "name": name,
                                "phone": phone or "N/A",
                                "platform": channel,
                                "reason": f"HTTP {res.status_code}",
                                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                "retry_count": 0,
                                "status": "FAILED"
                            })

                except Exception as e:
                    campaign.total_failed += 1
                    campaign.failed_recipients.append({
                        "id": str(contact.id),
                        "name": name,
                        "phone": phone or "N/A",
                        "platform": channel,
                        "reason": str(e),
                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "retry_count": 0,
                        "status": "FAILED"
                    })

                campaign.total_queued = max(0, campaign.total_queued - 1)
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
