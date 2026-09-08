from ..services.admin_service import AdminService
import threading
from ..repositories.template_repository import TemplateRepository
from ..repositories.campaign_repository import CampaignRepository
from ..repositories.client_repository import ClientRepository
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
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks
from rest_framework.permissions import BasePermission

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

class TemplateViewSet(viewsets.ModelViewSet):
    serializer_class = TemplateSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Template.objects.none()
        return TemplateRepository.filter_templates(client=client)

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Templates', 'CREATE', after_value=str(serializer.data))

    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Templates', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Templates', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=False, methods=['post'])
    def sync_from_meta(self, request):
        client = get_tenant_client(request) or request.user.client
        token = client.whatsapp_access_token
        if not client.whatsapp_waba_id or not token:
            return Response({"message": "WhatsApp WABA ID or Access Token is missing in client settings."}, status=400)
        
        url = f"https://graph.facebook.com/v19.0/{client.whatsapp_waba_id}/message_templates"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        try:
            res = requests.get(url, headers=headers)
            data = res.json()
            if 'data' in data:
                unique_keys = set()
                for tmpl in data['data']:
                    name = tmpl.get('name')
                    lang = tmpl.get('language')
                    if not name:
                        continue
                    Template.objects.update_or_create(
                        client=client,
                        name=name,
                        language=lang,
                        defaults={
                            'category': tmpl.get('category'),
                            'status': tmpl.get('status'),
                            'components': tmpl.get('components', [])
                        }
                    )
                    unique_keys.add((name, lang))
                synced_count = len(unique_keys)
                return Response({"message": f"Successfully synced {synced_count} unique approved templates from Meta."})
            return Response({"message": "Failed to fetch templates from Meta.", "details": data}, status=400)
        except Exception as e:
            return Response({"message": str(e)}, status=500)


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Campaign.objects.none()
        return CampaignRepository.filter_campaigns(client=client).order_by('-created_at')

    def perform_create(self, serializer):
        from django.utils import timezone
        client = get_tenant_client(self.request)

        # Resolve template from request data (support both 'template' and 'template_id' keys)
        template_id = self.request.data.get('template') or self.request.data.get('template_id')
        template_obj = None
        if template_id:
            try:
                template_obj = Template.objects.get(id=template_id)
            except Exception as ex:
                print(f"Error resolving template ID {template_id}: {ex}")

        # Determine channel and platforms
        platforms = self.request.data.get('platforms') or ['WHATSAPP']
        channel = self.request.data.get('channel') or (platforms[0] if platforms else 'WHATSAPP')

        scheduled_at = serializer.validated_data.get('scheduled_at')
        if scheduled_at and scheduled_at > timezone.now():
            campaign = serializer.save(client=client, template=template_obj, channel=channel, platforms=platforms, status='SCHEDULED')
        else:
            campaign = serializer.save(client=client, template=template_obj, channel=channel, platforms=platforms, status='SENDING')

        # Create optional follow-up
        delay_hours = self.request.data.get('followup_delay_hours')
        followup_template_id = self.request.data.get('followup_template_id')
        if delay_hours and followup_template_id:
            from ..models import CampaignFollowUp, Template
            fu_template = Template.objects.filter(id=followup_template_id, client=client).first()
            if fu_template:
                CampaignFollowUp.objects.create(
                    campaign=campaign,
                    delay_hours=int(delay_hours),
                    followup_template=fu_template
                )

        AdminService.log_admin_action(self.request, campaign, 'Campaigns', 'CREATE', after_value=str(serializer.data))
        if campaign.status == 'SENDING':
            thread = threading.Thread(target=self.process_campaign, args=(campaign.id,))
            thread.start()


    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Campaigns', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Campaigns', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=True, methods=['post'])
    def retry_failed(self, request, pk=None):
        campaign = self.get_object()
        contact_ids = request.data.get('contact_ids') # Optional list of specific contact IDs
        from ..services.campaign_service import CampaignService
        
        thread = threading.Thread(target=CampaignService.retry_failed_recipients, args=(campaign.id, contact_ids))
        thread.start()
        return Response({"message": "Retry process initiated for failed recipients."})

    @action(detail=False, methods=['post'])
    def ai_generate(self, request):
        prompt = request.data.get('prompt', '')
        action_type = request.data.get('action_type', 'generate') # generate, improve, translate, tone, fix_grammar
        tone = request.data.get('tone', 'professional')
        language = request.data.get('language', 'English')
        
        if not prompt:
            return Response({"error": "Prompt or message body is required"}, status=400)
            
        import re
        system_instruction = (
            "You are an expert copywriter. Output ONLY the raw final message/email body content. "
            "Never include preambles, introductory commentary (such as 'Certainly!', 'Here is a polished version:'), "
            "closing remarks (such as 'Feel free to...', 'Hope this helps!'), or wrapping quotation marks. "
            "Your entire output must be the message text itself, ready to send."
        )
        if action_type == 'improve':
            full_prompt = (
                f"Rewrite and polish this email message to be professional, clear, and engaging. "
                f"Output ONLY the final email body directly, with NO preambles, NO introductory commentary, and NO closing notes:\n\n{prompt}"
            )
        elif action_type == 'translate':
            full_prompt = f"Translate the following message accurately into {language}. Output ONLY the translated text:\n\n{prompt}"
        elif action_type == 'fix_grammar':
            full_prompt = f"Fix all spelling, punctuation, and grammar mistakes in this message while keeping its core meaning. Output ONLY the corrected text:\n\n{prompt}"
        elif action_type == 'tone':
            full_prompt = f"Rewrite this message in a {tone} tone. Output ONLY the rewritten text:\n\n{prompt}"
        else:
            full_prompt = f"Generate a compelling message based on this description. Output ONLY the message text:\n\n{prompt}"

        try:
            from ..services.ai_service import get_ai_response
            generated_text = get_ai_response(full_prompt, context=system_instruction)
            if not generated_text or "AI service is not configured" in generated_text:
                # Graceful smart polish fallback if OPENAI_API_KEY is not set
                cleaned = prompt.strip()
                if action_type == 'improve':
                    generated_text = f"Hello,\n\n{cleaned}\n\nBest regards,\nUWOConnect Team"
                elif action_type == 'fix_grammar':
                    generated_text = cleaned.capitalize()
                    if not generated_text.endswith(('.', '!', '?')):
                        generated_text += '.'
                else:
                    generated_text = cleaned
            else:
                # Clean any conversational preambles like "Certainly! Here's a polished version:"
                generated_text = re.sub(
                    r'^(?:certainly!?|sure!?|of course!?|here(?:[\'’]s| is| are)|below is)[\s\S]*?:(?:\r?\n)+',
                    '',
                    generated_text,
                    flags=re.IGNORECASE
                ).strip()
                # Clean any conversational closings like "Feel free to adjust any specifics!"
                generated_text = re.sub(
                    r'(?:\r?\n)+(?:feel free to|hope this helps|let me know if|please let me know|don\'t hesitate to)[\s\S]*$',
                    '',
                    generated_text,
                    flags=re.IGNORECASE
                ).strip()
                # Repeatedly clean divider lines (- or ---), bullets, and quotes
                changed = True
                while changed:
                    prev = generated_text
                    if generated_text.startswith("```"):
                        generated_text = re.sub(r'^```[a-zA-Z]*\n?', '', generated_text)
                        generated_text = re.sub(r'\n?```$', '', generated_text).strip()
                    generated_text = re.sub(r'^[-–—_*~•#\s]+(?:\r?\n)+', '', generated_text).strip()
                    generated_text = re.sub(r'^[-–—•]\s+', '', generated_text).strip()
                    if generated_text.startswith(('-', '–', '—')):
                        generated_text = re.sub(r'^[-–—_*~•\s]+', '', generated_text).strip()
                    generated_text = re.sub(r'(?:\r?\n)+[-–—_*~•#\s]+$', '', generated_text).strip()
                    if generated_text.endswith(('-', '–', '—')):
                        generated_text = re.sub(r'[-–—_*~•\s]+$', '', generated_text).strip()
                    if (generated_text.startswith('"') and generated_text.endswith('"')) or \
                       (generated_text.startswith('“') and generated_text.endswith('”')) or \
                       (generated_text.startswith("'") and generated_text.endswith("'")) or \
                       (generated_text.startswith('‘') and generated_text.endswith('’')):
                        generated_text = generated_text[1:-1].strip()
                    changed = (generated_text != prev)

            return Response({"result": generated_text, "action_type": action_type})
        except Exception as e:
            print(f"AI Generation View Error: {e}")
            cleaned = prompt.strip()
            fallback_res = f"Hello {{first_name}},\n\n{cleaned}\n\nExclusive broadcast update from UWOConnect!"
            return Response({"result": fallback_res, "action_type": action_type})

    def process_campaign(self, campaign_id):
        from ..services.campaign_service import CampaignService
        CampaignService.process_campaign(campaign_id)

