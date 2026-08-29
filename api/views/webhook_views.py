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

@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        from ..services.meta_webhook_service import MetaWebhookService
        return MetaWebhookService.verify_whatsapp_webhook(mode, token, challenge)

    def post(self, request):
        from ..services.meta_webhook_service import MetaWebhookService
        result = MetaWebhookService.handle_whatsapp_message(request.data)
        if result["status_code"] == 200:
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        return Response({"status": "error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def send_whatsapp_message(self, client, to_number, text_body, phone_number_id):
        from ..services.meta_webhook_service import MetaWebhookService
        return MetaWebhookService.send_whatsapp_message(client, to_number, text_body, phone_number_id)


@method_decorator(csrf_exempt, name='dispatch')
class FacebookInstagramWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        from ..services.meta_webhook_service import MetaWebhookService
        return MetaWebhookService.verify_fb_ig_webhook(mode, token, challenge)

    def post(self, request):
        from ..services.meta_webhook_service import MetaWebhookService
        result = MetaWebhookService.handle_fb_ig_message(request.data)
        if result["status_code"] == 200:
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        return Response({"status": "error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def send_message(self, client, platform, recipient_id, text_body):
        from ..services.meta_webhook_service import MetaWebhookService
        return MetaWebhookService.send_fb_ig_message(client, platform, recipient_id, text_body)

from ..services.ai_service import get_ai_draft


