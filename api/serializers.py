import re
from rest_framework import serializers
from django.utils import timezone
from .models import User, Client, Automation, Workflow, GlobalSetting, Contact, ContactFollowUp, Template, Campaign, SupportMessage, AuditLog, TeamInvite, KnowledgeDocument, TeamMessage, Product, Order, ProductPayment, Project, Task, TaskComment, WorkReport, WorkApproval, TeamChannel, TeamChatMessage, Attendance, LeaveRequest, Message, Conversation, ConversationAuditLog, Guide, GuideSection, GuideStep, GuideProgress, EmailAccount, EmailMessage, EmailAutoReplyRule, EmailAutomationWorkflow, EmailTeamNote, EmailAutomationSettings, EmailAutomationLog, SalesDocumentTemplate, SalesDocument, SalesDocumentItem, SalesDocumentActivity, Invoice, UserLegalConsent, LegalDocumentVersion, CompetitorAnalysis, ContactMessage, ContactMessageReply, UserFeedback, UserFeedbackReply, InAppNotification
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
        if value is None:
            return None
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
    google_drive_config = serializers.SerializerMethodField()
    zoho_config = serializers.SerializerMethodField()
    is_verification_account = serializers.SerializerMethodField()
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
                user = User.objects.create_user(
                    username=email_clean,
                    email=email_clean,
                    password="UwoConnect@123",
                    first_name=client.business_name,
                    role='CLIENT',
                    status='PENDING',
                    client=client
                )
                try:
                    from .services.welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user, temp_password="UwoConnect@123")
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")
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

    def get_google_drive_config(self, obj):
        """Return Google Drive config without sensitive OAuth tokens."""
        config = getattr(obj, 'google_drive_config', {}) or {}
        safe_keys = {
            'account_email', 'connected_at', 'last_sync_time', 'files_count', 'root_folder_id'
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_zoho_config(self, obj):
        """Return Zoho config without sensitive OAuth tokens."""
        config = obj.zoho_config or {}
        safe_keys = {
            'account_email', 'domain', 'connected_at', 'last_sync_time'
        }
        return {k: v for k, v in config.items() if k in safe_keys}

    def get_is_verification_account(self, obj):
        """Returns True if this client is designated for Google OAuth verification testing."""
        try:
            from .services.google_oauth_service import is_google_verification_account
            return is_google_verification_account(obj)
        except Exception:
            return False


class UserSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    name = serializers.SerializerMethodField()
    reporting_manager_name = serializers.ReadOnlyField(source='reporting_manager.username')

    def get_name(self, obj):
        full = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return full or obj.first_name or obj.username or obj.email or ''

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'name', 'first_name', 'last_name', 'role', 'enterprise_role', 'department',
            'designation', 'phone_number', 'reporting_manager', 'reporting_manager_name', 'status', 'client',
            'permissions', 'assigned_platforms', 'assigned_social_channels', 'permission_matrix',
            'employee_id', 'joining_date', 'working_hours', 'salary_visibility', 'skills',
            'availability_status', 'is_online', 'last_active_at', 'timezone', 'language',
            'current_page', 'last_login_ip', 'last_login_browser', 'last_login_os', 'login_history',
            'meta_portfolio_eligible', 'meta_portfolio_name', 'email_verified', 'email_verified_at'
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
    name = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    business_name = serializers.CharField(required=False, allow_blank=True)
    businessName = serializers.CharField(required=False, allow_blank=True)
    invite_token = serializers.CharField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    designation = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    brand_domain = serializers.CharField(required=False, allow_blank=True)
    termsAccepted = serializers.BooleanField(required=False, default=None)
    terms_accepted = serializers.BooleanField(required=False, default=None)
    privacy_accepted = serializers.BooleanField(required=False, default=None)
    terms_version = serializers.CharField(required=False, default='1.0')
    privacy_version = serializers.CharField(required=False, default='1.0')
    meta_portfolio_eligible = serializers.BooleanField(required=False, default=None)
    metaPortfolioEligible = serializers.BooleanField(required=False, default=None)
    meta_portfolio_name = serializers.CharField(required=False, allow_blank=True)
    portfolio_name = serializers.CharField(required=False, allow_blank=True)
    portfolioName = serializers.CharField(required=False, allow_blank=True)

    # Registration Analytics & Device Tracking fields (Optional from client)
    platform = serializers.CharField(required=False, allow_blank=True)
    registration_platform = serializers.CharField(required=False, allow_blank=True)
    device_type = serializers.CharField(required=False, allow_blank=True)
    device_model = serializers.CharField(required=False, allow_blank=True)
    os_name = serializers.CharField(required=False, allow_blank=True)
    os_version = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)
    country_code = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    location = serializers.CharField(required=False, allow_blank=True)
    registration_method = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        email = value.lower().strip()
        if UserRepository.filter_users(email=email).exists() or UserRepository.filter_users(username=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_password(self, value):
        from .utils.password_validator import validate_password_strength
        is_valid, errors = validate_password_strength(value)
        if not is_valid:
            raise serializers.ValidationError(errors[0] if len(errors) == 1 else " ".join(errors))
        return value

    def validate(self, attrs):
        # Resolve name and businessName from alternate field names
        if not attrs.get('name'):
            fn = attrs.get('first_name', '').strip()
            ln = attrs.get('last_name', '').strip()
            attrs['name'] = f"{fn} {ln}".strip() or attrs.get('email', '')
        if not attrs.get('businessName') and attrs.get('business_name'):
            attrs['businessName'] = attrs.get('business_name')

        # Enforce explicit Terms & Conditions and Privacy Policy acceptance
        terms_ok = attrs.get('terms_accepted')
        if terms_ok is None:
            terms_ok = attrs.get('termsAccepted')
        privacy_ok = attrs.get('privacy_accepted')
        if privacy_ok is None:
            privacy_ok = terms_ok

        if terms_ok is not True or privacy_ok is not True:
            raise serializers.ValidationError({
                "terms_accepted": "You must agree to both the Terms & Conditions and Privacy Policy to register."
            })

        # Resolve Meta Portfolio Name
        portfolio_name = (
            attrs.get('meta_portfolio_name') or 
            attrs.get('metaPortfolioName') or 
            attrs.get('portfolio_name') or 
            attrs.get('portfolioName') or ''
        ).strip()
        attrs['meta_portfolio_name'] = portfolio_name

        # Enforce Meta Portfolio Eligibility Gate for new registrations (anti-bypass)
        is_eligible = attrs.get('meta_portfolio_eligible')
        if is_eligible is None:
            is_eligible = attrs.get('metaPortfolioEligible')

        if is_eligible is not True:
            raise serializers.ValidationError({
                "meta_portfolio_eligible": "Meta Portfolio is required to register for Uwo Connect."
            })

        # Require Meta Portfolio Name for new account signups (exempt invitees)
        if not attrs.get('invite_token') and not portfolio_name:
            raise serializers.ValidationError({
                "meta_portfolio_name": "Meta Portfolio name is required."
            })
        return attrs

    def create(self, validated_data):
        from django.utils import timezone
        from .utils.registration_tracker import extract_registration_meta

        email = validated_data['email'].lower().strip()
        business_name = validated_data.get('businessName', f"{validated_data['name']}'s Business")
        invite_token = validated_data.get('invite_token')
        phone_number = validated_data.get('phone_number', '').strip()
        designation = validated_data.get('designation', '').strip() or 'Team Member'
        department = validated_data.get('department', '').strip() or 'General'
        brand_domain = validated_data.get('brand_domain', '').strip().lower()
        now = timezone.now()

        # Extract registration tracking metadata
        request_obj = self.context.get('request') if hasattr(self, 'context') else None
        reg_meta = extract_registration_meta(
            request=request_obj,
            payload=validated_data,
            signup_method=validated_data.get('registration_method') or 'email'
        )

        if invite_token:
            from django.db.models import Q
            invite = TeamInvite.objects.filter(
                token=invite_token, 
                expires_at__gt=now
            ).filter(Q(is_used=False) | Q(is_qr=True)).first()
            
            if not invite:
                raise serializers.ValidationError({"invite_token": "Invalid or expired invite token."})
                
            terms_ver = validated_data.get('terms_version') or '1.0'
            privacy_ver = validated_data.get('privacy_version') or '1.0'
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
                meta_portfolio_eligible=True,
                client=invite.client,
                permissions=invite.permissions,
                terms_accepted=True,
                privacy_accepted=True,
                terms_version=terms_ver,
                terms_accepted_at=now,
                privacy_version=privacy_ver,
                privacy_accepted_at=now,
                **reg_meta
            )
            try:
                UserLegalConsent.objects.create(
                    user=user,
                    document_type='TERMS',
                    document_version=terms_ver
                )
                UserLegalConsent.objects.create(
                    user=user,
                    document_type='PRIVACY_POLICY',
                    document_version=privacy_ver
                )
            except Exception:
                pass
            
            if not invite.is_qr:
                invite.is_used = True
                invite.save()
            return user
        else:
            parent_agency = None
            if brand_domain:
                parent_agency = Client.objects.filter(white_label_domain__iexact=brand_domain).first()

            meta_portfolio_name = validated_data.get('meta_portfolio_name', '').strip()
            client_settings = {
                "registered_domain": brand_domain,
                "parent_agency_id": str(parent_agency.id) if parent_agency else None
            } if parent_agency else {}
            if meta_portfolio_name:
                client_settings["meta_portfolio_name"] = meta_portfolio_name
                client_settings["business_portfolio_name"] = meta_portfolio_name

            client = Client.objects.create(
                business_name=business_name,
                meta_portfolio_name=meta_portfolio_name,
                phone_number=phone_number,
                parent_agency=parent_agency,
                settings=client_settings
            )
    
            terms_ver = validated_data.get('terms_version') or '1.0'
            privacy_ver = validated_data.get('privacy_version') or '1.0'
            user = User.objects.create_user(
                username=email,
                email=email,
                password=validated_data['password'],
                first_name=validated_data['name'],
                phone_number=phone_number,
                designation=designation,
                department=department,
                role='CLIENT',
                status='APPROVED',
                meta_portfolio_eligible=True,
                meta_portfolio_name=meta_portfolio_name,
                client=client,
                terms_accepted=True,
                privacy_accepted=True,
                terms_version=terms_ver,
                terms_accepted_at=now,
                privacy_version=privacy_ver,
                privacy_accepted_at=now,
                **reg_meta
            )
            try:
                UserLegalConsent.objects.create(
                    user=user,
                    document_type='TERMS',
                    document_version=terms_ver
                )
                UserLegalConsent.objects.create(
                    user=user,
                    document_type='PRIVACY_POLICY',
                    document_version=privacy_ver
                )
            except Exception:
                pass
            return user


class GlobalSettingSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = GlobalSetting
        fields = '__all__'

class ContactFollowUpSerializer(serializers.ModelSerializer):
    """Serializer for industrial CRM follow-up tasks per contact."""
    id = ObjectIdField(read_only=True)
    contact = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    is_overdue = serializers.ReadOnlyField()

    class Meta:
        model = ContactFollowUp
        fields = (
            'id', 'contact', 'client', 'created_by', 'created_by_name',
            'follow_up_type', 'title', 'note',
            'scheduled_at', 'completed_at', 'status', 'is_overdue',
            'created_at', 'updated_at',
        )
        read_only_fields = ('contact', 'client', 'created_by', 'completed_at', 'created_at', 'updated_at')

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.full_name or obj.created_by.email or 'Unknown'
        return None


class ContactSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    platform_id = serializers.CharField(required=False)
    preferred_channel = serializers.SerializerMethodField()
    follow_ups_count = serializers.SerializerMethodField()
    next_followup_at = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'phone' in data and not data.get('phone_number'):
            data['phone_number'] = data.pop('phone')
        if not data.get('platform_id'):
            data['platform_id'] = data.get('phone_number') or data.get('email') or f"contact_{timezone.now().strftime('%Y%m%d%H%M%S')}"
        return super().to_internal_value(data)

    def validate_phone_number(self, value):
        if not value:
            return value
        cleaned = str(value).strip()
        if not cleaned:
            return cleaned
        has_plus = cleaned.startswith('+')
        digits = re.sub(r'\D', '', cleaned)
        if len(digits) < 7 or len(digits) > 15:
            raise serializers.ValidationError("Phone number must contain between 7 and 15 digits (e.g. +919876543210).")
        if set(digits) == {'0'}:
            raise serializers.ValidationError("Phone number cannot consist solely of zeroes.")
        return f"+{digits}" if has_plus else digits

    def validate_notes(self, value):
        if value and len(value) > 10000:
            raise serializers.ValidationError("Notes cannot exceed 10,000 characters.")
        return value

    def get_preferred_channel(self, obj):
        try:
            convo = obj.conversations.first()
            if convo and convo.channel:
                return convo.channel
        except Exception:
            pass
        name = (obj.name or '').upper()
        pid = (obj.platform_id or '').lower()
        if 'INSTAGRAM' in name or name.startswith('@') or pid.startswith('ig') or 'instagram' in pid:
            return 'INSTAGRAM'
        elif 'FACEBOOK' in name or pid.startswith('fb') or 'facebook' in pid:
            return 'FACEBOOK'
        elif 'YOUTUBE' in name or pid.startswith('yt') or 'youtube' in pid:
            return 'YOUTUBE'
        elif '@' in pid and not name.startswith('@'):
            return 'GMAIL'
        return 'WHATSAPP'

    def get_follow_ups_count(self, obj):
        return obj.follow_ups.filter(status='PENDING').count()

    def get_next_followup_at(self, obj):
        nxt = obj.follow_ups.filter(status='PENDING').order_by('scheduled_at').first()
        return nxt.scheduled_at.isoformat() if nxt else None


class ContactListSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    preferred_channel = serializers.SerializerMethodField()
    follow_ups_count = serializers.SerializerMethodField()
    next_followup_at = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = (
            'id', 'name', 'phone_number', 'email', 'platform_id', 'stage',
            'tags', 'bot_paused', 'is_archived', 'updated_at', 'created_at',
            'preferred_channel', 'follow_ups_count', 'next_followup_at',
        )

    def get_preferred_channel(self, obj):
        try:
            convo = obj.conversations.first()
            if convo and convo.channel:
                return convo.channel
        except Exception:
            pass
        name = (obj.name or '').upper()
        pid = (obj.platform_id or '').lower()
        
        if 'INSTAGRAM' in name or name.startswith('@') or pid.startswith('ig') or 'instagram' in pid:
            return 'INSTAGRAM'
        elif 'FACEBOOK' in name or pid.startswith('fb') or 'facebook' in pid:
            return 'FACEBOOK'
        elif 'YOUTUBE' in name or pid.startswith('yt') or 'youtube' in pid:
            return 'YOUTUBE'
        elif '@' in pid and not name.startswith('@'):
            return 'GMAIL'
        else:
            return 'WHATSAPP'

    def get_follow_ups_count(self, obj):
        if hasattr(obj, 'pending_followups'):
            return len(obj.pending_followups)
        return obj.follow_ups.filter(status='PENDING').count()

    def get_next_followup_at(self, obj):
        if hasattr(obj, 'pending_followups'):
            nxt = obj.pending_followups[0] if obj.pending_followups else None
            return nxt.scheduled_at.isoformat() if nxt else None
        nxt = obj.follow_ups.filter(status='PENDING').order_by('scheduled_at').first()
        return nxt.scheduled_at.isoformat() if nxt else None

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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get('image_url'):
            from .services.media_storage_service import sign_azure_url
            data['image_url'] = sign_azure_url(data['image_url'])
        return data


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
    author_name = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = '__all__'
        read_only_fields = ('author', 'created_at')

    def get_author_name(self, obj):
        try:
            return obj.author.username if getattr(obj, 'author_id', None) and obj.author else 'Team Member'
        except Exception:
            return 'Team Member'

    def get_author_role(self, obj):
        try:
            return obj.author.enterprise_role or obj.author.role if getattr(obj, 'author_id', None) and obj.author else 'EMPLOYEE'
        except Exception:
            return 'EMPLOYEE'


class TaskSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    comments = TaskCommentSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = '__all__'
        read_only_fields = ('client', 'created_by', 'created_at', 'updated_at')

    def get_created_by_name(self, obj):
        try:
            return obj.created_by.username if getattr(obj, 'created_by_id', None) and obj.created_by else 'Admin'
        except Exception:
            return 'Admin'


class WorkReportSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    employee = ObjectIdField(read_only=True)
    employee_name = serializers.SerializerMethodField()
    employee_full_name = serializers.SerializerMethodField()
    employee_department = serializers.SerializerMethodField()
    employee_role = serializers.SerializerMethodField()

    class Meta:
        model = WorkReport
        fields = '__all__'
        read_only_fields = ('client', 'employee', 'created_at')

    def get_employee_name(self, obj):
        try:
            return obj.employee.username if getattr(obj, 'employee_id', None) and obj.employee else 'Team Member'
        except Exception:
            return 'Team Member'

    def get_employee_full_name(self, obj):
        try:
            if getattr(obj, 'employee_id', None) and obj.employee:
                return f"{obj.employee.first_name} {obj.employee.last_name}".strip() or obj.employee.username
        except Exception:
            pass
        return 'Team Member'

    def get_employee_department(self, obj):
        try:
            return obj.employee.department if getattr(obj, 'employee_id', None) and obj.employee else 'General'
        except Exception:
            return 'General'

    def get_employee_role(self, obj):
        try:
            return obj.employee.enterprise_role or obj.employee.role if getattr(obj, 'employee_id', None) and obj.employee else 'EMPLOYEE'
        except Exception:
            return 'EMPLOYEE'


class WorkApprovalSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    task_title = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkApproval
        fields = '__all__'
        read_only_fields = ('employee', 'submitted_at', 'reviewed_at')

    def get_task_title(self, obj):
        try:
            return obj.task.title if getattr(obj, 'task_id', None) and obj.task else ''
        except Exception:
            return ''

    def get_employee_name(self, obj):
        try:
            return obj.employee.username if getattr(obj, 'employee_id', None) and obj.employee else 'Team Member'
        except Exception:
            return 'Team Member'

    def get_reviewer_name(self, obj):
        try:
            return obj.reviewer.username if getattr(obj, 'reviewer_id', None) and obj.reviewer else 'Reviewer'
        except Exception:
            return 'Reviewer'


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
    sender_name = serializers.SerializerMethodField()
    sender_role = serializers.SerializerMethodField()

    class Meta:
        model = TeamChatMessage
        fields = '__all__'
        read_only_fields = ('sender', 'created_at')

    def get_sender_name(self, obj):
        try:
            return obj.sender.username if getattr(obj, 'sender_id', None) and obj.sender else 'Member'
        except Exception:
            return 'Member'

    def get_sender_role(self, obj):
        try:
            return obj.sender.enterprise_role or obj.sender.role if getattr(obj, 'sender_id', None) and obj.sender else 'EMPLOYEE'
        except Exception:
            return 'EMPLOYEE'


class ProjectSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    owner = ObjectIdField(read_only=True)
    owner_name = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    task_count = serializers.SerializerMethodField()
    members_details = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ('client', 'owner', 'created_at', 'updated_at')

    def get_owner_name(self, obj):
        try:
            return obj.owner.username if getattr(obj, 'owner_id', None) and obj.owner else 'Project Lead'
        except Exception:
            return 'Project Lead'

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
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    user_department = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = '__all__'
        read_only_fields = ('client', 'user', 'created_at')

    def get_user_name(self, obj):
        try:
            return obj.user.username if getattr(obj, 'user_id', None) and obj.user else 'Member'
        except Exception:
            return 'Member'

    def get_user_email(self, obj):
        try:
            return obj.user.email if getattr(obj, 'user_id', None) and obj.user else ''
        except Exception:
            return ''

    def get_user_department(self, obj):
        try:
            return obj.user.department if getattr(obj, 'user_id', None) and obj.user else 'General'
        except Exception:
            return 'General'


class LeaveRequestSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    user_name = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ('client', 'user', 'created_at')

    def get_user_name(self, obj):
        try:
            return obj.user.username if getattr(obj, 'user_id', None) and obj.user else 'Member'
        except Exception:
            return 'Member'

    def get_reviewer_name(self, obj):
        try:
            return obj.reviewed_by.username if getattr(obj, 'reviewed_by_id', None) and obj.reviewed_by else 'Reviewer'
        except Exception:
            return 'Reviewer'


class ConversationSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_avatar = serializers.SerializerMethodField()
    locked_by_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    contact_phone = serializers.SerializerMethodField()
    contact_email = serializers.SerializerMethodField()
    bot_paused = serializers.SerializerMethodField()

    def get_client(self, obj):
        fields_cache = getattr(getattr(obj, '_state', None), 'fields_cache', {})
        if 'client' in fields_cache:
            client_obj = fields_cache['client']
            return str(client_obj) if client_obj else None
        client_id = getattr(obj, 'client_id', None)
        return str(client_id) if client_id else None

    def get_assigned_to_name(self, obj):
        user = getattr(obj, 'assigned_to', None) if getattr(obj, 'assigned_to_id', None) else None
        if user:
            full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
            return full or getattr(user, 'username', None) or getattr(user, 'email', None)
        return None

    def get_locked_by_name(self, obj):
        user = getattr(obj, 'locked_by', None) if getattr(obj, 'locked_by_id', None) else None
        if user:
            full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
            return full or getattr(user, 'username', None) or getattr(user, 'email', None)
        return None

    class Meta:
        model = Conversation
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')

    def get_assigned_to_avatar(self, obj):
        user = getattr(obj, 'assigned_to', None) if getattr(obj, 'assigned_to_id', None) else None
        if user and hasattr(user, 'username'):
            return f"https://api.dicebear.com/7.x/avataaars/svg?seed={user.username}"
        return None

    def get_contact_name(self, obj):
        contact = getattr(obj, 'contact', None) if getattr(obj, 'contact_id', None) else None
        
        # If not directly linked by contact_id, try to resolve Contact by platform_id or phone
        if not contact and obj.contact_platform_id and getattr(obj, 'client_id', None):
            try:
                from ..models import Contact
                raw_pid = str(obj.contact_platform_id).strip()
                contact = Contact.objects.filter(client_id=obj.client_id, platform_id=raw_pid).first()
                if not contact:
                    contact = Contact.objects.filter(client_id=obj.client_id, phone_number=raw_pid).first()
                if not contact and raw_pid.isdigit():
                    contact = Contact.objects.filter(client_id=obj.client_id, phone_number=f"+{raw_pid}").first()
                if not contact and raw_pid.startswith('+'):
                    contact = Contact.objects.filter(client_id=obj.client_id, phone_number=raw_pid.lstrip('+')).first()
            except Exception:
                contact = None

        if contact:
            name = (contact.name or '').strip()
            is_hex = len(name) == 24 and all(c in '0123456789abcdefABCDEF' for c in name)
            # If name is generic, hex ID, or 'Unknown', prefer phone number or formatted platform id
            if is_hex or not name or name.upper() in ['UNKNOWN', 'UNKNOWN USER', 'USER', 'CUSTOMER', 'NONE', 'NULL', 'UNDEFINED']:
                phone = contact.phone_number or obj.contact_platform_id
                if phone:
                    clean_phone = str(phone).strip()
                    is_p_hex = len(clean_phone) == 24 and all(c in '0123456789abcdefABCDEF' for c in clean_phone)
                    if not is_p_hex:
                        if not clean_phone.startswith('+') and clean_phone.isdigit() and len(clean_phone) >= 10:
                            return f"+{clean_phone}"
                        return clean_phone
                return 'Customer'
            return name

        raw_id = str(obj.contact_platform_id or '').strip()
        is_raw_hex = len(raw_id) == 24 and all(c in '0123456789abcdefABCDEF' for c in raw_id)
        if is_raw_hex:
            return 'Customer'
        if raw_id and raw_id.isdigit() and len(raw_id) >= 10 and not raw_id.startswith('+'):
            return f"+{raw_id}"
        return raw_id or 'Customer'

    def get_contact_phone(self, obj):
        contact = getattr(obj, 'contact', None) if getattr(obj, 'contact_id', None) else None
        if not contact and obj.contact_platform_id and getattr(obj, 'client_id', None):
            try:
                from ..models import Contact
                raw_pid = str(obj.contact_platform_id).strip()
                contact = Contact.objects.filter(client_id=obj.client_id, platform_id=raw_pid).first()
                if not contact:
                    contact = Contact.objects.filter(client_id=obj.client_id, phone_number=raw_pid).first()
            except Exception:
                contact = None

        if contact and contact.phone_number:
            return contact.phone_number
        raw_id = str(obj.contact_platform_id or '').strip()
        is_raw_hex = len(raw_id) == 24 and all(c in '0123456789abcdefABCDEF' for c in raw_id)
        if not is_raw_hex and raw_id and (raw_id.startswith('+') or raw_id.isdigit()):
            return raw_id if raw_id.startswith('+') else f"+{raw_id}"
        return None

    def get_contact_email(self, obj):
        contact = getattr(obj, 'contact', None) if getattr(obj, 'contact_id', None) else None
        if not contact and obj.contact_platform_id and getattr(obj, 'client_id', None):
            try:
                from ..models import Contact
                raw_pid = str(obj.contact_platform_id).strip()
                contact = Contact.objects.filter(client_id=obj.client_id, platform_id=raw_pid).first()
                if not contact:
                    contact = Contact.objects.filter(client_id=obj.client_id, phone_number=raw_pid).first()
            except Exception:
                contact = None

        if contact and contact.email:
            return contact.email
        return None

    def get_bot_paused(self, obj):
        contact = getattr(obj, 'contact', None) if getattr(obj, 'contact_id', None) else None
        if contact:
            return bool(contact.bot_paused)
        return False



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


class EmailAutomationSettingsSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    account_email = serializers.CharField(source='account.email_address', read_only=True)

    class Meta:
        model = EmailAutomationSettings
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')


class EmailAutomationLogSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    rule_name = serializers.CharField(source='rule_applied.name', read_only=True)
    workflow_name = serializers.CharField(source='workflow_applied.name', read_only=True)

    class Meta:
        model = EmailAutomationLog
        fields = '__all__'
        read_only_fields = ('client', 'created_at', 'updated_at')



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
    document_date = serializers.DateField(required=False, default=timezone.now().date)
    issue_date = serializers.DateField(source='document_date', required=False)
    total_amount = serializers.DecimalField(source='grand_total', max_digits=12, decimal_places=2, required=False)
    items = SalesDocumentItemSerializer(many=True, read_only=True)
    activities = SalesDocumentActivitySerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    salesperson_name = serializers.CharField(source='salesperson.username', read_only=True)
    customer_details = serializers.SerializerMethodField(read_only=True)
    client_details = serializers.SerializerMethodField(read_only=True)

    def to_internal_value(self, data):
        ret = super().to_internal_value(data)
        if 'notes' in data and not ret.get('customer_notes'):
            ret['customer_notes'] = data['notes']
        if 'total_amount' in data and not ret.get('grand_total'):
            ret['grand_total'] = data['total_amount']
        if 'total_tax' in data and not ret.get('tax_amount'):
            ret['tax_amount'] = data['total_tax']
        if 'document_date' not in ret or not ret.get('document_date'):
            ret['document_date'] = timezone.now().date()
        return ret

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
    order = serializers.CharField(source='order_id', required=False, allow_null=True, allow_blank=True)
    contact = serializers.CharField(source='contact_id', required=False, allow_null=True, allow_blank=True)
    payment_record = serializers.CharField(source='payment_record_id', required=False, allow_null=True, allow_blank=True)
    invoice_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_order(self, value):
        if not value or not str(value).strip():
            return None
        return value

    def validate_contact(self, value):
        if not value or not str(value).strip():
            return None
        return value

    def validate_payment_record(self, value):
        if not value or not str(value).strip():
            return None
        return value

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        decimal_fields = ['subtotal', 'discount', 'shipping', 'tax', 'total', 'amount_paid', 'balance_due']
        for f in decimal_fields:
            if f in data and data[f] is not None:
                try:
                    data[f] = round(float(data[f]), 2)
                except (ValueError, TypeError):
                    pass
        return super().to_internal_value(data)

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


class CompetitorAnalysisSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    _id = serializers.SerializerMethodField()
    client_name = serializers.CharField(source='client.business_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = CompetitorAnalysis
        fields = '__all__'
        read_only_fields = ('client', 'created_by', 'status', 'created_at', 'updated_at')

    def get__id(self, obj):
        return str(obj.id)


class ContactMessageReplySerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    contact_message = ObjectIdField(read_only=True)
    sender = ObjectIdField(read_only=True)
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = ContactMessageReply
        fields = ['id', 'contact_message', 'sender', 'sender_name', 'sender_role', 'message', 'created_at']
        read_only_fields = ['id', 'contact_message', 'sender', 'sender_name', 'created_at']

    def get_sender_name(self, obj):
        if obj.sender:
            return obj.sender.get_full_name() or obj.sender.username
        return 'Admin' if obj.sender_role == 'ADMIN' else 'User'


class ContactMessageSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    user = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    client_name = serializers.ReadOnlyField(source='client.business_name')
    replies = ContactMessageReplySerializer(many=True, read_only=True)
    replies_count = serializers.SerializerMethodField()
    last_reply_at = serializers.SerializerMethodField()
    is_unanswered = serializers.SerializerMethodField()

    class Meta:
        model = ContactMessage
        fields = [
            'id', 'user', 'client', 'client_name', 'name', 'email', 'phone',
            'subject', 'message', 'source', 'status', 'created_at', 'updated_at',
            'replies', 'replies_count', 'last_reply_at', 'is_unanswered'
        ]
        read_only_fields = ['id', 'user', 'client', 'created_at', 'updated_at']

    def get_replies_count(self, obj):
        replies = getattr(obj, 'replies', None)
        return replies.count() if replies is not None else 0

    def get_last_reply_at(self, obj):
        replies = getattr(obj, 'replies', None)
        last_reply = replies.last() if replies is not None else None
        return last_reply.created_at if last_reply else None

    def get_is_unanswered(self, obj):
        if obj.status == 'RESOLVED':
            return False
        replies = getattr(obj, 'replies', None)
        last_reply = replies.last() if replies is not None else None
        if not last_reply:
            return True
        return last_reply.sender_role == 'USER'


class UserFeedbackReplySerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    feedback = ObjectIdField(read_only=True)
    sender = ObjectIdField(read_only=True)
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = UserFeedbackReply
        fields = ['id', 'feedback', 'sender', 'sender_name', 'sender_role', 'message', 'created_at']
        read_only_fields = ['id', 'feedback', 'sender', 'sender_name', 'created_at']

    def get_sender_name(self, obj):
        if obj.sender:
            return obj.sender.get_full_name() or obj.sender.username
        return 'Admin' if obj.sender_role == 'ADMIN' else 'User'


class UserFeedbackSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    user = ObjectIdField(read_only=True)
    client = ObjectIdField(read_only=True)
    client_name = serializers.ReadOnlyField(source='client.business_name')
    replies = UserFeedbackReplySerializer(many=True, read_only=True)
    replies_count = serializers.SerializerMethodField()
    last_reply_at = serializers.SerializerMethodField()
    is_unanswered = serializers.SerializerMethodField()

    class Meta:
        model = UserFeedback
        fields = [
            'id', 'user', 'client', 'client_name', 'name', 'email',
            'category', 'rating', 'message', 'source', 'status',
            'created_at', 'updated_at', 'replies', 'replies_count',
            'last_reply_at', 'is_unanswered'
        ]
        read_only_fields = ['id', 'user', 'client', 'created_at', 'updated_at']

    def get_replies_count(self, obj):
        replies = getattr(obj, 'replies', None)
        return replies.count() if replies is not None else 0

    def get_last_reply_at(self, obj):
        replies = getattr(obj, 'replies', None)
        last_reply = replies.last() if replies is not None else None
        return last_reply.created_at if last_reply else None

    def get_is_unanswered(self, obj):
        if obj.status == 'RESOLVED':
            return False
        replies = getattr(obj, 'replies', None)
        last_reply = replies.last() if replies is not None else None
        if not last_reply:
            return True
        return last_reply.sender_role == 'USER'


class InAppNotificationSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    user = ObjectIdField(read_only=True)

    class Meta:
        model = InAppNotification
        fields = ['id', 'user', 'title', 'body', 'notification_type', 'link', 'is_read', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']
