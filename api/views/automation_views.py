from ..services.admin_service import AdminService
from ..repositories.automation_repository import AutomationRepository
from ..repositories.workflow_repository import WorkflowRepository
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
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') if hasattr(request, 'query_params') else None
        if not client_id and isinstance(getattr(request, 'data', None), dict):
            client_id = request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except Exception:
                pass
        return getattr(request.user, 'client', None)
    return getattr(request.user, 'client', None)

class AutomationViewSet(viewsets.ModelViewSet):
    serializer_class = AutomationSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Automation.objects.none()
        return AutomationRepository.filter_automations(client=client)

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Automations', 'CREATE', after_value=str(serializer.data))

    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Automations', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Automations', 'DELETE', before_value=before_data)
        instance.delete()


class WorkflowViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Workflow.objects.none()
        return WorkflowRepository.filter_workflows(client=client)

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Workflows', 'CREATE', after_value=str(serializer.data))

    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Workflows', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Workflows', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=False, methods=['post'], url_path='upload_media')
    def upload_media(self, request):
        """
        POST /api/workflows/upload_media/
        Uploads image or video for workflow steps directly to Azure Blob Storage under:
        clients/client_{client_id}/workflows/{uuid}.{ext}
        """
        client = get_tenant_client(self.request)
        if not client:
            return Response({'error': 'Unauthorized tenant'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES.get('file') or request.FILES.get('media') or request.FILES.get('image') or request.FILES.get('video')
        if not file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        from ..services.media_storage_service import upload_tenant_media

        try:
            file_url, media_type, orig_name = upload_tenant_media(
                client_id=client.id,
                folder_name='workflows',
                file=file,
                max_size_mb=50
            )

            return Response({
                'status': 'success',
                'media_url': file_url,
                'media_type': media_type,
                'name': orig_name,
                'size': file.size
            }, status=status.HTTP_200_OK)
        except ValueError as val_err:
            return Response({'error': str(val_err)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Workflow media upload failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



