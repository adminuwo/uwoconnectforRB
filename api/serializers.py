from rest_framework import serializers
from .models import User, Client, Automation, Workflow, GlobalSetting, Contact, Template, Campaign, SupportMessage, AuditLog, TeamInvite, KnowledgeDocument, TeamMessage, Product, Order, ProductPayment, Project, Task, TaskComment, WorkReport, WorkApproval, TeamChannel, TeamChatMessage, Attendance, LeaveRequest, Message, Conversation, ConversationAuditLog, Guide, GuideSection, GuideStep, GuideProgress, EmailAccount, EmailMessage, EmailAutoReplyRule, EmailAutomationWorkflow, EmailTeamNote, SalesDocumentTemplate, SalesDocument, SalesDocumentItem, SalesDocumentActivity, Invoice
from .repositories.contact_repository import ContactRepository
from .repositories.workflow_repository import WorkflowRepository
from .repositories.automation_repository import AutomationRepository
from .repositories.user_repository import UserRepository
from .repositories.team_invite_repository import TeamInviteRepository
from .repositories.client_repository import ClientRepository

class ObjectIdField(serializers.Field):
    """
    Custom field that serializes MongoDB ObjectId to a plain string
    and deserializes a string back to an ObjectId-compatible value.
    """
    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        return data


class ClientSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    _id = serializers.SerializerMethodField()
    total_contacts = serializers.SerializerMethodField()
    total_workflows = serializers.SerializerMethodField()
    total_bots = serializers.SerializerMethodField()
    onedrive_config = serializers.SerializerMethodField()
    google_calendar_config = serializers.SerializerMethodField()
    google_sheets_config = serializers.SerializerMethodField()
    google_docs_config = serializers.SerializerMethodField()
    google_slides_config = serializers.SerializerMethodField()
    zoho_config = serializers.SerializerMethodField()
    email = serializers.EmailField(write_only=True, required=False)

    class Meta:
        model = Client
        fields = '__all__'

    def create(self, validated_data):
        email = validated_data.pop('email', None)
        client = Client.objects.create(**validated_data)
        if email:
            email_clean = email.lower().strip()
            if not User.objects.filter(username=email_clean).exists() and not User.objects.filter(email=email_clean).exists():
                User.objects.create_user(
                    username=email_clean,
                    email=email_clean,
                    password="UwoConnect@123",
                    first_name=client.business_name,
                    role='CLIENT',
                    status='PENDING',
                    client=client
                )
        return client

    def get__id(self, obj):
        return str(obj.id)

    def get_total_contacts(self, obj):
        return getattr(obj, 'contact_count', 0)

    def get_total_workflows(self, obj):
        return getattr(obj, 'workflow_count', 0)

    def get_total_bots(self, obj):
        return getattr(obj, 'automation_count', 0)

    def get_onedrive_config(self, obj):
        """Return OneDrive config without sensitive OAuth tokens."""
        config = obj.onedrive_config or {}
        safe_keys = {
            'account_name', 'account_email', 'drive_id', 'drive_name',
            'drive_type', 'storage_total', 'storage_used', 'web_url',
            'last_sync_time', 'connected_at', 'synced_count',
            'pending_count', 'failed_count',
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_google_calendar_config(self, obj):
        """Return Google Calendar config without sensitive OAuth tokens."""
        config = obj.google_calendar_config or {}
        safe_keys = {
            'account_email', 'primary_calendar_id', 'timezone',
            'auto_sync_whatsapp', 'auto_sync_crm', 'default_duration',
            'last_sync_time', 'connected_at', 'events_count',
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_google_sheets_config(self, obj):
        """Return Google Sheets config without sensitive OAuth tokens."""
        config = obj.google_sheets_config or {}
        safe_keys = {
            'account_email', 'spreadsheet_id', 'spreadsheet_name',
            'sheet_name', 'spreadsheet_url', 'auto_export_leads',
            'auto_export_orders', 'auto_export_crm', 'rows_synced',
            'last_sync_time', 'connected_at',
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_google_docs_config(self, obj):
        """Return Google Docs config without sensitive OAuth tokens."""
        config = obj.google_docs_config or {}
        safe_keys = {
            'account_email', 'default_doc_id', 'default_doc_name',
            'default_doc_url', 'auto_generate_summaries',
            'auto_generate_receipts', 'docs_created_count',
            'last_sync_time', 'connected_at', 'recent_docs',
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_google_slides_config(self, obj):
        """Return Google Slides config without sensitive OAuth tokens."""
        config = obj.google_slides_config or {}
        safe_keys = {
            'account_email', 'default_presentation_id', 'default_presentation_name',
            'default_presentation_url', 'auto_generate_pitch_decks',
            'auto_generate_catalog_decks', 'presentations_created_count',
            'last_sync_time', 'connected_at', 'recent_presentations',
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_zoho_config(self, obj):
        """Return Zoho config without sensitive OAuth tokens."""
        config = obj.zoho_config or {}
        safe_keys = {
            'account_email', 'domain', 'connected_at', 'last_sync_time'
        }
        return {k: v for k, v in config.items() if k in safe_keys}


class UserSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    name = serializers.CharField(source='first_name', required=False)
    reporting_manager_name = serializers.ReadOnlyField(source='reporting_manager.username')

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'name', 'first_name', 'role', 'enterprise_role', 'department',
            'designation', 'phone_number', 'reporting_manager', 'reporting_manager_name', 'status', 'client',
            'permissions', 'assigned_platforms', 'assigned_social_channels', 'permission_matrix',
            'employee_id', 'joining_date', 'working_hours', 'salary_visibility', 'skills',
            'availability_status', 'is_online', 'last_active_at', 'timezone', 'language',
            'current_page', 'last_login_ip', 'last_login_browser', 'last_login_os', 'login_history'
        )
        extra_kwargs = {'password': {'write_only': True}}

class TeamInviteSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = TeamInvite
        fields = '__all__'
        read_only_fields = ('client', 'token', 'created_at', 'is_used')


class AutomationSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Automation
        fields = '__all__'
        read_only_fields = ('client',)


class WorkflowSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Workflow
        fields = '__all__'
        read_only_fields = ('client',)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    name = serializers.CharField()
    businessName = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.CharField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    designation = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    brand_domain = serializers.CharField(required=False, allow_blank=True)
    termsAccepted = serializers.BooleanField(required=False, default=True)

    def validate_email(self, value):
        email = value.lower().strip()
        if UserRepository.filter_users(email=email).exists() or UserRepository.filter_users(username=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_termsAccepted(self, value):
        if value is False:
            raise serializers.ValidationError("Please accept the Terms & Conditions and Privacy Policy to continue.")
        return value

    def create(self, validated_data):
        from django.utils import timezone
        email = validated_data['email'].lower().strip()
        business_name = validated_data.get('businessName', f"{validated_data['name']}'s Business")
        invite_token = validated_data.get('invite_token')
        phone_number = validated_data.get('phone_number', '').strip()
        designation = validated_data.get('designation', '').strip() or 'Team Member'
        department = validated_data.get('department', '').strip() or 'General'
        brand_domain = validated_data.get('brand_domain', '').strip().lower()
        now = timezone.now()

        if invite_token:
            from django.db.models import Q
            invite = TeamInvite.objects.filter(
                token=invite_token, 
                expires_at__gt=now
            ).filter(Q(is_used=False) | Q(is_qr=True)).first()
            
            if not invite:
                raise serializers.ValidationError({"invite_token": "Invalid or expired invite token."})
                
            user = User.objects.create_user(
                username=email,
                email=email,
                password=validated_data['password'],
                first_name=validated_data['name'],
                phone_number=phone_number,
                employee_id=phone_number,
                designation=designation,
                department=department,
                role='AGENT',
                enterprise_role='EMPLOYEE',
                status='APPROVED',
                client=invite.client,
                permissions=invite.permissions,
                terms_accepted=True,
                privacy_accepted=True,
                terms_version='1.0',
                terms_accepted_at=now
            )
            
            if not invite.is_qr:
                invite.is_used = True
                invite.save()
            return user
        else:
            parent_agency = None
            if brand_domain:
                parent_agency = Client.objects.filter(white_label_domain__iexact=brand_domain).first()

            client = Client.objects.create(
                business_name=business_name,
                phone_number=phone_number,
                parent_agency=parent_agency,
                settings={
                    "registered_domain": brand_domain,
                    "parent_agency_id": str(parent_agency.id) if parent_agency else None
                } if parent_agency else {}
            )
    
            user = User.objects.create_user(
                username=email,
                email=email,
                password=validated_data['password'],
                first_name=validated_data['name'],
                phone_number=phone_number,
                designation=designation,
                department=department,
                role='CLIENT',
                status='PENDING',
                client=client,
                terms_accepted=True,
                privacy_accepted=True,
                terms_version='1.0',
                terms_accepted_at=now
            )
            return user


class GlobalSettingSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = GlobalSetting
        fields = '__all__'

class ContactSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Contact
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

class ContactListSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    preferred_channel = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = ('id', 'name', 'phone_number', 'email', 'platform_id', 'stage', 'tags', 'bot_paused', 'is_archived', 'updated_at', 'created_at', 'preferred_channel')

    def get_preferred_channel(self, obj):
        name = (obj.name or '').upper()
        pid = (obj.platform_id or '').lower()
        
        if 'INSTAGRAM' in name or pid.startswith('ig') or 'instagram' in pid:
            return 'INSTAGRAM'
        elif 'FACEBOOK' in name or pid.startswith('fb') or 'facebook' in pid:
            return 'FACEBOOK'
        elif '@' in pid:
            return 'GMAIL'
        else:
            return 'WHATSAPP'

class TemplateSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Template
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

class CampaignSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    template = serializers.PrimaryKeyRelatedField(queryset=Template.objects.all(), required=False, allow_null=True)
    has_followup = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

    def get_has_followup(self, obj):
        return hasattr(obj, 'follow_up') and obj.follow_up.is_active

class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    
    class Meta:
        model = KnowledgeDocument
        fields = '__all__'
        read_only_fields = ('client', 'uploaded_at', 'status')

class SupportMessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    sender = ObjectIdField(read_only=True)
    sender_name = serializers.ReadOnlyField(source='sender.username')
    sender_role = serializers.ReadOnlyField(source='sender.role')

    class Meta:
        model = SupportMessage
        fields = '__all__'
        read_only_fields = ('sender', 'client')

class AuditLogSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'

class TeamMessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    sender = ObjectIdField(read_only=True)
    sender_name = serializers.ReadOnlyField(source='sender.username')
    sender_role = serializers.ReadOnlyField(source='sender.role')

    class Meta:
        model = TeamMessage
        fields = '__all__'
        read_only_fields = ('sender', 'client', 'created_at')


class ProductSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ('client',)


class OrderSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    contact_name = serializers.ReadOnlyField(source='contact.name')
    contact_phone = serializers.ReadOnlyField(source='contact.phone_number')

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ('client',)


class TaskCommentSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    author_name = serializers.ReadOnlyField(source='author.username')
    author_role = serializers.ReadOnlyField(source='author.enterprise_role')

    class Meta:
        model = TaskComment
        fields = '__all__'
        read_only_fields = ('author', 'created_at')


class TaskSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    created_by_name = serializers.ReadOnlyField(source='created_by.username')
    comments = TaskCommentSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = '__all__'
        read_only_fields = ('client', 'created_by', 'created_at', 'updated_at')


class WorkReportSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    employee = ObjectIdField(read_only=True)
    employee_name = serializers.ReadOnlyField(source='employee.username')
    employee_full_name = serializers.SerializerMethodField()
    employee_department = serializers.ReadOnlyField(source='employee.department')
    employee_role = serializers.ReadOnlyField(source='employee.enterprise_role')

    class Meta:
        model = WorkReport
        fields = '__all__'
        read_only_fields = ('client', 'employee', 'created_at')

    def get_employee_full_name(self, obj):
        if obj.employee:
            return f"{obj.employee.first_name} {obj.employee.last_name}".strip() or obj.employee.username
        return 'Team Member'


class WorkApprovalSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    task_title = serializers.ReadOnlyField(source='task.title')
    employee_name = serializers.ReadOnlyField(source='employee.username')
    reviewer_name = serializers.ReadOnlyField(source='reviewer.username')

    class Meta:
        model = WorkApproval
        fields = '__all__'
        read_only_fields = ('employee', 'submitted_at', 'reviewed_at')


class TeamChannelSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    created_by = ObjectIdField(read_only=True)
    members = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = TeamChannel
        fields = '__all__'
        read_only_fields = ('client', 'created_by', 'created_at')

    def get_members(self, obj):
        try:
            return [str(m.id) for m in obj.members.all()]
        except Exception:
            return []

    def get_member_count(self, obj):
        try:
            return obj.members.count()
        except Exception:
            return 0


class TeamChatMessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    channel = ObjectIdField(read_only=True)
    sender = ObjectIdField(read_only=True)
    sender_name = serializers.ReadOnlyField(source='sender.username')
    sender_role = serializers.ReadOnlyField(source='sender.enterprise_role')

    class Meta:
        model = TeamChatMessage
        fields = '__all__'
        read_only_fields = ('sender', 'created_at')


class ProjectSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    owner = ObjectIdField(read_only=True)
    owner_name = serializers.ReadOnlyField(source='owner.username')
    members = serializers.SerializerMethodField()
    task_count = serializers.SerializerMethodField()
    members_details = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ('client', 'owner', 'created_at', 'updated_at')

    def get_members(self, obj):
        try:
            return [str(m.id) for m in obj.members.all()]
        except Exception:
            return []

    def get_task_count(self, obj):
        try:
            return obj.tasks.count()
        except Exception:
            return 0

    def get_members_details(self, obj):
        try:
            return [{
                "id": str(m.id),
                "username": m.username,
                "name": f"{m.first_name} {m.last_name}".strip() or m.username,
                "email": m.email,
                "department": m.department,
                "role": m.enterprise_role or m.role,
                "is_online": getattr(m, 'is_online', False)
            } for m in obj.members.all()]
        except Exception:
            return []


class AttendanceSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    user_name = serializers.ReadOnlyField(source='user.username')
    user_email = serializers.ReadOnlyField(source='user.email')
    user_department = serializers.ReadOnlyField(source='user.department')

    class Meta:
        model = Attendance
        fields = '__all__'
        read_only_fields = ('client', 'user', 'created_at')


class LeaveRequestSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    user_name = serializers.ReadOnlyField(source='user.username')
    reviewer_name = serializers.ReadOnlyField(source='reviewed_by.username')

    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ('client', 'user', 'created_at')


class ConversationSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_avatar = serializers.SerializerMethodField()
    locked_by_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    contact_phone = serializers.SerializerMethodField()

    def get_assigned_to_name(self, obj):
        if obj.assigned_to:
            full = f"{getattr(obj.assigned_to, 'first_name', '') or ''} {getattr(obj.assigned_to, 'last_name', '') or ''}".strip()
            return full or getattr(obj.assigned_to, 'username', None) or getattr(obj.assigned_to, 'email', None)
        return None

    def get_locked_by_name(self, obj):
        if obj.locked_by:
            full = f"{getattr(obj.locked_by, 'first_name', '') or ''} {getattr(obj.locked_by, 'last_name', '') or ''}".strip()
            return full or getattr(obj.locked_by, 'username', None) or getattr(obj.locked_by, 'email', None)
        return None

    class Meta:
        model = Conversation
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

    def get_assigned_to_avatar(self, obj):
        if obj.assigned_to and hasattr(obj.assigned_to, 'username'):
            return f"https://api.dicebear.com/7.x/avataaars/svg?seed={obj.assigned_to.username}"
        return None

    def get_contact_name(self, obj):
        if obj.contact:
            return obj.contact.name or obj.contact.phone_number or obj.contact_platform_id
        return obj.contact_platform_id

    def get_contact_phone(self, obj):
        if obj.contact:
            return obj.contact.phone_number
        return None


class ConversationAuditLogSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = ConversationAuditLog
        fields = '__all__'
        read_only_fields = ('client', 'created_at')


class MessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = Message
        fields = '__all__'
        read_only_fields = ('client', 'created_at')


class GuideStepSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = GuideStep
        fields = '__all__'


class GuideSectionSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    steps = GuideStepSerializer(many=True, read_only=True)

    class Meta:
        model = GuideSection
        fields = '__all__'


class GuideListSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    total_sections = serializers.SerializerMethodField()
    total_steps = serializers.SerializerMethodField()

    class Meta:
        model = Guide
        fields = ['id', 'slug', 'title', 'icon', 'category', 'status', 'description', 'estimated_time', 'order', 'language', 'version', 'total_sections', 'total_steps']

    def get_total_sections(self, obj):
        return obj.sections.count()

    def get_total_steps(self, obj):
        return GuideStep.objects.filter(section__guide=obj).count()


class GuideDetailSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    sections = GuideSectionSerializer(many=True, read_only=True)

    class Meta:
        model = Guide
        fields = '__all__'


class GuideProgressSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = GuideProgress
        fields = '__all__'
        read_only_fields = ('user',)


# ── ENTERPRISE EMAIL CENTER SERIALIZERS ────────────────────────────────────

class EmailAccountSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = EmailAccount
        fields = '__all__'
        read_only_fields = ('client', 'created_at')


class EmailTeamNoteSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    author_name = serializers.CharField(source='author.first_name', read_only=True)

    class Meta:
        model = EmailTeamNote
        fields = '__all__'
        read_only_fields = ('author', 'created_at')


class EmailMessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.first_name', read_only=True)
    account_provider = serializers.CharField(source='account.provider', read_only=True)
    team_notes = EmailTeamNoteSerializer(many=True, read_only=True)

    class Meta:
        model = EmailMessage
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')


class EmailAutoReplyRuleSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = EmailAutoReplyRule
        fields = '__all__'
        read_only_fields = ('client', 'created_at')


class EmailAutomationWorkflowSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    assign_user_name = serializers.CharField(source='assign_user.first_name', read_only=True)

    class Meta:
        model = EmailAutomationWorkflow
        fields = '__all__'
        read_only_fields = ('client', 'created_at')


class SalesDocumentTemplateSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)

    class Meta:
        model = SalesDocumentTemplate
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')


class SalesDocumentItemSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = SalesDocumentItem
        fields = '__all__'


class SalesDocumentActivitySerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = SalesDocumentActivity
        fields = '__all__'
        read_only_fields = ('created_at',)


class SalesDocumentSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    items = SalesDocumentItemSerializer(many=True, read_only=True)
    activities = SalesDocumentActivitySerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    salesperson_name = serializers.CharField(source='salesperson.username', read_only=True)
    customer_details = serializers.SerializerMethodField(read_only=True)
    client_details = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SalesDocument
        fields = '__all__'
        read_only_fields = ('client', 'created_by', 'document_number', 'secure_token', 'version', 'created_at', 'updated_at')

    def get_customer_details(self, obj):
        if obj.customer:
            return {
                'id': str(obj.customer.id),
                'name': obj.customer.name,
                'email': obj.customer.email,
                'phone_number': obj.customer.phone_number,
            }
        return None

    def get_client_details(self, obj):
        if obj.company_details and isinstance(obj.company_details, dict) and obj.company_details.get('business_name'):
            return obj.company_details
        
        client = obj.client
        if client:
            return {
                'business_name': client.business_name,
                'company_logo_url': getattr(client, 'company_logo_url', '') or '',
                'phone_number': getattr(client, 'phone_number', '') or '',
                'email': (client.users.first().email if client.users.exists() else '') if hasattr(client, 'users') else '',
                'address': getattr(client, 'address', '') or '',
                'tax_id_gstin': getattr(client, 'tax_id_gstin', '') or '',
                'invoice_prefix': getattr(client, 'invoice_prefix', 'INV') or 'INV',
                'website': getattr(client, 'website', '') or '',
            }
        return {}


class InvoiceSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    order = serializers.CharField(source='order_id', required=False, allow_null=True)
    contact = serializers.CharField(source='contact_id', required=False, allow_null=True)
    payment_record = serializers.CharField(source='payment_record_id', required=False, allow_null=True)
    invoice_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')


class InvoiceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            'invoice_prefix', 'invoice_next_number', 'company_logo_url',
            'tax_id_gstin', 'invoice_default_notes', 'payment_terms', 'invoice_footer'
        ]






