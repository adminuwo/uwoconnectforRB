from ..services.admin_service import AdminService
from ..repositories.system_repository import SystemRepository
from ..repositories.contact_repository import ContactRepository
from ..repositories.client_repository import ClientRepository
from ..repositories.message_repository import MessageRepository
from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets
from rest_framework.response import Response
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer, TeamInviteSerializer, ProductSerializer, OrderSerializer
from ..models import User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, Template, Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order
import requests
import os
import json
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks, get_ai_draft
from rest_framework.permissions import BasePermission
from .webhook_views import WhatsAppWebhookView, FacebookInstagramWebhookView

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if request.user.role == 'ADMIN':
        client_id = request.query_params.get('client_id') or request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except (Client.DoesNotExist, ValueError):
                pass
        return None
    return request.user.client

class ClientViewSet(viewsets.ModelViewSet):
    queryset = ClientRepository.get_all_clients()
    serializer_class = ClientSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        if self.request.user.role == 'ADMIN':
            return ClientRepository.get_all_clients()
        return ClientRepository.filter_clients(id=self.request.user.client_id)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def suspend(self, request, pk=None):
        from ..services.client_service import ClientService
        result = ClientService.suspend_client(request, self.get_object())
        return Response(result)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reactivate(self, request, pk=None):
        from ..services.client_service import ClientService
        result = ClientService.reactivate_client(request, self.get_object())
        return Response(result)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def disconnect_meta(self, request, pk=None):
        from ..services.client_service import ClientService
        result = ClientService.disconnect_meta(request, self.get_object())
        return Response(result)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reset_ai(self, request, pk=None):
        from ..services.client_service import ClientService
        result = ClientService.reset_ai(request, self.get_object())
        return Response(result)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reset_workflows(self, request, pk=None):
        from ..services.client_service import ClientService
        result = ClientService.reset_workflows(request, self.get_object())
        return Response(result)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def toggle_feature(self, request, pk=None):
        from ..services.client_service import ClientService
        feature = request.data.get('feature')
        result = ClientService.toggle_feature(request, self.get_object(), feature)
        if "error" in result:
            return Response({"error": result["error"]}, status=result["status_code"])
        return Response({"status": result["status"], "value": result["value"]})


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Contact.objects.none()
        return ContactRepository.filter_contacts(client=client)

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Contacts', 'CREATE', after_value=str(serializer.data))

    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Contacts', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Contacts', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)
            
        file = request.FILES.get('file')
        if not file or not file.name.endswith('.csv'):
            return Response({"message": "Please upload a valid CSV file."}, status=400)
            
        try:
            from ..services.contact_service import ContactService
            result = ContactService.import_contacts_from_csv(client, file, request.data.get('stage', 'NEW'))
            return Response(result)
        except Exception as e:
            return Response({"message": f"Error parsing CSV: {str(e)}"}, status=400)

    @action(detail=False, methods=['get'])
    def export_csv(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)
            
        from ..services.contact_service import ContactService
        return ContactService.export_contacts_to_csv(client)


class ClientStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response({
                "totalConversations": 0,
                "automationRuns": 0,
                "activeUsers": 0,
                "avgResponse": "14s"
            }, status=200)
            
        total_conversations = MessageRepository.filter_messages(client=client).values('from_address', 'to_address').distinct().count()
        automation_runs = MessageRepository.filter_messages(client=client, message_type='OUTGOING', status='SENT').count()
        active_users = ContactRepository.filter_contacts(client=client).count()
        
        return Response({
            "totalConversations": total_conversations,
            "automationRuns": automation_runs,
            "activeUsers": active_users,
            "avgResponse": "14s"
        })


class SuggestDraftView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No client associated"}, status=400)
            
        contact_id = request.data.get('contact_id')
        if not contact_id:
            return Response({"error": "contact_id is required"}, status=400)
            
        # Get last 10 messages for context
        try:
            contact = ContactRepository.get_contact(id=contact_id, client=client)
        except Contact.DoesNotExist:
            return Response({"error": "Contact not found"}, status=404)
            
        messages = MessageRepository.filter_messages(
            client=client, 
            from_address=contact.platform_id
        ) | MessageRepository.filter_messages(
            client=client, 
            to_address=contact.platform_id
        )
        
        messages = messages.order_by('-created_at')[:10]
        messages = reversed(messages) # chronological order
        
        chat_history = []
        for msg in messages:
            # Internal notes aren't strictly part of the external convo, but could be helpful context.
            # Let's include them for AI context.
            role = "user" if msg.message_type == "INCOMING" else "assistant"
            chat_history.append({"role": role, "content": msg.body})
            
        if not chat_history:
            return Response({"draft": "Hi there! How can I help you today?"})
            
        draft = get_ai_draft(chat_history)
        return Response({"draft": draft})


class ClientMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response([])
        
        messages = MessageRepository.filter_messages(client=client).order_by('-created_at')[:1000]
        data = []
        for msg in messages:
            data.append({
                "id": str(msg.id),
                "from_address": msg.from_address,
                "to_address": msg.to_address,
                "body": msg.body,
                "channel": msg.channel,
                "message_type": msg.message_type,
                "status": msg.status,
                "metadata": msg.metadata or {},
                "created_at": msg.created_at
            })
        return Response(data)

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"detail": "Client not found"}, status=status.HTTP_400_BAD_REQUEST)
        
        to_number = request.data.get('to_number')
        body = request.data.get('body')
        channel = (request.data.get('channel') or 'WHATSAPP').upper()
        message_type = (request.data.get('message_type') or 'OUTGOING').upper()
        
        if not to_number or not body:
            return Response({"detail": "to_number and body are required"}, status=status.HTTP_400_BAD_REQUEST)

        raw_to = str(to_number).strip()

        new_msg = MessageRepository.create_message(
            client=client,
            channel=channel,
            from_address=request.user.username or 'SYSTEM',
            to_address=raw_to,
            body=body,
            message_type=message_type,
            status='SENT'
        )

        if message_type == 'OUTGOING':
            try:
                from ..services.meta_webhook_service import MetaWebhookService
                if channel == 'WHATSAPP':
                    phone_id = client.whatsapp_phone_number_id or '100000000000000'
                    MetaWebhookService.send_whatsapp_message(client, raw_to, body, phone_id)
                elif channel in ['FACEBOOK', 'INSTAGRAM']:
                    MetaWebhookService.send_fb_ig_message(client, channel, raw_to, body)
            except Exception as e:
                print("Error dispatching external message:", e)

        return Response({
            "id": str(new_msg.id),
            "from_address": new_msg.from_address,
            "to_address": new_msg.to_address,
            "body": new_msg.body,
            "channel": new_msg.channel,
            "message_type": new_msg.message_type,
            "status": new_msg.status,
            "metadata": new_msg.metadata or {},
            "created_at": new_msg.created_at
        }, status=status.HTTP_201_CREATED)

class MediaProxyView(APIView):
    """Proxy endpoint to stream WhatsApp/Meta media files to the frontend with correct Content-Type."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        media_id = request.query_params.get('media_id')
        media_url = request.query_params.get('media_url')
        
        client = get_tenant_client(request)
        if not client:
            client = Client.objects.filter(whatsapp_access_token__isnull=False).exclude(whatsapp_access_token='').first()

        token = client.whatsapp_access_token if client else None
        if media_id and token:
            try:
                url_res = requests.get(
                    f"https://graph.facebook.com/v18.0/{media_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10
                )
                if url_res.status_code == 200:
                    media_url = url_res.json().get('url')
            except Exception as e:
                logger.error("Failed to get media URL for %s: %s", media_id, e)

        if media_url:
            try:
                headers = {"Authorization": f"Bearer {token}"} if (token and "facebook.com" in media_url) else {}
                file_res = requests.get(media_url, headers=headers, timeout=30)
                if file_res.status_code == 200:
                    content_type = file_res.headers.get('Content-Type', 'application/octet-stream')
                    from django.http import HttpResponse
                    response = HttpResponse(file_res.content, content_type=content_type)
                    filename = request.query_params.get('filename')
                    if filename:
                        response['Content-Disposition'] = f'inline; filename="{filename}"'
                    return response
            except Exception as e:
                logger.error("Failed downloading media from %s: %s", media_url, e)

        return Response({"error": "Media file not found or download failed."}, status=404)

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No client associated"}, status=400)
            
        to_number = request.data.get('to_number')
        body = request.data.get('body')
        channel = request.data.get('channel')
        
        if not to_number or not body:
            return Response({"error": "to_number and body are required"}, status=400)
            
        message_type = request.data.get('message_type', 'OUTGOING')
        
        if message_type == 'INTERNAL':
            MessageRepository.create_message(
                client=client,
                channel=channel or 'WHATSAPP',
                from_address=client.business_name,
                to_address=to_number,
                body=body,
                message_type='INTERNAL',
                status='SENT'
            )
            return Response({"status": "internal_note_saved"})
            
        # Detect channel if not provided
        if not channel:
            last_msg = MessageRepository.filter_messages(client=client, from_address=to_number).order_by('-created_at').first()
            if not last_msg:
                last_msg = MessageRepository.filter_messages(client=client, to_address=to_number).order_by('-created_at').first()
            channel = last_msg.channel if last_msg else 'WHATSAPP'
            
        channel = channel.upper()
        
        # Human agent takeover: Pause bot response for this contact
        try:
            from ..models import Contact
            # Standardize format for query lookup
            formatted_number = to_number.replace('+', '').strip()
            contact = ContactRepository.filter_contacts(
                client=client, 
                phone_number__icontains=formatted_number
            ).first()
            if not contact:
                contact = ContactRepository.filter_contacts(
                    client=client, 
                    platform_id=to_number
                ).first()
            if contact and not contact.bot_paused:
                contact.bot_paused = True
                contact.save()
        except Exception as e:
            print(f"Failed to auto-pause bot for contact: {str(e)}")
        
        if channel == 'WHATSAPP':
            phone_number_id = client.whatsapp_phone_number_id or 'WHATSAPP_SYSTEM'
            webhook_view = WhatsAppWebhookView()
            try:
                webhook_view.send_whatsapp_message(client, to_number, body, phone_number_id)
            except Exception as _werr:
                MessageRepository.create_message(
                    client=client,
                    channel='WHATSAPP',
                    from_address=phone_number_id,
                    to_address=to_number,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
        elif channel in ['INSTAGRAM', 'FACEBOOK']:
            webhook_view = FacebookInstagramWebhookView()
            try:
                webhook_view.send_message(client, channel, to_number, body)
            except Exception as _ferr:
                MessageRepository.create_message(
                    client=client,
                    channel=channel,
                    from_address=channel,
                    to_address=to_number,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
        elif channel == 'GMAIL':
            from ..services.gmail_service import send_gmail_message
            try:
                send_gmail_message(client, to_address=to_number, body=body)
                MessageRepository.create_message(
                    client=client,
                    channel='GMAIL',
                    from_address=client.gmail_config.get('email_address', ''),
                    to_address=to_number,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
            except Exception as e:
                return Response({"error": str(e)}, status=400)
        else:
            return Response({"error": f"Unsupported channel: {channel}"}, status=400)
            
        return Response({"status": "sent"})

class AuditLogMixin:
    def get_module_name(self):
        model = None
        if hasattr(self, 'queryset') and self.queryset:
            model = self.queryset.model
        elif hasattr(self, 'get_queryset'):
            try:
                model = self.get_queryset().model
            except Exception:
                pass
        return model.__name__ if model else "General"

    def perform_create(self, serializer):
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, self.get_module_name(), 'CREATE', after_value=str(serializer.data))
        
    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, self.get_module_name(), 'UPDATE', before_value=before_data, after_value=str(serializer.data))
        
    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, self.get_module_name(), 'DELETE', before_value=before_data)
        instance.delete()


