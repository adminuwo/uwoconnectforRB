import time
import threading
from django.utils import timezone
from datetime import timedelta
from django.db import close_old_connections

def start_followup_scheduler():
    thread = threading.Thread(target=followup_poller, daemon=True, name="FollowUpBackgroundPoller")
    thread.start()

def followup_poller():
    time.sleep(15)  # Let server start
    print("[Follow-up Scheduler]: Background loop STARTED.")
    while True:
        try:
            close_old_connections()
            from api.models import CampaignFollowUp, FollowUpLog, Message
            from api.services.meta_webhook_service import MetaWebhookService
            
            # Find active follow-ups for completed/sent campaigns
            active_followups = CampaignFollowUp.objects.filter(
                is_active=True,
                campaign__status__in=['COMPLETED', 'SENDING']
            )

            for fu in active_followups:
                base_time = fu.campaign.scheduled_at or fu.campaign.created_at
                if not base_time:
                    continue
                
                trigger_time = base_time + timedelta(hours=fu.delay_hours)
                
                if timezone.now() >= trigger_time:
                    client = fu.campaign.client
                    if not fu.campaign.template:
                        continue
                        
                    # Find all contacts who received the original campaign template
                    original_messages = Message.objects.filter(
                        client=client,
                        message_type='OUTGOING',
                        created_at__gte=base_time - timedelta(minutes=10),
                        created_at__lte=base_time + timedelta(hours=2)
                    )
                    
                    target_phones = set([m.to_address for m in original_messages])
                    
                    for phone in target_phones:
                        from api.models import Contact
                        fmt_phone = phone.replace('+', '').strip()
                        contact = Contact.objects.filter(client=client, phone_number__icontains=fmt_phone).first()
                        
                        if not contact:
                            continue
                            
                        if FollowUpLog.objects.filter(followup=fu, contact=contact).exists():
                            continue
                            
                        # Did this contact SEND an INCOMING message AFTER the campaign base_time?
                        replied = Message.objects.filter(
                            client=client,
                            message_type='INCOMING',
                            from_address=phone,
                            created_at__gt=base_time
                        ).exists()
                        
                        if replied:
                            # Mark as skipped
                            FollowUpLog.objects.create(followup=fu, contact=contact, status='SKIPPED_REPLIED')
                            continue
                            
                        # If no reply, SEND FOLLOW-UP!
                        if fu.followup_template and client.whatsapp_phone_number_id and client.whatsapp_access_token:
                            try:
                                from api.integrations.meta_integration import MetaIntegration
                                from api.repositories.message_repository import MessageRepository
                                payload = {
                                    "messaging_product": "whatsapp",
                                    "to": phone,
                                    "type": "template",
                                    "template": {
                                        "name": fu.followup_template.name,
                                        "language": {"code": fu.followup_template.language or "en"}
                                    }
                                }
                                res = MetaIntegration.send_whatsapp_message(
                                    phone_number_id=client.whatsapp_phone_number_id,
                                    token=client.whatsapp_access_token,
                                    payload=payload
                                )
                                if res.status_code in [200, 201]:
                                    FollowUpLog.objects.create(followup=fu, contact=contact, status='SENT')
                                    MessageRepository.create_message(
                                        client=client,
                                        channel='WHATSAPP',
                                        from_address=client.whatsapp_phone_number_id,
                                        to_address=phone,
                                        body=f"[Follow-up Template: {fu.followup_template.name}]",
                                        message_type='OUTGOING',
                                        status='SENT'
                                    )
                                else:
                                    print(f"[FollowUp Error] Meta API returned {res.status_code}: {res.text}")
                                    FollowUpLog.objects.create(followup=fu, contact=contact, status='FAILED')
                            except Exception as send_err:
                                print(f"[FollowUp Error] Could not send to {phone}: {send_err}")
                                FollowUpLog.objects.create(followup=fu, contact=contact, status='FAILED')
                                        
        except Exception as e:
            print(f"[FollowUp Poller Error]: {e}")
            
        time.sleep(60) # Check every 60 seconds
