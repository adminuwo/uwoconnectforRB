from ..repositories.team_invite_repository import TeamInviteRepository
from ..repositories.team_message_repository import TeamMessageRepository
from ..repositories.user_repository import UserRepository
from ..repositories.client_repository import ClientRepository
from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets, serializers
from rest_framework.response import Response
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import (
    RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer,
    ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer,
    TeamInviteSerializer, ProductSerializer, OrderSerializer, ProjectSerializer, TaskSerializer, TaskCommentSerializer,
    WorkReportSerializer, WorkApprovalSerializer, TeamChannelSerializer, TeamChatMessageSerializer,
    AttendanceSerializer, LeaveRequestSerializer
)
from ..models import (
    User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, Template,
    Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order, Project, Task, TaskComment, WorkReport,
    WorkApproval, TeamChannel, TeamChatMessage, Attendance, LeaveRequest
)
from django.utils import timezone
from django.db.models import Q
import datetime

class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, 'client', None):
            return Task.objects.none()
        
        qs = Task.objects.filter(client=user.client, is_archived=False)
        
        # Filtering parameters
        status_param = self.request.query_params.get('status')
        priority_param = self.request.query_params.get('priority')
        department_param = self.request.query_params.get('department')
        assigned_param = self.request.query_params.get('assigned_to')
        search_query = self.request.query_params.get('search')
        
        if status_param:
            qs = qs.filter(status=status_param.upper())
        if priority_param:
            qs = qs.filter(priority=priority_param.upper())
        if department_param:
            qs = qs.filter(department__iexact=department_param)
        if assigned_param:
            qs = qs.filter(assigned_to__id=assigned_param)
        if search_query:
            qs = qs.filter(title__icontains=search_query)
            
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(client=user.client, created_by=user)

    @action(detail=True, methods=['post'])
    def toggle_checklist(self, request, pk=None):
        task = self.get_object()
        item_id = request.data.get('item_id')
        checklist = task.checklist or []
        
        for item in checklist:
            if str(item.get('id')) == str(item_id):
                item['completed'] = not item.get('completed', False)
                break
                
        task.checklist = checklist
        # Recalculate progress percentage
        if checklist:
            completed_count = sum(1 for i in checklist if i.get('completed'))
            task.progress_percentage = int((completed_count / len(checklist)) * 100)
            if task.progress_percentage == 100 and task.status not in ['COMPLETED', 'WAITING_APPROVAL']:
                task.status = 'UNDER_REVIEW'
        task.save()
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def submit_for_approval(self, request, pk=None):
        task = self.get_object()
        notes = request.data.get('notes', '')
        task.status = 'WAITING_APPROVAL'
        task.save()
        
        approval = WorkApproval.objects.create(
            task=task,
            employee=request.user,
            reviewer=task.created_by or request.user.reporting_manager,
            status='PENDING',
            submission_notes=notes
        )
        return Response({'task': TaskSerializer(task).data, 'approval_id': str(approval.id)})

    @action(detail=True, methods=['post'])
    def add_comment(self, request, pk=None):
        task = self.get_object()
        text = request.data.get('text')
        if not text:
            return Response({'error': 'Text is required'}, status=400)
        
        comment = TaskComment.objects.create(
            task=task,
            author=request.user,
            text=text,
            attachments=request.data.get('attachments', []),
            mentions=request.data.get('mentions', [])
        )
        return Response(TaskCommentSerializer(comment).data, status=201)

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        task = self.get_object()
        cloned_task = Task.objects.create(
            client=task.client,
            title=f"Copy of {task.title}",
            description=task.description,
            priority=task.priority,
            status='NOT_STARTED',
            created_by=request.user,
            department=task.department,
            estimated_hours=task.estimated_hours,
            checklist=task.checklist
        )
        cloned_task.assigned_to.set(task.assigned_to.all())
        return Response(TaskSerializer(cloned_task).data, status=201)


class WorkReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response([], status=200)
        
        qs = WorkReport.objects.filter(client=request.user.client)
        
        is_client = (
            request.user.role == 'CLIENT' or 
            request.user.enterprise_role == 'CLIENT' or 
            getattr(request.user, 'is_staff', False) or 
            getattr(request.user, 'is_superuser', False)
        )
        
        # If agent/employee, show reports of teammates in shared projects + their own
        if not is_client:
            user_projects = Project.objects.filter(client=request.user.client).filter(Q(members=request.user) | Q(owner=request.user))
            team_member_ids = set()
            for p in user_projects:
                team_member_ids.update(p.members.values_list('id', flat=True))
                if p.owner:
                    team_member_ids.add(p.owner.id)
            team_member_ids.add(request.user.id)
            qs = qs.filter(employee_id__in=team_member_ids)
            
        date_param = request.query_params.get('date')
        if date_param:
            qs = qs.filter(report_date=date_param)

        serializer = WorkReportSerializer(qs.order_by('-report_date', '-created_at'), many=True)
        return Response(serializer.data)

    def post(self, request):
        if not getattr(request.user, 'client', None):
            return Response({'error': 'No client associated'}, status=400)
            
        todays_work = request.data.get('todays_work')
        if not todays_work:
            return Response({'error': "Today's work details are required"}, status=400)
            
        report = WorkReport.objects.create(
            client=request.user.client,
            employee=request.user,
            report_date=request.data.get('report_date', timezone.now().date()),
            todays_work=todays_work,
            completed_work=request.data.get('completed_work', ''),
            remaining_work=request.data.get('remaining_work', ''),
            blockers=request.data.get('blockers', ''),
            need_help=request.data.get('need_help', False),
            next_steps=request.data.get('next_steps', ''),
            hours_worked=request.data.get('hours_worked', 8.0),
            attachments=request.data.get('attachments', [])
        )
        return Response(WorkReportSerializer(report).data, status=201)


class WorkApprovalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response([], status=200)
            
        qs = WorkApproval.objects.filter(task__client=request.user.client)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
            
        serializer = WorkApprovalSerializer(qs.order_by('-submitted_at'), many=True)
        return Response(serializer.data)

    def post(self, request):
        approval_id = request.data.get('approval_id')
        action_type = request.data.get('action') # APPROVE or REQUEST_CHANGES
        feedback = request.data.get('feedback', '')
        
        try:
            approval = WorkApproval.objects.get(id=approval_id, task__client=request.user.client)
        except WorkApproval.DoesNotExist:
            return Response({'error': 'Approval request not found'}, status=404)
            
        approval.reviewer = request.user
        approval.feedback_notes = feedback
        approval.reviewed_at = timezone.now()
        
        if action_type == 'APPROVE':
            approval.status = 'APPROVED'
            approval.task.status = 'COMPLETED'
            approval.task.progress_percentage = 100
            approval.task.save()
        else:
            approval.status = 'CHANGES_REQUESTED'
            approval.task.status = 'IN_PROGRESS'
            approval.task.save()
            
        approval.save()
        return Response(WorkApprovalSerializer(approval).data)


class TeamChannelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response([], status=200)
            
        client = request.user.client
        is_client_admin = request.user.role == 'CLIENT' or request.user.enterprise_role == 'CLIENT' or request.user.is_staff

        # Ensure default workspace channels exist
        if not TeamChannel.objects.filter(client=client, name='general').exists():
            TeamChannel.objects.create(
                client=client,
                name='general',
                description='Company wide discussions & updates',
                channel_type='PUBLIC',
                created_by=request.user
            )
        if not TeamChannel.objects.filter(client=client, name='announcements').exists():
            TeamChannel.objects.create(
                client=client,
                name='announcements',
                description='Official management announcements',
                channel_type='PUBLIC',
                created_by=request.user
            )

        # Sync active projects with project channels
        active_projects = list(Project.objects.filter(client=client))
        active_project_slugs = {}
        for p in active_projects:
            slug = f"proj-{p.name.strip().lower().replace(' ', '-')}"
            active_project_slugs[slug] = p
            ch, created = TeamChannel.objects.get_or_create(
                client=client,
                name=slug,
                defaults={
                    'description': f"Official discussion channel for {p.name}",
                    'channel_type': 'PUBLIC',
                    'created_by': request.user
                }
            )
            if created or not ch.members.exists():
                ch.members.set(p.members.all())

        # Clean up orphan project channels whose project was deleted
        for ch in TeamChannel.objects.filter(client=client, name__startswith='proj-'):
            if ch.name not in active_project_slugs:
                ch.delete()

        # Fetch channels
        all_channels = TeamChannel.objects.filter(client=client)

        if is_client_admin:
            visible_channels = all_channels
        else:
            # Employee / Agent: Show general channels + projects where user is member/owner
            user_projects = [p for p in active_projects if request.user in p.members.all() or p.owner == request.user]
            user_proj_slugs = set(f"proj-{p.name.strip().lower().replace(' ', '-')}" for p in user_projects)
            
            visible_channels = []
            for ch in all_channels:
                if not ch.name.startswith('proj-'):
                    visible_channels.append(ch)
                elif ch.name in user_proj_slugs:
                    visible_channels.append(ch)
            
        serializer = TeamChannelSerializer(visible_channels, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not getattr(request.user, 'client', None):
            return Response({'error': 'No client associated'}, status=400)
            
        name = request.data.get('name', '').strip().lower().replace(' ', '-')
        if not name:
            return Response({'error': 'Channel name is required'}, status=400)
            
        channel = TeamChannel.objects.create(
            client=request.user.client,
            name=name,
            description=request.data.get('description', ''),
            channel_type=request.data.get('channel_type', 'PUBLIC'),
            created_by=request.user
        )
        return Response(TeamChannelSerializer(channel).data, status=201)


class TeamChatMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        channel_id = request.query_params.get('channel_id')
        if not channel_id:
            return Response([], status=200)
            
        from bson import ObjectId
        from django.db.models import Q
        try:
            ch_oid = ObjectId(channel_id) if ObjectId.is_valid(channel_id) else None
        except Exception:
            ch_oid = None

        if ch_oid:
            messages = TeamChatMessage.objects.filter(Q(channel_id=channel_id) | Q(channel_id=ch_oid)).order_by('created_at')[:100]
        else:
            messages = TeamChatMessage.objects.filter(channel_id=channel_id).order_by('created_at')[:100]
            
        serializer = TeamChatMessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        channel_id = request.data.get('channel_id')
        text = request.data.get('text', '')
        if not channel_id or not text:
            return Response({'error': 'Channel ID and text are required'}, status=400)
            
        from bson import ObjectId
        from django.db.models import Q
        try:
            ch_oid = ObjectId(channel_id) if ObjectId.is_valid(channel_id) else None
        except Exception:
            ch_oid = None

        channel = None
        if ch_oid:
            channel = TeamChannel.objects.filter(Q(id=channel_id) | Q(id=ch_oid)).first()
        else:
            channel = TeamChannel.objects.filter(id=channel_id).first()

        if not channel:
            return Response({'error': 'Channel not found'}, status=404)
            
        message = TeamChatMessage.objects.create(
            channel=channel,
            sender=request.user,
            text=text,
            attachments=request.data.get('attachments', []),
            is_announcement=request.data.get('is_announcement', False)
        )
        return Response(TeamChatMessageSerializer(message).data, status=201)


class TeamAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response({'error': 'No client'}, status=400)
            
        client = request.user.client
        tasks = Task.objects.filter(client=client, is_archived=False)
        total_tasks = tasks.count()
        completed_tasks = tasks.filter(status='COMPLETED').count()
        in_progress_tasks = tasks.filter(status='IN_PROGRESS').count()
        blocked_tasks = tasks.filter(status='BLOCKED').count()
        under_review_tasks = tasks.filter(status__in=['UNDER_REVIEW', 'WAITING_APPROVAL']).count()
        
        completion_rate = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 100
        
        reports_count = WorkReport.objects.filter(client=client).count()
        members_count = User.objects.filter(client=client).count()
        
        return Response({
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'in_progress_tasks': in_progress_tasks,
            'blocked_tasks': blocked_tasks,
            'under_review_tasks': under_review_tasks,
            'completion_rate': completion_rate,
            'total_reports': reports_count,
            'total_members': members_count
        })


class TeamAICopilotView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        action_type = request.data.get('action') # GENERATE_TASK, SUMMARIZE_REPORTS, DETECT_BLOCKERS
        prompt_text = request.data.get('prompt', '')
        
        from ..services.ai_service import get_ai_response
        system_prompt = "You are a Senior Enterprise Project Manager and AI Productivity Copilot."
        
        if action_type == 'GENERATE_TASK':
            user_prompt = f"Generate a detailed task breakdown with checklist items for: {prompt_text}"
        elif action_type == 'SUMMARIZE_REPORTS':
            user_prompt = f"Summarize daily progress reports and highlight key achievements & blockers: {prompt_text}"
        else:
            user_prompt = f"Analyze blockers and suggest actionable solutions: {prompt_text}"
            
        ai_res = get_ai_response(system_prompt, user_prompt)
        return Response({'result': ai_res})
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

class TeamMemberViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'client', None):
            try:
                user.is_online = True
                user.last_active_at = timezone.now()
                user.save(update_fields=['is_online', 'last_active_at'])
            except Exception:
                pass
            return UserRepository.filter_users(client=user.client)
        return User.objects.none()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        now = timezone.now()
        user_map = {str(u.id): u for u in queryset}
        for item in data:
            u_id = str(item.get('id'))
            user_obj = user_map.get(u_id)
            if user_obj:
                is_active = getattr(user_obj, 'is_online', False)
                last_active = getattr(user_obj, 'last_active_at', None)
                if not is_active and last_active:
                    try:
                        if (now - last_active).total_seconds() < 300:
                            is_active = True
                    except Exception:
                        pass
                item['is_online'] = is_active
            else:
                item['is_online'] = False

        return Response(data)

    def create(self, request, *args, **kwargs):
        user = request.user
        if not getattr(user, 'client', None):
            return Response({"error": "No workspace client associated with current account."}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data.copy()
        email = data.get('email', '').strip().lower()
        name = data.get('name') or data.get('full_name') or data.get('username') or (email.split('@')[0] if email else 'User')
        raw_password = data.get('password') or 'UWOConnect123!'

        if not email:
            return Response({"error": "Email address is required."}, status=status.HTTP_400_BAD_REQUEST)

        data['email'] = email
        if 'username' not in data or not data['username']:
            data['username'] = email
        if 'first_name' not in data or not data['first_name']:
            data['first_name'] = name

        # Check if user already exists
        existing_user = User.objects.filter(email__iexact=email).first() or User.objects.filter(username__iexact=email).first()
        if existing_user:
            existing_user.client = user.client
            existing_user.status = 'APPROVED'
            existing_user.department = data.get('department', existing_user.department or 'General')
            existing_user.designation = data.get('designation', existing_user.designation or 'Team Member')
            if raw_password:
                existing_user.set_password(raw_password)
            existing_user.save()
            return Response(UserSerializer(existing_user).data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(client=user.client, status='APPROVED')
        instance.set_password(raw_password)
        instance.save()

        return Response(UserSerializer(instance).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise serializers.ValidationError("Cannot remove yourself from the team.")
        instance.delete()

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        member = self.get_object()
        if member == request.user:
            return Response({'error': 'Cannot suspend yourself'}, status=400)
        current_status = member.status
        member.status = 'SUSPENDED' if current_status != 'SUSPENDED' else 'APPROVED'
        member.save()
        return Response({'status': 'success', 'member_status': member.status, 'user': UserSerializer(member).data})

    @action(detail=True, methods=['post'])
    def update_permissions(self, request, pk=None):
        member = self.get_object()
        permission_matrix = request.data.get('permission_matrix')
        assigned_social_channels = request.data.get('assigned_social_channels')
        enterprise_role = request.data.get('enterprise_role')
        department = request.data.get('department')
        designation = request.data.get('designation')

        if permission_matrix is not None:
            member.permission_matrix = permission_matrix
        if assigned_social_channels is not None:
            member.assigned_social_channels = assigned_social_channels
        if enterprise_role:
            member.enterprise_role = enterprise_role
        if department:
            member.department = department
        if designation:
            member.designation = designation

        member.save()
        return Response({'status': 'success', 'user': UserSerializer(member).data})

    @action(detail=False, methods=['get'])
    def live_activity(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response([])
        members = User.objects.filter(client=client)
        data = []
        for m in members:
            data.append({
                'id': str(m.id),
                'username': m.username,
                'name': m.first_name or m.username,
                'email': m.email,
                'role': m.enterprise_role or m.role,
                'department': m.department,
                'is_online': m.is_online,
                'status': m.availability_status or ('ONLINE' if m.is_online else 'OFFLINE'),
                'current_page': m.current_page or '/client',
                'last_active_at': m.last_active_at,
                'last_login_ip': m.last_login_ip or '127.0.0.1',
                'last_login_browser': m.last_login_browser or 'Chrome / Windows'
            })
        return Response(data)

    @action(detail=False, methods=['get'])
    def login_monitoring(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response([])
        members = User.objects.filter(client=client)
        logs = []
        for m in members:
            history = m.login_history or [
                {
                    'login_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'ip': m.last_login_ip or '192.168.1.100',
                    'browser': m.last_login_browser or 'Chrome 125.0',
                    'os': m.last_login_os or 'Windows 11',
                    'location': 'Mumbai, India',
                    'status': 'SUCCESS',
                    'failed_attempts': 0
                }
            ]
            logs.append({
                'user_id': str(m.id),
                'username': m.username,
                'name': m.first_name or m.username,
                'email': m.email,
                'role': m.enterprise_role,
                'login_history': history
            })
        return Response(logs)

    @action(detail=False, methods=['get'])
    def connected_social_channels(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response([])
        channels = [
            {'id': 'wa_default', 'name': 'WhatsApp Business Main', 'type': 'WHATSAPP', 'icon': 'WhatsApp', 'details': client.phone_number or '+123456789'},
            {'id': 'ig_main', 'name': 'Instagram Business Account', 'type': 'INSTAGRAM', 'icon': 'Instagram', 'details': f"@{client.business_name.lower().replace(' ', '_')}"},
            {'id': 'fb_page', 'name': 'Facebook Official Page', 'type': 'FACEBOOK', 'icon': 'Facebook', 'details': f"{client.business_name} Page"},
            {'id': 'tg_support', 'name': 'Telegram Support Channel', 'type': 'TELEGRAM', 'icon': 'MessageSquare', 'details': '@uwosupport'},
            {'id': 'li_company', 'name': 'LinkedIn Company Page', 'type': 'LINKEDIN', 'icon': 'Globe', 'details': f"{client.business_name} Corporate"}
        ]
        return Response(channels)


class TeamInviteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response([], status=status.HTTP_200_OK)
        invites = TeamInviteRepository.filter_teaminvites(client=request.user.client)
        serializer = TeamInviteSerializer(invites, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not getattr(request.user, "client", None):
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        from ..services.team_service import TeamService
        result = TeamService.create_invite(request.user.client, email)
        return Response(result, status=status.HTTP_201_CREATED)

    def delete(self, request):
        if not getattr(request.user, "client", None):
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)
        invite_id = request.query_params.get("id")
        if not invite_id:
            return Response({"error": "ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        from ..services.team_service import TeamService
        success = TeamService.delete_invite(request.user.client, invite_id)
        if success:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"error": "Invite not found"}, status=status.HTTP_404_NOT_FOUND)

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from ..models import TeamMessage
from ..serializers import TeamMessageSerializer


class TeamChatView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not getattr(request.user, 'client', None):
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)
            
        messages = TeamMessageRepository.filter_teammessages(client=request.user.client).order_by('-created_at')[:50]
        # Return in chronological order
        serializer = TeamMessageSerializer(reversed(messages), many=True)
        return Response(serializer.data)

    def post(self, request):
        if not getattr(request.user, "client", None):
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)
        body = request.data.get("body")
        if not body:
            return Response({"error": "Body is required"}, status=status.HTTP_400_BAD_REQUEST)
        from ..services.team_service import TeamService
        result = TeamService.send_chat_message(request.user.client, request.user, body)
        return Response(result, status=status.HTTP_201_CREATED)


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, 'client', None):
            return Project.objects.none()
        qs = Project.objects.filter(client=user.client)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        user = self.request.user
        project = serializer.save(client=user.client, owner=user)
        members_data = self.request.data.get('members', [])
        if members_data:
            for m_id in members_data:
                try:
                    member_user = User.objects.filter(id=m_id).first()
                    if member_user:
                        project.members.add(member_user)
                except Exception:
                    pass
        # Create an associated project channel automatically
        channel_name = f"proj-{project.name.lower().replace(' ', '-')[:25]}"
        TeamChannel.objects.get_or_create(
            client=user.client,
            name=channel_name,
            defaults={
                'description': f"Official discussion channel for {project.name}",
                'channel_type': 'PUBLIC',
                'created_by': user
            }
        )

    def perform_update(self, serializer):
        project = serializer.save()
        if 'members' in self.request.data:
            members_data = self.request.data.get('members', [])
            project.members.clear()
            for m_id in members_data:
                try:
                    member_user = User.objects.filter(id=m_id).first()
                    if member_user:
                        project.members.add(member_user)
                except Exception:
                    pass

    def destroy(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        client = getattr(request.user, 'client', None)
        from bson import ObjectId
        from api.models import Project

        deleted = False
        if client:
            try:
                qs = Project.objects.filter(client=client, id=pk)
                if qs.exists():
                    qs.delete()
                    deleted = True
            except Exception:
                pass

            if not deleted and isinstance(pk, str) and len(pk) == 24:
                try:
                    qs = Project.objects.filter(client=client, id=ObjectId(pk))
                    if qs.exists():
                        qs.delete()
                        deleted = True
                except Exception:
                    pass

        if not deleted:
            try:
                qs = Project.objects.filter(id=pk)
                if qs.exists():
                    qs.delete()
                    deleted = True
            except Exception:
                pass

            if not deleted and isinstance(pk, str) and len(pk) == 24:
                try:
                    qs = Project.objects.filter(id=ObjectId(pk))
                    if qs.exists():
                        qs.delete()
                        deleted = True
                except Exception:
                    pass

        return Response(status=204)


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, 'client', None):
            return Attendance.objects.none()
        qs = Attendance.objects.filter(client=user.client)
        if user.enterprise_role in ['EMPLOYEE', 'INTERN']:
            qs = qs.filter(user=user)
        return qs.order_by('-date')

    @action(detail=False, methods=['post'])
    def clock_in(self, request):
        user = request.user
        if not getattr(user, 'client', None):
            return Response({'error': 'No client associated'}, status=400)
        today = timezone.now().date()
        attendance, created = Attendance.objects.get_or_create(
            client=user.client,
            user=user,
            date=today,
            defaults={'clock_in': timezone.now(), 'status': 'PRESENT'}
        )
        if not created and not attendance.clock_in:
            attendance.clock_in = timezone.now()
            attendance.status = 'PRESENT'
            attendance.save()
        return Response(AttendanceSerializer(attendance).data)

    @action(detail=False, methods=['post'])
    def clock_out(self, request):
        user = request.user
        today = timezone.now().date()
        try:
            attendance = Attendance.objects.get(client=user.client, user=user, date=today)
            attendance.clock_out = timezone.now()
            if attendance.clock_in:
                diff = (attendance.clock_out - attendance.clock_in).total_seconds() / 3600.0
                attendance.working_hours = round(diff, 2)
            attendance.save()
            return Response(AttendanceSerializer(attendance).data)
        except Attendance.DoesNotExist:
            return Response({'error': 'No clock-in record found for today'}, status=404)


class LeaveRequestViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, 'client', None):
            return LeaveRequest.objects.none()
        qs = LeaveRequest.objects.filter(client=user.client)
        if user.enterprise_role in ['EMPLOYEE', 'INTERN']:
            qs = qs.filter(user=user)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(client=self.request.user.client, user=self.request.user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave = self.get_object()
        action_type = request.data.get('action') # APPROVED or REJECTED
        leave.status = 'APPROVED' if action_type == 'APPROVED' else 'REJECTED'
        leave.reviewed_by = request.user
        leave.reviewed_at = timezone.now()
        leave.save()
        return Response(LeaveRequestSerializer(leave).data)


import uuid

class TeamInviteQRView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)
        
        now = timezone.now()
        invite = TeamInvite.objects.filter(
            client=client,
            is_qr=True,
            expires_at__gt=now
        ).order_by('-created_at').first()

        if not invite:
            token = uuid.uuid4().hex
            expires_at = now + datetime.timedelta(days=365)
            invite = TeamInvite.objects.create(
                client=client,
                email='',
                token=token,
                permissions=[],
                expires_at=expires_at,
                is_qr=True
            )

        return Response({
            "invite_token": invite.token,
            "business_name": client.business_name,
            "expires_at": invite.expires_at,
            "is_qr": True
        })

    def post(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            return Response({"error": "No client associated"}, status=status.HTTP_400_BAD_REQUEST)

        TeamInvite.objects.filter(client=client, is_qr=True).update(is_used=True)

        now = timezone.now()
        token = uuid.uuid4().hex
        expires_at = now + datetime.timedelta(days=365)
        invite = TeamInvite.objects.create(
            client=client,
            email='',
            token=token,
            permissions=[],
            expires_at=expires_at,
            is_qr=True
        )

        return Response({
            "invite_token": invite.token,
            "business_name": client.business_name,
            "expires_at": invite.expires_at,
            "is_qr": True
        }, status=status.HTTP_201_CREATED)


class TeamInviteValidateView(APIView):
    permission_classes = []

    def get(self, request):
        token = request.query_params.get('token', '').strip()
        if not token:
            return Response({"valid": False, "error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)

        from django.db.models import Q
        now = timezone.now()
        invite = TeamInvite.objects.filter(
            token=token,
            expires_at__gt=now
        ).filter(Q(is_used=False) | Q(is_qr=True)).first()

        if not invite:
            return Response({"valid": False, "error": "Invalid or expired invite token"}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "valid": True,
            "business_name": invite.client.business_name,
            "client_id": invite.client.id,
            "is_qr": invite.is_qr
        })





