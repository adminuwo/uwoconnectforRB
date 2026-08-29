import os
import requests
from rest_framework import status, serializers, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework_simplejwt.tokens import RefreshToken
from ..permissions.custom_permissions import IsApprovedUser

from ..repositories.support_message_repository import SupportMessageRepository
from ..repositories.client_repository import ClientRepository
from ..repositories.system_repository import SystemRepository
from ..repositories.user_repository import UserRepository
from ..repositories.automation_repository import AutomationRepository
from ..repositories.message_repository import MessageRepository

from ..serializers import GlobalSettingSerializer, SupportMessageSerializer, AuditLogSerializer
from ..models import User, Client, Workflow, SupportMessage, GlobalSetting, AuditLog


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

class AdminStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response({
            "totalClients": Client.objects.count(),
            "activeAutomations": AutomationRepository.filter_automations(enabled=True).count(),
            "totalWorkflows": Workflow.objects.count(),
        })


class GlobalSettingsView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return []
        return [IsAdminUser()]

    def get(self, request):
        key = request.query_params.get('key')
        if key:
            setting = SystemRepository.filter_globalsettings(key=key).first()
            if setting:
                return Response(GlobalSettingSerializer(setting).data)
            return Response({"value": ""})
        
        settings = SystemRepository.get_all_globalsettings()
        return Response(GlobalSettingSerializer(settings, many=True).data)

    def post(self, request):
        key = request.data.get('key')
        value = request.data.get('value', '')
        file = request.FILES.get('file') or request.data.get('file')
        delete_file = request.data.get('delete_file') == 'true'
        
        setting, created = GlobalSetting.objects.update_or_create(
            key=key,
            defaults={'value': value}
        )
        
        if delete_file:
            setting.file = None
            setting.save()
        elif file and not isinstance(file, str):
            setting.file = file
            setting.save()
            
            # Extract text from file and update value automatically
            try:
                import docx
                import PyPDF2
                import io

                ext = os.path.splitext(file.name)[1].lower()
                extracted_text = ""

                if ext == '.docx':
                    doc = docx.Document(file)
                    # Join paragraphs with line breaks
                    extracted_text = "<br />".join([para.text for para in doc.paragraphs if para.text.strip()])
                elif ext == '.pdf':
                    pdf_reader = PyPDF2.PdfReader(file)
                    full_text = ""
                    for page in pdf_reader.pages:
                        full_text += page.extract_text() + "\n"
                    # Convert newlines to HTML line breaks
                    extracted_text = full_text.strip().replace('\n', '<br />')

                if extracted_text.strip():
                    setting.value = extracted_text
                    setting.save()
            except Exception as e:
                print(f"Error extracting text from file: {str(e)}")
            
        return Response(GlobalSettingSerializer(setting).data)


class AdminAutomationsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        autos = AutomationRepository.get_all_automations().select_related('client')
        data = []
        for auto in autos:
            data.append({
                "_id": str(auto.id),
                "clientId": auto.client.id if auto.client else None,
                "name": auto.name,
                "enabled": auto.enabled,
                "triggerType": auto.trigger_type,
                "clientName": auto.client.business_name if auto.client else "Unknown"
            })
        return Response(data)


class AdminMessagesView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        messages = MessageRepository.get_all_messages().select_related('client').order_by('-created_at')[:100]
        data = []
        for msg in messages:
            data.append({
                "id": str(msg.id),
                "_id": str(msg.id),
                "clientName": msg.client.business_name if msg.client else "Unknown",
                "from_address": msg.from_address,
                "to_address": msg.to_address,
                "body": msg.body,
                "channel": msg.channel,
                "message_type": msg.message_type,
                "status": msg.status,
                "created_at": msg.created_at
            })
        return Response(data)


class AdminUsersView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = UserRepository.filter_users(role='CLIENT').select_related('client').order_by('-date_joined')
        data = []
        for user in users:
            data.append({
                "id": str(user.id),
                "name": f"{user.first_name} {user.last_name}".strip() or user.username,
                "email": user.email,
                "status": user.status,
                "businessName": user.client.business_name if user.client else "N/A",
                "date_joined": user.date_joined
            })
        return Response(data)

    def patch(self, request, pk):
        try:
            user = User.objects.get(id=pk, role='CLIENT')
            status = request.data.get('status')
            if status in ['APPROVED', 'REJECTED', 'PENDING', 'SUSPENDED']:
                user.status = status
                user.save()
                return Response({"message": f"User {status.lower()} successfully."})
            return Response({"message": "Invalid status."}, status=400)
        except User.DoesNotExist:
            return Response({"message": "User not found."}, status=404)

    def delete(self, request, pk=None):
        # ── Delete a single user by pk ──────────────────────────────
        if pk:
            try:
                user = User.objects.get(id=pk, role='CLIENT')
                if user.client:
                    user.client.delete()   # cascade removes Client data
                user.delete()
                return Response({"message": "User deleted successfully."})
            except User.DoesNotExist:
                return Response({"message": "User not found."}, status=404)

        # ── Delete ALL client users ─────────────────────────────────
        delete_all = request.query_params.get('delete_all', '').lower()
        if delete_all == 'true':
            # Delete all associated Client objects first (cascade)
            ClientRepository.get_all_clients().delete()
            deleted_count, _ = UserRepository.filter_users(role='CLIENT').delete()
            return Response({
                "message": f"All {deleted_count} client users deleted successfully."
            })

        return Response({"message": "Provide a user pk or ?delete_all=true"}, status=400)


class SupportMessageViewSet(viewsets.ModelViewSet):
    serializer_class = SupportMessageSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            client_id = self.request.query_params.get('client_id')
            if client_id:
                try:
                    client = ClientRepository.get_client(id=client_id)
                    return SupportMessageRepository.filter_supportmessages(client=client)
                except Exception:
                    return SupportMessage.objects.none()
            return SupportMessageRepository.get_all_supportmessages()
        return SupportMessageRepository.filter_supportmessages(client=user.client)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == 'ADMIN':
            client_id = self.request.data.get('client_id')
            if not client_id:
                raise serializers.ValidationError({"client_id": "Required when sending as admin."})
            client = ClientRepository.get_client(id=client_id)
        else:
            client = user.client
        serializer.save(sender=user, client=client)

    @action(detail=False, methods=['get'], permission_classes=[IsAdminUser])
    def clients(self, request):
        from django.db.models import Max
        client_ids = SupportMessage.objects.values('client').annotate(latest_message=Max('created_at')).order_by('-latest_message')
        
        clients_data = []
        for item in client_ids:
            client_id = item['client']
            client = ClientRepository.filter_clients(id=client_id).first()
            if client:
                last_msg = SupportMessageRepository.filter_supportmessages(client=client).order_by('-created_at').first()
                clients_data.append({
                    "id": str(client.id),
                    "business_name": client.business_name,
                    "last_message_body": last_msg.body if last_msg else "",
                    "last_message_time": last_msg.created_at if last_msg else None,
                    "unread_count": 0
                })
        return Response(clients_data)


class AdminImpersonateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        is_admin = bool(
            request.user.role == 'ADMIN' or
            getattr(request.user, 'enterprise_role', None) == 'SUPER_ADMIN' or
            request.user.is_staff or
            request.user.is_superuser
        )
        if not is_admin:
            return Response({"error": "Only admins can impersonate clients."}, status=status.HTTP_403_FORBIDDEN)
            
        client_id = request.data.get('client_id')
        if not client_id:
            return Response({"error": "client_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            client = ClientRepository.get_client(id=client_id)
            user = UserRepository.filter_users(client=client, role='CLIENT').first() or UserRepository.filter_users(client=client).first()
            if not user:
                return Response({"error": "No user registered under this client node to impersonate."}, status=status.HTTP_404_NOT_FOUND)
                
            refresh = RefreshToken.for_user(user)
            refresh['impersonator_id'] = str(request.user.id)
            refresh['impersonator_username'] = request.user.username
            refresh['impersonated_client_id'] = str(client.id)
            refresh['impersonated_client_name'] = client.business_name

            # Audit Log
            try:
                AuditLog.objects.create(
                    admin_name=request.user.username,
                    client_name=client.business_name,
                    module="WORKSPACE_ACCESS",
                    action="SUPER_ADMIN_IMPERSONATE",
                    before_value="Admin Control Center",
                    after_value=f"Impersonating Client #{client.id} ({client.business_name})",
                    ip_address=request.META.get('REMOTE_ADDR') or '127.0.0.1'
                )
            except Exception:
                pass

            client_plan = client.plan or 'ADVANCED'
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "plan": client_plan,
                    "client_plan": client_plan,
                    "client_id": str(client.id),
                    "business_name": client.business_name,
                    "client": {
                        "id": str(client.id),
                        "business_name": client.business_name,
                        "plan": client_plan
                    }
                },
                "impersonating": {
                    "impersonator_name": request.user.username,
                    "target_client_id": str(client.id),
                    "target_client_name": client.business_name,
                    "target_client_plan": client_plan
                }
            }, status=status.HTTP_200_OK)
        except Client.DoesNotExist:
            return Response({"error": "Client node not found."}, status=status.HTTP_404_NOT_FOUND)



class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SystemRepository.get_all_auditlogs()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != 'ADMIN':
            return AuditLog.objects.none()
            
        queryset = SystemRepository.get_all_auditlogs()
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(admin_name__icontains=search) |
                Q(client_name__icontains=search) |
                Q(module__icontains=search) |
                Q(action__icontains=search)
            )
        module = self.request.query_params.get('module')
        if module:
            queryset = queryset.filter(module=module)
            
        return queryset


