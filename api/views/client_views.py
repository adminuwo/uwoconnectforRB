from ..services.admin_service import AdminService
from ..repositories.system_repository import SystemRepository
from ..repositories.contact_repository import ContactRepository
from ..repositories.client_repository import ClientRepository
from ..repositories.message_repository import MessageRepository
from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets, filters
from rest_framework.response import Response
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action
from rest_framework.views import APIView
import os
import json
import ipaddress
import socket
import urllib
import urllib.parse
from django.db.models import Q
from bson import ObjectId
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer, TeamInviteSerializer, ProductSerializer, OrderSerializer
from ..models import User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, ContactFollowUp, Conversation, Template, Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order
import requests
import logging
logger = logging.getLogger(__name__)
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks, get_ai_draft
from ..utils.channel_permissions import get_user_allowed_channels
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
        return getattr(request.user, 'client', None)
    return getattr(request.user, 'client', None)

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

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_whatsapp_profile_picture(self, request, pk=None):
        client = self.get_object()
        
        # Verify ownership
        if request.user.role != 'ADMIN' and request.user.client_id != client.id:
            return Response({"error": "Unauthorized"}, status=403)

        if not client.whatsapp_phone_number_id or not client.whatsapp_access_token:
            return Response({"error": "WhatsApp not connected"}, status=400)

        image_file = request.FILES.get('profile_picture')
        if not image_file:
            return Response({"error": "No image provided. Please send file in 'profile_picture' form field."}, status=400)

        app_id = os.getenv('FACEBOOK_APP_ID')
        if not app_id:
            return Response({"error": "Server is missing FACEBOOK_APP_ID"}, status=500)

        file_length = image_file.size
        file_type = image_file.content_type

        # 1. Create Resumable Upload Session
        session_url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{app_id}/uploads?file_length={file_length}&file_type={file_type}"
        headers = {
            "Authorization": f"Bearer {client.whatsapp_access_token}"
        }
        
        try:
            res = requests.post(session_url, headers=headers)
            res_data = res.json()
            if 'id' not in res_data:
                return Response({"error": "Failed to create upload session with Meta", "details": res_data}, status=400)
                
            upload_session_id = res_data['id']

            # 2. Upload file binary data
            upload_url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{upload_session_id}"
            upload_headers = {
                "Authorization": f"Bearer {client.whatsapp_access_token}",
                "file_offset": "0"
            }
            
            image_file.seek(0)
            upload_res = requests.post(upload_url, headers=upload_headers, data=image_file.read())
            upload_data = upload_res.json()
            if 'h' not in upload_data:
                return Response({"error": "Failed to upload file data to Meta", "details": upload_data}, status=400)
                
            file_handle = upload_data['h']

            # 3. Update WhatsApp Business Profile
            profile_url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{client.whatsapp_phone_number_id}/whatsapp_business_profile"
            profile_payload = {
                "messaging_product": "whatsapp",
                "profile_picture_handle": file_handle
            }
            profile_headers = {
                "Authorization": f"Bearer {client.whatsapp_access_token}",
                "Content-Type": "application/json"
            }
            profile_res = requests.post(profile_url, headers=profile_headers, json=profile_payload)
            profile_data = profile_res.json()

            if profile_res.status_code == 200 and profile_data.get('success'):
                # Fetch fresh profile picture URL from Meta
                profile_pic_url = None
                try:
                    meta_get = requests.get(
                        f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{client.whatsapp_phone_number_id}/whatsapp_business_profile?fields=profile_picture_url",
                        headers={"Authorization": f"Bearer {client.whatsapp_access_token}"},
                        timeout=10
                    )
                    if meta_get.status_code == 200:
                        m_data = meta_get.json().get('data', [])
                        if m_data and isinstance(m_data, list) and len(m_data) > 0:
                            profile_pic_url = m_data[0].get('profile_picture_url')
                except Exception as ex:
                    logger.warning(f"Failed to fetch profile picture URL from Meta: {ex}")

                settings_dict = client.settings or {}
                if profile_pic_url:
                    settings_dict['whatsapp_profile_picture_url'] = profile_pic_url
                    client.settings = settings_dict
                    client.save(update_fields=['settings'])

                return Response({
                    "status": "success",
                    "message": "Profile picture updated successfully on WhatsApp!",
                    "profile_picture_url": profile_pic_url
                })
            else:
                return Response({"error": "Failed to update WhatsApp profile", "details": profile_data}, status=400)
                
        except Exception as e:
            return Response({"error": f"An internal error occurred: {str(e)}"}, status=500)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def get_whatsapp_profile_picture(self, request, pk=None):
        client = self.get_object()
        
        # Verify ownership
        if request.user.role != 'ADMIN' and request.user.client_id != client.id:
            return Response({"error": "Unauthorized"}, status=403)

        if not client.whatsapp_phone_number_id or not client.whatsapp_access_token:
            return Response({"profile_picture_url": None, "error": "WhatsApp not connected"}, status=200)

        cached_url = (client.settings or {}).get('whatsapp_profile_picture_url')

        # Try to query Meta live for the latest/active profile picture URL
        try:
            meta_get = requests.get(
                f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{client.whatsapp_phone_number_id}/whatsapp_business_profile?fields=profile_picture_url",
                headers={"Authorization": f"Bearer {client.whatsapp_access_token}"},
                timeout=10
            )
            if meta_get.status_code == 200:
                m_data = meta_get.json().get('data', [])
                if m_data and isinstance(m_data, list) and len(m_data) > 0:
                    live_url = m_data[0].get('profile_picture_url')
                    if live_url:
                        settings_dict = client.settings or {}
                        settings_dict['whatsapp_profile_picture_url'] = live_url
                        client.settings = settings_dict
                        client.save(update_fields=['settings'])
                        return Response({"status": "success", "profile_picture_url": live_url})
        except Exception as ex:
            logger.warning(f"Failed to fetch live WhatsApp profile picture: {ex}")

        return Response({"status": "success", "profile_picture_url": cached_url})

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def get_whatsapp_business_profile(self, request, pk=None):
        client = self.get_object()
        if request.user.role != 'ADMIN' and request.user.client_id != client.id:
            return Response({"error": "Unauthorized"}, status=403)

        settings_dict = client.settings or {}
        cached_profile = settings_dict.get('whatsapp_business_profile', {})
        cached_hours = settings_dict.get('whatsapp_business_hours', {})

        if not client.whatsapp_phone_number_id or not client.whatsapp_access_token:
            return Response({
                "profile": cached_profile,
                "business_hours": cached_hours,
                "is_connected": False
            }, status=200)

        # Fetch live details from Meta Graph API
        live_profile = dict(cached_profile)
        force_meta = request.query_params.get('force_meta') == 'true'
        try:
            url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{client.whatsapp_phone_number_id}/whatsapp_business_profile?fields=about,address,description,email,profile_picture_url,websites,vertical"
            headers = {"Authorization": f"Bearer {client.whatsapp_access_token}"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data_list = res.json().get('data', [])
                if data_list and isinstance(data_list, list) and len(data_list) > 0:
                    meta_data = data_list[0]
                    for field in ['address', 'description', 'about', 'email', 'vertical']:
                        meta_val = meta_data.get(field)
                        if meta_val and str(meta_val).strip():
                            # If force_meta is True or field wasn't set by user, apply Meta's value
                            if force_meta or not cached_profile.get(field):
                                live_profile[field] = str(meta_val).strip()
                    if meta_data.get('websites') and isinstance(meta_data['websites'], list):
                        valid_sites = [str(w).strip() for w in meta_data['websites'] if str(w).strip()]
                        if valid_sites and (force_meta or not cached_profile.get('websites')):
                            live_profile['websites'] = valid_sites
                    if meta_data.get('profile_picture_url'):
                        live_profile['profile_picture_url'] = meta_data['profile_picture_url']
                        settings_dict['whatsapp_profile_picture_url'] = meta_data['profile_picture_url']

                    settings_dict['whatsapp_business_profile'] = live_profile
                    client.settings = settings_dict
                    client.save(update_fields=['settings'])
        except Exception as ex:
            logger.warning(f"Failed to fetch live WhatsApp business profile from Meta: {ex}")

        return Response({
            "status": "success",
            "profile": live_profile,
            "business_hours": cached_hours,
            "is_connected": True
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_whatsapp_business_profile(self, request, pk=None):
        client = self.get_object()
        if request.user.role != 'ADMIN' and request.user.client_id != client.id:
            return Response({"error": "Unauthorized"}, status=403)

        if not client.whatsapp_phone_number_id or not client.whatsapp_access_token:
            return Response({"error": "WhatsApp is not connected"}, status=400)

        profile_data = request.data.get('profile', {})
        business_hours = request.data.get('business_hours', {})

        # 1. Always persist to client settings first so user changes are never lost
        settings_dict = client.settings or {}
        current_profile = settings_dict.get('whatsapp_business_profile', {})
        current_profile.update(profile_data)
        settings_dict['whatsapp_business_profile'] = current_profile

        if business_hours:
            settings_dict['whatsapp_business_hours'] = business_hours

        client.settings = settings_dict
        client.save(update_fields=['settings'])

        # 2. Prepare clean Meta payload (Meta Cloud API strictly rejects empty strings with #131000)
        meta_payload = {
            "messaging_product": "whatsapp"
        }
        
        if profile_data.get('address') and str(profile_data['address']).strip():
            meta_payload['address'] = str(profile_data['address']).strip()[:256]
        if profile_data.get('description') and str(profile_data['description']).strip():
            meta_payload['description'] = str(profile_data['description']).strip()[:512]
        if profile_data.get('about') and str(profile_data['about']).strip():
            meta_payload['about'] = str(profile_data['about']).strip()[:139]
        if profile_data.get('email') and str(profile_data['email']).strip():
            meta_payload['email'] = str(profile_data['email']).strip()[:128]
        if profile_data.get('vertical') and str(profile_data['vertical']).strip():
            meta_payload['vertical'] = str(profile_data['vertical']).strip()
        if profile_data.get('websites'):
            ws = profile_data['websites']
            if isinstance(ws, list):
                clean_ws = [str(w).strip() for w in ws if str(w).strip()]
                if clean_ws:
                    meta_payload['websites'] = clean_ws[:2]
            elif isinstance(ws, str) and ws.strip():
                meta_payload['websites'] = [ws.strip()]

        # 3. Call Meta Graph API if attributes are provided
        meta_synced = False
        meta_error = None
        if len(meta_payload) > 1:
            meta_url = f"https://graph.facebook.com/{os.getenv('WHATSAPP_API_VERSION', 'v20.0')}/{client.whatsapp_phone_number_id}/whatsapp_business_profile"
            headers = {
                "Authorization": f"Bearer {client.whatsapp_access_token}",
                "Content-Type": "application/json"
            }
            try:
                meta_res = requests.post(meta_url, headers=headers, json=meta_payload, timeout=12)
                meta_json = meta_res.json()
                if meta_res.status_code == 200 and meta_json.get('success'):
                    meta_synced = True
                else:
                    meta_error = meta_json.get('error', {}).get('message') or str(meta_json)
                    logger.warning(f"Meta Cloud API business profile update response: {meta_json}")
            except Exception as ex:
                meta_error = str(ex)
                logger.warning(f"Meta Cloud API update exception: {ex}")

        return Response({
            "status": "success",
            "meta_synced": meta_synced,
            "meta_warning": meta_error if not meta_synced else None,
            "message": "WhatsApp Business Profile & Operating Hours updated successfully!",
            "profile": current_profile,
            "business_hours": settings_dict.get('whatsapp_business_hours', {})
        }, status=200)


class ContactViewSet(viewsets.ModelViewSet):
    permission_classes = [IsApprovedUser]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['id', 'updated_at', 'created_at']
    ordering = ['-updated_at']

    def get_serializer_class(self):
        if self.action == 'list':
            from ..serializers import ContactListSerializer
            return ContactListSerializer
        from ..serializers import ContactSerializer
        return ContactSerializer

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if not client:
            return Contact.objects.none()

        allowed_channels = get_user_allowed_channels(self.request.user, client)
        if not allowed_channels and self.request.user.role != 'ADMIN':
            return Contact.objects.none()

        qs = ContactRepository.filter_contacts(client=client)

        search_query = self.request.query_params.get('search', None)
        if search_query:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search_query) | Q(phone_number__icontains=search_query) | Q(platform_id__icontains=search_query))

        channel_filter = self.request.query_params.get('preferred_channel', None)
        if channel_filter and channel_filter != 'ALL':
            from django.db.models import Q
            ch = channel_filter.upper()
            if ch == 'INSTAGRAM':
                qs = qs.filter(Q(name__icontains='INSTAGRAM') | Q(platform_id__icontains='instagram') | Q(platform_id__startswith='ig_'))
            elif ch == 'FACEBOOK':
                qs = qs.filter(Q(name__icontains='FACEBOOK') | Q(platform_id__icontains='facebook') | Q(platform_id__startswith='fb_'))
            elif ch == 'GMAIL':
                qs = qs.filter(Q(platform_id__contains='@') | Q(email__isnull=False) | Q(email__contains='@'))
            elif ch == 'WHATSAPP':
                qs = qs.filter(~Q(name__icontains='INSTAGRAM') & ~Q(name__icontains='FACEBOOK') & ~Q(platform_id__contains='@') & ~Q(platform_id__startswith='ig_') & ~Q(platform_id__startswith='fb_'))
            else:
                qs = qs.filter(platform_id__startswith=f"{ch.lower()}_")
        elif self.request.user.role != 'ADMIN' and set(allowed_channels) < {'WHATSAPP', 'FACEBOOK', 'INSTAGRAM'}:
            pass

        from django.db.models import Prefetch
        from ..models import ContactFollowUp
        return qs.prefetch_related(
            Prefetch('follow_ups', queryset=ContactFollowUp.objects.filter(status='PENDING').order_by('scheduled_at'), to_attr='pending_followups')
        ).order_by('-updated_at')

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

    @action(detail=True, methods=['get'])
    def follow_ups(self, request, pk=None):
        """List all follow-up tasks for a specific contact."""
        contact = self.get_object()
        client = get_tenant_client(request)
        qs = ContactFollowUp.objects.filter(contact=contact, client=client).order_by('scheduled_at')
        from ..serializers import ContactFollowUpSerializer
        serializer = ContactFollowUpSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='follow_ups/create')
    def create_follow_up(self, request, pk=None):
        """Schedule a new follow-up task for a contact."""
        contact = self.get_object()
        client = get_tenant_client(request)
        from ..serializers import ContactFollowUpSerializer
        serializer = ContactFollowUpSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(contact=contact, client=client, created_by=request.user)
            # Auto-advance stage to FOLLOWUP if still NEW or QUALIFIED
            if contact.stage in ('NEW', 'QUALIFIED'):
                contact.stage = 'FOLLOWUP'
                contact.save(update_fields=['stage'])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], url_path='follow_ups/(?P<fid>[^/.]+)/update')
    def update_follow_up(self, request, pk=None, fid=None):
        """Mark a follow-up as DONE or CANCELLED."""
        client = get_tenant_client(request)
        try:
            fu = ContactFollowUp.objects.get(pk=fid, client=client)
        except ContactFollowUp.DoesNotExist:
            return Response({'detail': 'Follow-up not found.'}, status=status.HTTP_404_NOT_FOUND)

        from django.utils import timezone
        new_status = request.data.get('status')
        if new_status == 'DONE':
            fu.completed_at = timezone.now()
        fu.status = new_status or fu.status
        note = request.data.get('note')
        if note is not None:
            fu.note = note
        fu.save()
        from ..serializers import ContactFollowUpSerializer
        return Response(ContactFollowUpSerializer(fu).data)

    @action(detail=False, methods=['get'])
    def upcoming_followups(self, request):
        """Return today's and overdue pending follow-ups — used by Home screen widget."""
        from django.utils import timezone
        from datetime import timedelta
        client = get_tenant_client(request)
        if not client:
            return Response([], status=200)
        now = timezone.now()
        window_end = now + timedelta(days=7)  # Next 7 days
        qs = ContactFollowUp.objects.filter(
            client=client,
            status='PENDING',
            scheduled_at__lte=window_end,
        ).select_related('contact').order_by('scheduled_at')[:20]
        from ..serializers import ContactFollowUpSerializer
        serializer = ContactFollowUpSerializer(qs, many=True)
        # Enrich with contact info
        data = serializer.data
        for item, fu_obj in zip(data, qs):
            item['contact_name'] = fu_obj.contact.name or fu_obj.contact.phone_number or 'Unknown'
            item['contact_phone'] = fu_obj.contact.phone_number or ''
            item['contact_stage'] = fu_obj.contact.stage
        return Response(data)


class ClientStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = get_tenant_client(request)
        if not client:
            # Fallback to counting all data if super admin with no specific tenant
            total_conversations = Contact.objects.count()
            automation_runs = Message.objects.filter(message_type='OUTGOING', status='SENT').count()
            active_users = total_conversations
            connectors_count = 5
            projects_count = Workflow.objects.count()
            team_members_count = User.objects.count()
            pdfs_count = KnowledgeDocument.objects.count()
            products_count = Product.objects.count()
            crm_leads_count = total_conversations
            return Response({
                "totalConversations": total_conversations,
                "automationRuns": automation_runs,
                "activeUsers": active_users,
                "avgResponse": "14s",
                "resourceCounts": {
                    "connectors": connectors_count,
                    "projects": projects_count,
                    "teamMembers": team_members_count,
                    "pdfs": pdfs_count,
                    "products": products_count,
                    "crmLeads": crm_leads_count
                }
            }, status=200)
            
        total_conversations = ContactRepository.filter_contacts(client=client).count()
        automation_runs = MessageRepository.filter_messages(client=client, message_type='OUTGOING', status='SENT').count()
        active_users = total_conversations

        # --- Live Resource Counts from Database ---
        connector_flags = [
            client.automation_enabled and bool(client.whatsapp_access_token),  # WhatsApp
            client.facebook_enabled,
            client.instagram_enabled,
            client.gmail_enabled,
            client.outlook_enabled,
            client.youtube_enabled,
            client.google_news_enabled,
            client.onedrive_enabled,
            client.google_calendar_enabled,
            client.google_sheets_enabled,
            client.google_docs_enabled,
            client.google_slides_enabled,
            client.zoho_enabled,
        ]
        connectors_count = sum(1 for flag in connector_flags if flag)

        from ..repositories.workflow_repository import WorkflowRepository
        projects_count = WorkflowRepository.filter_workflows(client=client).count()

        from ..models import User
        team_members_count = User.objects.filter(client=client).count()

        from ..repositories.knowledge_repository import KnowledgeRepository
        pdfs_count = KnowledgeRepository.filter_documents(client=client).count()

        from ..repositories.product_repository import ProductRepository
        products_count = ProductRepository.filter_products(client=client).count()
        crm_leads_count = total_conversations

        return Response({
            "totalConversations": total_conversations,
            "automationRuns": automation_runs,
            "activeUsers": active_users,
            "avgResponse": "14s",
            "resourceCounts": {
                "connectors": connectors_count,
                "projects": projects_count,
                "teamMembers": team_members_count,
                "pdfs": pdfs_count,
                "products": products_count,
                "crmLeads": crm_leads_count
            }
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

        allowed_channels = get_user_allowed_channels(request.user, client)
        if not allowed_channels and request.user.role != 'ADMIN':
            return Response([])
            
        contact_id = request.query_params.get('contact_id')
        try:
            limit = int(request.query_params.get('limit', 100))
        except ValueError:
            limit = 100
            
        try:
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            offset = 0

        messages = MessageRepository.filter_messages(client=client)

        channel_filter = request.query_params.get('channel')
        if channel_filter and channel_filter != 'ALL':
            if channel_filter.upper() in allowed_channels or request.user.role == 'ADMIN':
                messages = messages.filter(channel=channel_filter.upper())
            else:
                return Response([])
        else:
            if request.user.role != 'ADMIN':
                messages = messages.filter(channel__in=allowed_channels)

        if contact_id:
            search_terms = set([contact_id, str(contact_id).strip()])
            clean_digits = ''.join(filter(str.isdigit, str(contact_id)))
            if clean_digits:
                search_terms.add(clean_digits)
                if len(clean_digits) == 10:
                    search_terms.add(f"91{clean_digits}")
                    search_terms.add(f"+91{clean_digits}")
                elif clean_digits.startswith("91") and len(clean_digits) == 12:
                    search_terms.add(clean_digits[2:])
                    search_terms.add(f"+{clean_digits}")

            # Safely lookup matching Contact without ValidationError on non-ObjectId strings
            contact_obj = None
            try:
                contact_q = Q(platform_id=contact_id) | Q(phone_number=contact_id) | Q(email=contact_id)
                if ObjectId.is_valid(str(contact_id)):
                    contact_q |= Q(id=contact_id)
                contact_obj = Contact.objects.filter(Q(client=client) & contact_q).first()
            except Exception as lookup_err:
                pass

            # Fallback: if contact_id is a Conversation ID or matches Conversation
            if not contact_obj:
                try:
                    convo_q = Q(contact_platform_id=contact_id)
                    if ObjectId.is_valid(str(contact_id)):
                        convo_q |= Q(id=contact_id)
                    convo_obj = Conversation.objects.filter(Q(client=client) & convo_q).first()
                    if convo_obj:
                        if getattr(convo_obj, 'contact_platform_id', None):
                            search_terms.add(str(convo_obj.contact_platform_id))
                        if getattr(convo_obj, 'contact_id', None):
                            search_terms.add(str(convo_obj.contact_id))
                        if getattr(convo_obj, 'contact', None):
                            contact_obj = convo_obj.contact
                except Exception:
                    pass

            if contact_obj:
                if contact_obj.platform_id:
                    search_terms.add(str(contact_obj.platform_id))
                if contact_obj.phone_number:
                    search_terms.add(str(contact_obj.phone_number))
                    p_digits = ''.join(filter(str.isdigit, str(contact_obj.phone_number)))
                    if p_digits:
                        search_terms.add(p_digits)
                if contact_obj.email:
                    search_terms.add(str(contact_obj.email))
                search_terms.add(str(contact_obj.id))

            q_filter = Q()
            for term in search_terms:
                if term:
                    q_filter |= Q(from_address=term) | Q(to_address=term)

            messages = messages.filter(q_filter)

        # Sort descending by indexed ID to get latest messages fast without MongoDB memory overflow
        messages = messages.order_by('-id')[offset:offset+limit]
        msg_list = list(messages)

        # Find the latest incoming message timestamp to determine customer read state
        latest_incoming_time = None
        for m in msg_list:
            if m.message_type == 'INCOMING':
                m_time = getattr(m, 'created_at', None)
                if m_time and (latest_incoming_time is None or m_time > latest_incoming_time):
                    latest_incoming_time = m_time

        # Automatically mark incoming messages as READ on agent viewing & trigger Meta WhatsApp read receipt asynchronously
        if contact_id and client:
            try:
                import threading
                unread_incomings = [m for m in msg_list if m.message_type == 'INCOMING' and (m.status or '').upper() != 'READ']
                if unread_incomings:
                    for u_msg in unread_incomings[:10]:
                        u_msg.status = 'READ'
                        u_msg.save()

                    def async_mark_read(c_target, msgs_to_mark):
                        from ..services.meta_webhook_service import MetaWebhookService
                        for m in msgs_to_mark:
                            wa_id = getattr(m, 'whatsapp_message_id', None)
                            if wa_id:
                                try:
                                    MetaWebhookService.mark_whatsapp_message_as_read(c_target, wa_id)
                                except Exception:
                                    pass

                    threading.Thread(target=async_mark_read, args=(client, unread_incomings[:10]), daemon=True).start()
            except Exception:
                pass


        data = []
        for msg in msg_list:
            msg_status = (getattr(msg, 'status', None) or 'SENT').upper()

            # If an outgoing message was created prior to a customer's incoming reply, it was definitively read!
            if msg.message_type == 'OUTGOING' and msg_status in ['SENT', 'DELIVERED', 'RECEIVED', 'PENDING']:
                if latest_incoming_time and getattr(msg, 'created_at', None) and msg.created_at <= latest_incoming_time:
                    msg_status = 'READ'
                    if msg.status != 'READ':
                        try:
                            msg.status = 'READ'
                            msg.save()
                        except Exception:
                            pass

            data.append({
                "id": str(msg.id),
                "from_address": msg.from_address,
                "to_address": msg.to_address,
                "body": msg.body,
                "channel": msg.channel,
                "message_type": msg.message_type,
                "status": msg_status,
                "whatsapp_message_id": getattr(msg, 'whatsapp_message_id', None),
                "buttons": getattr(msg, 'buttons', []) or [],
                "metadata": msg.metadata or {},
                "created_at": msg.created_at
            })
        return Response(data)


    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No client associated"}, status=400)
            
        to_number = request.data.get('to_number')
        body = request.data.get('body')
        channel = request.data.get('channel')
        
        message_type = request.data.get('message_type', 'OUTGOING')
        
        if message_type == 'INCOMING':
            incoming_msg = MessageRepository.create_message(
                client=client,
                channel=channel or 'WHATSAPP',
                from_address=to_number,
                to_address=client.business_name,
                body=body,
                message_type='INCOMING',
                status='RECEIVED'
            )
            # Unpause bot for testing
            try:
                contact = Contact.objects.filter(Q(client=client) & (Q(platform_id=to_number) | Q(phone_number=to_number))).first()
                if contact:
                    contact.bot_paused = False
                    contact.save()
            except Exception:
                pass

            # Trigger Workflow Engine
            from ..services.workflow_service import WorkflowEngine
            from ..services.meta_webhook_service import MetaWebhookService
            wf_msgs = WorkflowEngine.process_workflow(client, to_number, body, channel or 'WHATSAPP')
            generated_responses = []
            if wf_msgs:
                phone_number_id = client.whatsapp_phone_number_id or 'WHATSAPP_SYSTEM'
                for w_item in wf_msgs:
                    auto_reply = None
                    if (channel or 'WHATSAPP').upper() == 'WHATSAPP':
                        try:
                            auto_reply = MetaWebhookService.send_whatsapp_message(
                                client=client,
                                to_number=to_number,
                                text_body=w_item.get('body', ''),
                                phone_number_id=phone_number_id,
                                buttons=w_item.get('buttons'),
                                media_url=w_item.get('media_url'),
                                media_type=w_item.get('type')
                            )
                        except Exception as _m_err:
                            print(f"Meta WhatsApp delivery exception: {_m_err}")

                    if not auto_reply:
                        auto_reply = MessageRepository.create_message(
                            client=client,
                            channel=channel or 'WHATSAPP',
                            from_address='WORKFLOW_BOT',
                            to_address=to_number,
                            body=w_item.get('body', ''),
                            message_type='OUTGOING',
                            status='SENT',
                            metadata={'buttons': w_item.get('buttons', []) or []}
                        )

                    generated_responses.append({
                        "id": str(auto_reply.id),
                        "from_address": auto_reply.from_address,
                        "to_address": auto_reply.to_address,
                        "body": auto_reply.body,
                        "channel": auto_reply.channel,
                        "message_type": auto_reply.message_type,
                        "status": auto_reply.status,
                        "buttons": getattr(auto_reply, 'buttons', []) or [],
                        "created_at": auto_reply.created_at
                    })

            return Response({
                "id": str(incoming_msg.id),
                "from_address": incoming_msg.from_address,
                "to_address": incoming_msg.to_address,
                "body": incoming_msg.body,
                "channel": incoming_msg.channel,
                "message_type": incoming_msg.message_type,
                "workflow_triggered": bool(wf_msgs),
                "auto_replies": generated_responses,
                "created_at": incoming_msg.created_at
            })
            
        # ── 1. Robust Target Resolution ──────────────────────────────────
        import re
        from bson import ObjectId
        target_dest = str(to_number or '').strip()
        contact = None
        convo = None

        # Check if target_dest is an ObjectId (Conversation or Contact ID)
        if ObjectId.is_valid(target_dest):
            contact = Contact.objects.filter(client=client, id=target_dest).first()
            if not contact:
                convo = Conversation.objects.filter(client=client, id=target_dest).first()
                if convo:
                    if convo.contact:
                        contact = convo.contact
                    if convo.contact_platform_id:
                        target_dest = str(convo.contact_platform_id)
                    if not channel and convo.channel:
                        channel = convo.channel

        # Search Contact by phone digits or platform_id
        if not contact:
            clean_digits = re.sub(r'\D', '', target_dest)
            contact_q = Q(platform_id=target_dest)
            if clean_digits:
                contact_q |= Q(phone_number__icontains=clean_digits) | Q(platform_id=clean_digits)
                if len(clean_digits) == 10:
                    contact_q |= Q(phone_number__icontains=f"91{clean_digits}")
            try:
                contact = Contact.objects.filter(Q(client=client) & contact_q).first()
            except Exception:
                pass

        # Derive channel and exact destination from Contact
        if contact:
            if not channel and getattr(contact, 'preferred_channel', None):
                channel = contact.preferred_channel
            if (channel or 'WHATSAPP').upper() == 'WHATSAPP':
                if contact.phone_number:
                    target_dest = contact.phone_number
                elif contact.platform_id:
                    target_dest = contact.platform_id
            else:
                if contact.platform_id:
                    target_dest = contact.platform_id
                elif contact.phone_number:
                    target_dest = contact.phone_number

        # Fallback channel detection
        if not channel:
            if '@' in target_dest:
                channel = 'GMAIL'
            else:
                last_msg = MessageRepository.filter_messages(client=client, from_address=target_dest).order_by('-created_at').first()
                if not last_msg:
                    last_msg = MessageRepository.filter_messages(client=client, to_address=target_dest).order_by('-created_at').first()
                channel = last_msg.channel if last_msg else 'WHATSAPP'
            
        channel = channel.upper()

        # Sanitize WhatsApp phone number: remove non-digits; if 10-digit, derive country code from client phone or default 91
        if channel == 'WHATSAPP':
            digits = re.sub(r'\D', '', str(target_dest))
            if len(digits) == 10:
                client_digits = re.sub(r'\D', '', str(getattr(client, 'phone_number', '') or ''))
                country_prefix = client_digits[:-10] if len(client_digits) > 10 else '91'
                target_dest = f"{country_prefix}{digits}"
            elif digits:
                target_dest = digits
        
        # Human agent takeover: Pause bot response for this contact
        if contact and not contact.bot_paused:
            try:
                contact.bot_paused = True
                contact.save()
            except Exception as e:
                print(f"Failed to auto-pause bot for contact: {str(e)}")
        
        new_msg = None
        
        if message_type == 'INTERNAL':
            sender_name = request.user.username if (request.user and request.user.is_authenticated) else 'Team Member'
            sender_avatar = f"https://api.dicebear.com/7.x/avataaars/svg?seed={sender_name}"
            new_msg = MessageRepository.create_message(
                client=client,
                channel=channel or 'WHATSAPP',
                from_address=sender_name,
                to_address=target_dest,
                body=body,
                message_type='INTERNAL',
                sender_name=sender_name,
                sender_avatar=sender_avatar,
                status='SENT'
            )
        elif channel == 'WHATSAPP':
            phone_number_id = client.whatsapp_phone_number_id or 'WHATSAPP_SYSTEM'
            webhook_view = WhatsAppWebhookView()
            try:
                new_msg = webhook_view.send_whatsapp_message(client, target_dest, body, phone_number_id)
            except Exception as _werr:
                new_msg = MessageRepository.create_message(
                    client=client,
                    channel='WHATSAPP',
                    from_address=phone_number_id,
                    to_address=target_dest,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
        elif channel in ['INSTAGRAM', 'FACEBOOK']:
            webhook_view = FacebookInstagramWebhookView()
            try:
                new_msg = webhook_view.send_message(client, channel, target_dest, body)
            except Exception as _ferr:
                new_msg = MessageRepository.create_message(
                    client=client,
                    channel=channel,
                    from_address=channel,
                    to_address=target_dest,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
        elif channel == 'GMAIL':
            from ..services.gmail_service import send_gmail_message
            try:
                send_gmail_message(client, target_dest, body)
                new_msg = MessageRepository.create_message(
                    client=client,
                    channel='GMAIL',
                    from_address=client.gmail_config.get('email_address', ''),
                    to_address=target_dest,
                    body=body,
                    message_type='OUTGOING',
                    status='SENT'
                )
            except Exception as e:
                return Response({"error": str(e)}, status=400)
        else:
            return Response({"error": f"Unsupported channel: {channel}"}, status=400)
            
        if new_msg:
            return Response({
                "id": str(new_msg.id),
                "from_address": new_msg.from_address,
                "to_address": new_msg.to_address,
                "body": new_msg.body,
                "channel": new_msg.channel,
                "message_type": new_msg.message_type,
                "status": new_msg.status,
                "buttons": getattr(new_msg, 'buttons', []) or [],
                "metadata": new_msg.metadata or {},
                "created_at": new_msg.created_at
            })
            
        return Response({"status": "sent"})
# Trusted Meta / WhatsApp CDN domains allowed for media proxying
ALLOWED_MEDIA_DOMAINS = {
    'graph.facebook.com',
    'lookaside.fbsbx.com',
    'pps.whatsapp.net',
    'mmg.whatsapp.net',
    'fbcdn.net',
}

def is_safe_media_url(target_url: str) -> bool:
    """
    Validates that target_url is strictly HTTPS and points exclusively to
    verified Meta/WhatsApp public CDN infrastructure, preventing SSRF attacks.
    """
    if not target_url or not isinstance(target_url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme != 'https':
            return False
            
        hostname = (parsed.hostname or '').lower().strip()
        if not hostname:
            return False

        # Validate domain against allowed Meta/WhatsApp CDN whitelist
        domain_allowed = any(
            hostname == allowed or hostname.endswith('.' + allowed)
            for allowed in ALLOWED_MEDIA_DOMAINS
        )
        if not domain_allowed:
            return False

        # Resolve hostname to IP and ensure it is not a private, loopback, or link-local address
        ip_addr = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip_addr)
        if (ip_obj.is_private or ip_obj.is_loopback or 
            ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast):
            return False

        return True
    except Exception as e:
        logger.warning("SSRF check rejected URL '%s': %s", target_url, e)
        return False


class MediaProxyView(APIView):
    """
    Secure proxy endpoint to stream WhatsApp/Meta media files to the frontend
    with strict SSRF defense, domain whitelisting, and Content-Type enforcement.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        media_id = request.query_params.get('media_id')
        media_url = request.query_params.get('media_url')
        
        client = get_tenant_client(request)
        token = getattr(client, 'whatsapp_access_token', None) if client else None

        # Resolve media_id via Meta Graph API if provided
        if media_id:
            # Validate media_id is alphanumeric to prevent path injection
            if not str(media_id).isalnum():
                return Response({"error": "Invalid media ID format."}, status=status.HTTP_400_BAD_REQUEST)

            if not token:
                return Response({"error": "WhatsApp credentials not configured for this client."}, status=status.HTTP_403_FORBIDDEN)

            try:
                graph_url = f"https://graph.facebook.com/v18.0/{media_id}"
                url_res = requests.get(
                    graph_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10
                )
                if url_res.status_code == 200:
                    media_url = url_res.json().get('url')
                else:
                    return Response({"error": "Failed to resolve media from Meta."}, status=url_res.status_code)
            except Exception as e:
                logger.error("Failed to query Meta Graph API for media_id %s: %s", media_id, e)
                return Response({"error": "Media lookup failed."}, status=status.HTTP_502_BAD_GATEWAY)

        if not media_url:
            return Response({"error": "media_id or media_url is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Enforce strict SSRF validation
        if not is_safe_media_url(media_url):
            logger.warning("Blocked potential SSRF attempt for URL: %s by user: %s", media_url, request.user.username if request.user else "Anonymous")
            return Response({"error": "Access to the requested URL is forbidden."}, status=status.HTTP_403_FORBIDDEN)

        try:
            # Only attach Bearer token if connecting to verified facebook.com endpoints
            parsed_host = (urllib.parse.urlparse(media_url).hostname or '').lower()
            attach_auth = bool(token and (parsed_host == 'graph.facebook.com' or parsed_host.endswith('.facebook.com')))
            headers = {"Authorization": f"Bearer {token}"} if attach_auth else {}

            file_res = requests.get(media_url, headers=headers, timeout=25, stream=True)
            if file_res.status_code == 200:
                content_type = file_res.headers.get('Content-Type', 'application/octet-stream')
                response = HttpResponse(file_res.content, content_type=content_type)
                
                # Security header to prevent MIME sniffing
                response['X-Content-Type-Options'] = 'nosniff'
                
                filename = request.query_params.get('filename')
                if filename:
                    # Sanitize filename
                    clean_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
                    response['Content-Disposition'] = f'inline; filename="{clean_filename}"'
                return response
            else:
                return Response({"error": "Failed to download upstream media."}, status=file_res.status_code)
        except Exception as e:
            logger.error("Failed downloading media from %s: %s", media_url, e)
            return Response({"error": "Media download failed."}, status=status.HTTP_502_BAD_GATEWAY)

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


