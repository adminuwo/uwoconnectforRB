from ..models import Message, SupportMessage, TeamMessage

class MessageRepository:
    @staticmethod
    def filter_messages(**kwargs):
        return Message.objects.filter(**kwargs)

    @staticmethod
    def get_message(id):
        return Message.objects.filter(id=id).first()

    @staticmethod
    def get_all_messages():
        return Message.objects.all()

    @staticmethod
    def get_all():
        return Message.objects.all()
        
    @staticmethod
    def create_message(**kwargs):
        msg = Message.objects.create(**kwargs)
        from ..models import Contact, Conversation
        from django.utils import timezone
        
        # Touch the contact's updated_at so it rises to the top of the inbox list
        client = kwargs.get('client')
        platform_id = msg.from_address if msg.message_type == 'INCOMING' else msg.to_address
        if client and platform_id:
            Contact.objects.filter(client=client, platform_id=platform_id).update(updated_at=timezone.now())
            
            # Create or update Conversation safely without MultipleObjectsReturned exception
            try:
                contact_obj = Contact.objects.filter(client=client, platform_id=platform_id).first()
                inferred_ch = msg.channel
                if not inferred_ch or inferred_ch == 'WHATSAPP':
                    cname = (contact_obj.name if contact_obj else '') or ''
                    pid_str = str(platform_id).lower()
                    if 'INSTAGRAM' in cname.upper() or 'instagram' in pid_str or pid_str.startswith('ig_'):
                        inferred_ch = 'INSTAGRAM'
                    elif 'FACEBOOK' in cname.upper() or 'facebook' in pid_str or pid_str.startswith('fb_'):
                        inferred_ch = 'FACEBOOK'
                    elif '@' in pid_str:
                        inferred_ch = 'GMAIL'
                    else:
                        inferred_ch = inferred_ch or 'WHATSAPP'

                convo = Conversation.objects.filter(client=client, contact_platform_id=platform_id).first()
                if not convo:
                    convo = Conversation.objects.create(
                        client=client,
                        contact_platform_id=platform_id,
                        channel=inferred_ch,
                        contact=contact_obj,
                        last_message_summary=msg.body,
                        last_message_at=msg.created_at or timezone.now()
                    )
                else:
                    convo.last_message_summary = msg.body
                    convo.last_message_at = msg.created_at or timezone.now()
                    if inferred_ch and inferred_ch != 'WHATSAPP':
                        convo.channel = inferred_ch
                    if not convo.contact:
                        convo.contact = contact_obj
                    convo.save()
            except Exception as _convo_err:
                pass

            # Automatic Lead Qualification for Incoming Messages (Pricing / Product Inquiry)
            if msg.message_type == 'INCOMING' and msg.body:
                try:
                    from ..services.lead_qualification_service import LeadQualificationService
                    LeadQualificationService.qualify_and_update_contact(client, platform_id, msg.body)
                except Exception as _lead_err:
                    pass

            # Real-time WebSocket event broadcast to inbox group
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"inbox_{client.id}",
                        {
                            "type": "new_message",
                            "message": {
                                "id": str(msg.id),
                                "from_address": msg.from_address,
                                "to_address": msg.to_address,
                                "body": msg.body,
                                "channel": msg.channel,
                                "message_type": msg.message_type,
                                "status": msg.status,
                                "created_at": str(msg.created_at or timezone.now())
                            }
                        }
                    )
            except Exception as _ws_err:
                pass
            
        return msg

class SupportMessageRepository:
    @staticmethod
    def filter_messages(**kwargs):
        return SupportMessage.objects.filter(**kwargs)
        
    @staticmethod
    def create_message(**kwargs):
        return SupportMessage.objects.create(**kwargs)

class TeamMessageRepository:
    @staticmethod
    def filter_messages(**kwargs):
        return TeamMessage.objects.filter(**kwargs)
        
    @staticmethod
    def create_message(**kwargs):
        return TeamMessage.objects.create(**kwargs)
