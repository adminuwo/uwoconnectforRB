from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

class Client(models.Model):
    PLAN_CHOICES = [
        ('FREE', 'Free'),
        ('STARTER', 'Starter'),
        ('GROWTH', 'Growth'),
        ('ENTERPRISE', 'Enterprise'),
    ]
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('SUSPENDED', 'Suspended'),
        ('TRIAL', 'Trial'),
    ]
    business_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    automation_enabled = models.BooleanField(default=True)
    plan = models.CharField(max_length=50, default='FREE')
    assigned_plan = models.ForeignKey('Plan', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_clients')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Enablement Flags
    whatsapp_enabled = models.BooleanField(default=True)
    facebook_enabled = models.BooleanField(default=False)
    instagram_enabled = models.BooleanField(default=False)
    gmail_enabled = models.BooleanField(default=False)
    onedrive_enabled = models.BooleanField(default=False)
    google_calendar_enabled = models.BooleanField(default=False)
    google_sheets_enabled = models.BooleanField(default=False)
    google_docs_enabled = models.BooleanField(default=False)
    google_slides_enabled = models.BooleanField(default=False)
    zoho_enabled = models.BooleanField(default=False)
    youtube_enabled = models.BooleanField(default=False)
    google_news_enabled = models.BooleanField(default=False)
    outlook_enabled = models.BooleanField(default=False)
    
    # Plan & Entitlements State
    selected_channels = models.JSONField(default=list, blank=True)
    billing_period = models.CharField(max_length=20, default='MONTHLY')
    
    # Admin Controlled Channel Access Permissions (e.g. {"whatsapp": True, "facebook": True, "instagram": False})
    channel_access = models.JSONField(default=dict, blank=True)
    
    # WhatsApp Config
    whatsapp_access_token = models.TextField(null=True, blank=True)
    whatsapp_phone_number_id = models.CharField(max_length=100, null=True, blank=True)
    whatsapp_waba_id = models.CharField(max_length=100, null=True, blank=True)
    whatsapp_verify_token = models.CharField(max_length=100, null=True, blank=True)
    
    # Global Greeting Message
    greeting_enabled = models.BooleanField(default=True)
    greeting_message = models.TextField(null=True, blank=True)
    greeting_buttons = models.JSONField(default=list, blank=True)
    
    # AI Assistant Config
    ai_enabled = models.BooleanField(default=False)
    ai_context = models.TextField(null=True, blank=True) # Description of business/platform for the AI
    
    # Config as JSON
    facebook_config = models.JSONField(default=dict, blank=True)
    instagram_config = models.JSONField(default=dict, blank=True)
    whatsapp_config = models.JSONField(default=dict, blank=True)
    gmail_config = models.JSONField(default=dict, blank=True)
    onedrive_config = models.JSONField(default=dict, blank=True)
    google_calendar_config = models.JSONField(default=dict, blank=True)
    google_sheets_config = models.JSONField(default=dict, blank=True)
    google_docs_config = models.JSONField(default=dict, blank=True)
    google_slides_config = models.JSONField(default=dict, blank=True)
    zoho_config = models.JSONField(default=dict, blank=True)
    youtube_config = models.JSONField(default=dict, blank=True)
    google_news_config = models.JSONField(default=dict, blank=True)
    outlook_config = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    
    # Enterprise Features
    api_key = models.CharField(max_length=100, null=True, blank=True, unique=True)
    white_label_name = models.CharField(max_length=100, null=True, blank=True)
    white_label_domain = models.CharField(max_length=100, null=True, blank=True)
    white_label_logo = models.TextField(null=True, blank=True)
    
    # Invoice & Branding Settings
    invoice_prefix = models.CharField(max_length=20, default='INV')
    invoice_next_number = models.IntegerField(default=1001)
    company_logo_url = models.TextField(null=True, blank=True)
    tax_id_gstin = models.CharField(max_length=100, null=True, blank=True)
    invoice_default_notes = models.TextField(null=True, blank=True)
    payment_terms = models.TextField(null=True, blank=True)
    invoice_footer = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def has_channel_access(self, channel_name):
        """
        Returns True if the client has admin-granted access to this channel.
        WhatsApp, Facebook, Instagram default to True unless explicitly disabled in channel_access.
        Other channels (Gmail, Zoho, Google Sheets, Calendar, etc.) are enabled if Admin explicitly granted access
        in channel_access or via model enablement flags.
        """
        key = str(channel_name).lower().strip()
        if isinstance(self.channel_access, dict) and key in self.channel_access:
            return bool(self.channel_access[key])
        if key == 'whatsapp':
            return bool(self.whatsapp_enabled)
        if key in ('facebook', 'instagram'):
            return True
        # Check model field (e.g. gmail_enabled, zoho_enabled, etc.)
        field_name = f"{key}_enabled"
        if hasattr(self, field_name):
            return bool(getattr(self, field_name, False))
        return False

    def get_channel_access_dict(self):
        """
        Returns full dict of channel permissions for all supported platform channels.
        """
        ca = self.channel_access if isinstance(self.channel_access, dict) else {}
        ALL_KEYS = [
            'whatsapp', 'facebook', 'instagram', 'gmail', 'outlook', 'onedrive',
            'google_calendar', 'google_sheets', 'google_docs', 'google_slides',
            'zoho', 'youtube', 'google_news', 'telegram', 'linkedin', 'twitter', 'tiktok'
        ]
        result = {}
        for k in ALL_KEYS:
            if k in ca:
                result[k] = bool(ca[k])
            elif k == 'whatsapp':
                result[k] = bool(self.whatsapp_enabled)
            elif k in ('facebook', 'instagram'):
                result[k] = True
            elif hasattr(self, f"{k}_enabled"):
                result[k] = bool(getattr(self, f"{k}_enabled", False))
            else:
                result[k] = False
        return result

    def __str__(self):
        return self.business_name

class User(AbstractUser):
    ROLE_CHOICES = [
        ('ADMIN', 'Admin'),
        ('CLIENT', 'Client'),
        ('AGENT', 'Agent'),
    ]
    ENTERPRISE_ROLE_CHOICES = [
        ('SUPER_ADMIN', 'Super Admin'),
        ('ORG_ADMIN', 'Organization Admin'),
        ('HR', 'HR Manager'),
        ('MANAGER', 'Manager'),
        ('TEAM_LEAD', 'Team Lead'),
        ('EMPLOYEE', 'Employee'),
        ('INTERN', 'Intern'),
        ('GUEST', 'Guest'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SUSPENDED', 'Suspended'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='CLIENT')
    enterprise_role = models.CharField(max_length=30, choices=ENTERPRISE_ROLE_CHOICES, default='EMPLOYEE')
    department = models.CharField(max_length=100, default='General', blank=True)
    designation = models.CharField(max_length=100, default='Team Member', blank=True)
    reporting_manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='direct_reports')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    permissions = models.JSONField(default=list, blank=True)
    assigned_platforms = models.JSONField(default=list, blank=True) # e.g. ["CRM", "WHATSAPP", "ORDERS", "PROJECTS"]
    employee_id = models.CharField(max_length=50, null=True, blank=True)
    phone_number = models.CharField(max_length=50, null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    working_hours = models.CharField(max_length=50, default='9:00 AM - 6:00 PM', blank=True)
    salary_visibility = models.BooleanField(default=False)
    skills = models.JSONField(default=list, blank=True)
    availability_status = models.CharField(max_length=30, default='AVAILABLE', blank=True) # AVAILABLE, BUSY, IN_MEETING, ON_LEAVE
    is_online = models.BooleanField(default=False)
    last_active_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='UTC', blank=True)
    language = models.CharField(max_length=50, default='English', blank=True)
    assigned_social_channels = models.JSONField(default=list, blank=True) # e.g. ["instagram_acc_a", "whatsapp_num_1"]
    permission_matrix = models.JSONField(default=dict, blank=True) # e.g. {"instagram": "FULL", "crm": "VIEW"}
    current_page = models.CharField(max_length=255, null=True, blank=True)
    last_login_ip = models.CharField(max_length=100, null=True, blank=True)
    last_login_browser = models.CharField(max_length=255, null=True, blank=True)
    last_login_os = models.CharField(max_length=255, null=True, blank=True)
    login_history = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.username} ({self.enterprise_role or self.role})"

class TeamInvite(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='team_invites')
    email = models.EmailField(blank=True, default='')
    token = models.CharField(max_length=64, unique=True)
    permissions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    is_qr = models.BooleanField(default=False)

    def __str__(self):
        return f"Invite for {self.email or 'QR Code'} to {self.client.business_name}"

class PasswordResetOTP(models.Model):
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.email} - {self.otp}"

class Automation(models.Model):
    TRIGGER_CHOICES = [
        ('KEYWORD', 'Keyword'),
        ('START_CHAT', 'Start Chat'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='automations')
    name = models.CharField(max_length=255)
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='KEYWORD')
    keywords = models.JSONField(default=list, blank=True)
    response = models.TextField()
    buttons = models.JSONField(default=list, blank=True) # Optional buttons (max 3)
    channels = models.JSONField(default=list, blank=True)  # e.g., ["WHATSAPP"]
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Workflow(models.Model):
    TRIGGER_CHOICES = [
        ('KEYWORD', 'Keyword'),
        ('NEW_CHAT', 'New Chat'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='workflows')
    name = models.CharField(max_length=255)
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default='KEYWORD')
    trigger_value = models.JSONField(default=list, blank=True)
    steps = models.JSONField(default=list)  # List of step dicts
    channels = models.JSONField(default=list, blank=True)  # e.g., ["WHATSAPP"]
    category = models.CharField(max_length=100, default='General')
    industry = models.CharField(max_length=100, default='None')
    version = models.CharField(max_length=20, default='1.0')
    is_shared = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class WorkflowSession(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='workflow_sessions')
    phone_number = models.CharField(max_length=50) # The customer's WhatsApp number
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='sessions')
    current_node_id = models.CharField(max_length=255)
    variables = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Message(models.Model):
    CHANNEL_CHOICES = [
        ('WHATSAPP', 'WhatsApp'),
        ('FACEBOOK', 'Facebook'),
        ('INSTAGRAM', 'Instagram'),
        ('GMAIL', 'Gmail'),
    ]
    TYPE_CHOICES = [
        ('INCOMING', 'Incoming'),
        ('OUTGOING', 'Outgoing'),
        ('INTERNAL', 'Internal Note'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('READ', 'Read'),
        ('RECEIVED', 'Received'),
        ('FAILED', 'Failed'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='messages')
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, db_index=True)
    from_address = models.CharField(max_length=255)
    to_address = models.CharField(max_length=255)
    body = models.TextField()
    message_type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    sender_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages')
    sender_name = models.CharField(max_length=255, null=True, blank=True)
    sender_avatar = models.CharField(max_length=500, null=True, blank=True)
    sender_department = models.CharField(max_length=100, null=True, blank=True)
    ai_suggested_reply = models.TextField(null=True, blank=True)
    whatsapp_message_id = models.CharField(max_length=255, null=True, blank=True)
    meta_message_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    edited_at = models.DateTimeField(null=True, blank=True)
    edited_history = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

class Conversation(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('WAITING', 'Waiting for Customer'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='conversations')
    contact = models.ForeignKey('Contact', on_delete=models.CASCADE, related_name='conversations', null=True, blank=True)
    contact_platform_id = models.CharField(max_length=255)
    channel = models.CharField(max_length=20, default='WHATSAPP', db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_conversations')
    assigned_department = models.CharField(max_length=100, default='General', blank=True)
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='locked_conversations')
    locked_at = models.DateTimeField(null=True, blank=True)
    typing_users = models.JSONField(default=list, blank=True)
    viewing_users = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    unread_count_admin = models.IntegerField(default=0)
    unread_count_employee = models.IntegerField(default=0)
    last_message_summary = models.TextField(blank=True, default='')
    last_message_at = models.DateTimeField(auto_now=True)
    first_response_time_seconds = models.IntegerField(default=0)
    resolution_time_seconds = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-last_message_at']

    def __str__(self):
        return f"Convo {self.contact_platform_id} ({self.channel}) [{self.status}]"

class ConversationAuditLog(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='audit_logs', null=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='conversation_audit_logs')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_name = models.CharField(max_length=255, default='System')
    actor_role = models.CharField(max_length=100, default='Admin')
    event_type = models.CharField(max_length=50) # OPENED, VIEWED, ASSIGNED, REPLIED, NOTE_ADDED, STATUS_CHANGED, TYPING, LOCKED, UNLOCKED, TAKEOVER, TRANSFERRED, CLOSED, REOPENED
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type}] {self.actor_name} on Convo #{self.conversation_id if self.conversation else 'N/A'}"

class Log(models.Model):
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='logs')
    action = models.CharField(max_length=255)
    details = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

class GlobalSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    file = models.FileField(upload_to='legal/', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


def client_directory_path(instance, filename):
    return f'knowledge/client_{instance.client.id}/{filename}'

class KnowledgeDocument(models.Model):
    """
    RAG Knowledge Base — Client ke business documents store hote hain.
    AI sirf inhi documents ke basis pe jawab deta hai.
    """
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='knowledge_docs')
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=client_directory_path, null=True, blank=True)
    extracted_text = models.TextField(blank=True, default='')
    file_type = models.CharField(max_length=20, blank=True, default='')  # pdf, docx, txt
    file_size = models.IntegerField(default=0)  # bytes
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.client.business_name} — {self.title}"


class KnowledgeChunk(models.Model):
    """
    Document ka ek chunk — embedding ke saath stored.
    Har document multiple chunks mein split hota hai for accurate RAG retrieval.
    """
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name='chunks')
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='knowledge_chunks')
    chunk_text = models.TextField()  # 500-800 word chunk
    chunk_index = models.IntegerField(default=0)  # Order in the document
    embedding = models.JSONField(default=list, blank=True)  # OpenAI embedding vector (1536 dims)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['document', 'chunk_index']

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"

class Contact(models.Model):
    STAGE_CHOICES = [
        ('NEW', 'New Lead'),
        ('FOLLOWUP', 'Follow Up'),
        ('NEGOTIATION', 'Negotiation'),
        ('WON', 'Closed Won'),
        ('LOST', 'Closed Lost'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    platform_id = models.CharField(max_length=255, help_text="WhatsApp ID, IG SID, or FB PSID")
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='NEW')
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(null=True, blank=True)
    bot_paused = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('client', 'platform_id')

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            try:
                from .utils.sheets_utils import sync_lead_to_google_sheet
                sync_lead_to_google_sheet(self.client, self)
            except Exception as e:
                print(f"[Sheets Async Trigger Error] {str(e)}")

    def __str__(self):
        return f"{self.name or self.platform_id} ({self.client.business_name})"

class Template(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='templates')
    name = models.CharField(max_length=255)
    language = models.CharField(max_length=50, default='en_US')
    category = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=50, default='PENDING') # APPROVED, REJECTED, etc.
    components = models.JSONField(default=list) # The template structure
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.language})"

class Campaign(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SCHEDULED', 'Scheduled'),
        ('SENDING', 'Sending'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, default='Marketing')
    tags = models.JSONField(default=list, blank=True)
    priority = models.CharField(max_length=20, default='NORMAL')

    # Message Content
    channel = models.CharField(max_length=50, default='WHATSAPP')  # kept for backward compat
    body = models.TextField(null=True, blank=True)  # kept for backward compat
    template = models.ForeignKey(Template, on_delete=models.SET_NULL, null=True, blank=True)
    message_body = models.TextField(null=True, blank=True)
    attachments = models.JSONField(default=list, blank=True)

    # Multi-Channel & Audience
    platforms = models.JSONField(default=list, blank=True)  # ['WHATSAPP', 'GMAIL', 'SMS', 'TELEGRAM', 'INSTAGRAM']
    audience_filter = models.CharField(max_length=50, default='ALL') # 'ALL', 'NEW', 'WON', etc.

    # Delivery & Settings
    sending_mode = models.CharField(max_length=50, default='IMMEDIATE') # IMMEDIATE, SCHEDULED, RECURRING
    speed_mode = models.CharField(max_length=50, default='NORMAL') # ULTRA_FAST, FAST, NORMAL, SAFE
    fallback_channels = models.JSONField(default=list, blank=True) # ['GMAIL', 'SMS']
    retry_attempts = models.IntegerField(default=3)
    
    # Real-time Metrics
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    total_recipients = models.IntegerField(default=0)
    total_queued = models.IntegerField(default=0)
    total_sent = models.IntegerField(default=0)
    total_delivered = models.IntegerField(default=0)
    total_read = models.IntegerField(default=0)
    total_replied = models.IntegerField(default=0)
    total_clicked = models.IntegerField(default=0)
    total_failed = models.IntegerField(default=0)
    failed_recipients = models.JSONField(default=list, blank=True)

    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

class CampaignFollowUp(models.Model):
    campaign = models.OneToOneField(Campaign, on_delete=models.CASCADE, related_name='follow_up')
    delay_hours = models.IntegerField(default=24)
    followup_template = models.ForeignKey(Template, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"FollowUp for {self.campaign.name} ({self.delay_hours}h)"

class FollowUpLog(models.Model):
    followup = models.ForeignKey(CampaignFollowUp, on_delete=models.CASCADE, related_name='logs')
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default='SENT')
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('followup', 'contact')

    def __str__(self):
        return f"FollowUp sent to {self.contact.phone_number}"

class SupportMessage(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='support_messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Support Message from {self.sender.username} ({self.client.business_name}) at {self.created_at}"

class TeamMessage(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='team_messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_team_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        
    def __str__(self):
        return f"From {self.sender.username}: {self.body[:20]}"


class AuditLog(models.Model):
    admin_name = models.CharField(max_length=255)
    client_name = models.CharField(max_length=255)
    module = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    before_value = models.TextField(null=True, blank=True)
    after_value = models.TextField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at}] {self.admin_name} -> {self.client_name}: {self.action} on {self.module}"


class Product(models.Model):
    CATEGORY_CHOICES = [
        ('PHYSICAL', 'Physical Product'),
        ('DIGITAL', 'Digital Product'),
        ('BOOK', 'Book / E-Book'),
        ('SERVICE', 'Service'),
        ('OTHER', 'Other'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='PHYSICAL')
    description = models.TextField(null=True, blank=True)
    image_url = models.CharField(max_length=500, null=True, blank=True)
    in_stock = models.BooleanField(default=True)

    # Extended Basic Info
    sku = models.CharField(max_length=100, null=True, blank=True)
    brand = models.CharField(max_length=100, null=True, blank=True)
    product_type = models.CharField(max_length=50, default='PHYSICAL')  # PHYSICAL, DIGITAL, BOOK, SERVICE, SUBSCRIPTION, COURSE, CONSULTING
    currency = models.CharField(max_length=10, default='USD')
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock_quantity = models.IntegerField(default=100)
    availability_status = models.CharField(max_length=50, default='IN_STOCK')  # IN_STOCK, OUT_OF_STOCK, PRE_ORDER, BACKORDER
    tags = models.JSONField(default=list, blank=True)

    # Media & Assets
    gallery_images = models.JSONField(default=list, blank=True)
    video_url = models.CharField(max_length=500, null=True, blank=True)
    pdf_brochure_url = models.CharField(max_length=500, null=True, blank=True)

    # Product Link Section
    product_url = models.CharField(max_length=1000, null=True, blank=True)
    link_type = models.CharField(max_length=50, default='WEBSITE')  # WEBSITE, BUY_NOW, CHECKOUT, PAYMENT, BOOKING, DOWNLOAD, DOCUMENTATION, VIDEO, EXTERNAL_MARKETPLACE, CUSTOM
    cta_text = models.CharField(max_length=100, default='View Product')
    button_color = models.CharField(max_length=50, default='#10B981')
    button_icon = models.CharField(max_length=50, default='ExternalLink')
    open_behavior = models.CharField(max_length=50, default='NEW_TAB')  # SAME_WINDOW, NEW_TAB, IN_APP_BROWSER
    short_url = models.CharField(max_length=255, null=True, blank=True)
    qr_code_url = models.CharField(max_length=500, null=True, blank=True)

    # Analytics & Metrics
    views_count = models.IntegerField(default=0)
    link_clicks_count = models.IntegerField(default=0)
    button_clicks_count = models.IntegerField(default=0)
    whatsapp_sends_count = models.IntegerField(default=0)
    conversions_count = models.IntegerField(default=0)
    revenue_generated = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    # Specifications / Details
    specifications = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - ${self.price}"


class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders')
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='orders')
    items = models.JSONField(default=list)  # Jisme array of dicts ho: [{'product_id': '...', 'name': '...', 'price': 100, 'quantity': 1}]
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_status = models.CharField(choices=STATUS_CHOICES, default='PENDING', max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} for {self.contact.name or self.contact.phone_number}"


class PaymentOrder(models.Model):
    PLAN_CHOICES = [
        ('STARTER', 'Starter'),
        ('GROWTH', 'Growth'),
        ('ENTERPRISE', 'Enterprise'),
    ]
    CYCLE_CHOICES = [
        ('MONTHLY', 'Monthly'),
        ('ANNUAL', 'Annual'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payment_orders')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_orders')
    order_id = models.CharField(max_length=100, unique=True)
    payment_session_id = models.TextField(null=True, blank=True)
    razorpay_order_id = models.CharField(max_length=100, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    billing_cycle = models.CharField(max_length=10, choices=CYCLE_CHOICES, default='MONTHLY')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    cf_payment_id = models.CharField(max_length=100, null=True, blank=True)
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"PaymentOrder {self.order_id} - {self.client.business_name} ({self.status})"


class Project(models.Model):
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]
    STATUS_CHOICES = [
        ('PLANNING', 'Planning'),
        ('IN_PROGRESS', 'In Progress'),
        ('ON_HOLD', 'On Hold'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PLANNING')
    progress_percentage = models.IntegerField(default=0)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='owned_projects')
    members = models.ManyToManyField(User, related_name='assigned_projects', blank=True)
    department = models.CharField(max_length=100, default='General', blank=True)
    start_date = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    milestones = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    files = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Project: {self.name} [{self.status}]"


class Task(models.Model):
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]
    STATUS_CHOICES = [
        ('NOT_STARTED', 'Not Started'),
        ('IN_PROGRESS', 'In Progress'),
        ('UNDER_REVIEW', 'Under Review'),
        ('WAITING_APPROVAL', 'Waiting Approval'),
        ('BLOCKED', 'Blocked'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='tasks')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name='tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='NOT_STARTED')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tasks')
    assigned_to = models.ManyToManyField(User, related_name='assigned_tasks', blank=True)
    department = models.CharField(max_length=100, default='General', blank=True)
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    estimated_hours = models.FloatField(default=0.0)
    spent_hours = models.FloatField(default=0.0)
    progress_percentage = models.IntegerField(default=0)
    milestone_name = models.CharField(max_length=100, blank=True, null=True)
    is_recurring = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    checklist = models.JSONField(default=list, blank=True)
    attachments = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task #{self.id} - {self.title} [{self.status}]"


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_comments')
    text = models.TextField()
    attachments = models.JSONField(default=list, blank=True)
    mentions = models.JSONField(default=list, blank=True)
    parent_comment = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    is_pinned = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.author.username} on Task #{self.task.id}"


class WorkReport(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='work_reports')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='work_reports')
    report_date = models.DateField()
    todays_work = models.TextField()
    completed_work = models.TextField(blank=True, null=True)
    remaining_work = models.TextField(blank=True, null=True)
    blockers = models.TextField(blank=True, null=True)
    need_help = models.BooleanField(default=False)
    next_steps = models.TextField(blank=True, null=True)
    hours_worked = models.FloatField(default=8.0)
    attachments = models.JSONField(default=list, blank=True)
    ai_summary = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report {self.report_date} - {self.employee.username}"


class WorkApproval(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('CHANGES_REQUESTED', 'Changes Requested'),
        ('REJECTED', 'Rejected'),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='approvals')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_approvals')
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_approvals')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    submission_notes = models.TextField(blank=True, null=True)
    feedback_notes = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Approval #{self.id} for Task #{self.task.id} - {self.status}"


class TeamChannel(models.Model):
    TYPE_CHOICES = [
        ('PUBLIC', 'Public Channel'),
        ('PRIVATE', 'Private Channel'),
        ('DIRECT', 'Direct Message'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='team_channels')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    channel_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='PUBLIC')
    members = models.ManyToManyField(User, related_name='team_channels', blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_channels')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"#{self.name} ({self.channel_type})"


class TeamChatMessage(models.Model):
    channel = models.ForeignKey(TeamChannel, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_chat_messages')
    text = models.TextField()
    attachments = models.JSONField(default=list, blank=True)
    reactions = models.JSONField(default=dict, blank=True)
    mentions = models.JSONField(default=list, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_announcement = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Msg in #{self.channel.name} by {self.sender.username}"


class Attendance(models.Model):
    STATUS_CHOICES = [
        ('PRESENT', 'Present'),
        ('ABSENT', 'Absent'),
        ('HALF_DAY', 'Half Day'),
        ('ON_LEAVE', 'On Leave'),
        ('LATE', 'Late'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='attendances')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField()
    clock_in = models.DateTimeField(null=True, blank=True)
    clock_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PRESENT')
    working_hours = models.FloatField(default=0.0)
    break_hours = models.FloatField(default=0.0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'user', 'date')

    def __str__(self):
        return f"Attendance {self.date} - {self.user.username} [{self.status}]"


class LeaveRequest(models.Model):
    TYPE_CHOICES = [
        ('CASUAL', 'Casual Leave'),
        ('SICK', 'Sick Leave'),
        ('PAID', 'Paid Leave'),
        ('UNPAID', 'Unpaid Leave'),
        ('WFH', 'Work From Home'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='leave_requests')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CASUAL')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leaves')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Leave ({self.leave_type}) {self.start_date} to {self.end_date} - {self.user.username}"


# ─────────────────────────────────────────────────────────────────────────────
# Interactive Learning Center & Documentation Models
# ─────────────────────────────────────────────────────────────────────────────

class Guide(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('ARCHIVED', 'Archived'),
    ]

    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=255)
    icon = models.CharField(max_length=50, default='BookOpen')  # Lucide icon name
    category = models.CharField(max_length=100, default='General')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PUBLISHED')
    description = models.TextField(blank=True, null=True)
    estimated_time = models.CharField(max_length=50, default='10 mins')
    order = models.IntegerField(default=0)
    language = models.CharField(max_length=10, default='en')
    version = models.CharField(max_length=20, default='1.0')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'title']

    def __str__(self):
        return f"{self.title} ({self.slug})"


class GuideSection(models.Model):
    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name='sections')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, blank=True, null=True)
    icon = models.CharField(max_length=50, default='ChevronRight')
    order = models.IntegerField(default=0)
    is_expandable = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.guide.title} - {self.title}"


class GuideStep(models.Model):
    STEP_TYPE_CHOICES = [
        ('text', 'Rich Text'),
        ('code', 'Code Snippet'),
        ('image', 'Image Screenshot'),
        ('video', 'Video Tutorial'),
        ('diagram', 'Flow Diagram'),
        ('checklist', 'Interactive Checklist'),
        ('faq', 'FAQ Accordion'),
        ('warning', 'Warning Alert'),
        ('tip', 'Pro Tip Alert'),
    ]

    section = models.ForeignKey(GuideSection, on_delete=models.CASCADE, related_name='steps')
    title = models.CharField(max_length=255, blank=True, null=True)
    step_type = models.CharField(max_length=20, choices=STEP_TYPE_CHOICES, default='text')
    content = models.TextField(blank=True, null=True)  # Markdown/Text content
    media_url = models.URLField(max_length=500, blank=True, null=True)
    code_snippet = models.TextField(blank=True, null=True)
    code_language = models.CharField(max_length=50, default='bash', blank=True, null=True)
    checklist_items = models.JSONField(default=list, blank=True) # list of items if checklist
    order = models.IntegerField(default=0)
    is_completable = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.section.title} - Step {self.order}: {self.title or self.step_type}"


class GuideProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='guide_progress')
    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name='user_progress')
    completed_steps = models.JSONField(default=list, blank=True) # List of step IDs completed
    bookmarked_sections = models.JSONField(default=list, blank=True) # List of section IDs bookmarked
    last_step_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'guide')

    def __str__(self):
        return f"{self.user.username} progress on {self.guide.title}"


# ── ENTERPRISE EMAIL CENTER MODELS ──────────────────────────────────────────

class EmailAccount(models.Model):
    PROVIDER_CHOICES = [
        ('gmail', 'Gmail / Google Workspace'),
        ('outlook', 'Microsoft 365 / Outlook'),
        ('exchange', 'Microsoft Exchange'),
        ('imap', 'Custom IMAP / SMTP'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='email_accounts')
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default='gmail')
    email_address = models.EmailField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    credentials = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email_address} ({self.provider})"


class EmailMessage(models.Model):
    FOLDER_CHOICES = [
        ('inbox', 'Inbox'),
        ('sent', 'Sent'),
        ('drafts', 'Drafts'),
        ('scheduled', 'Scheduled'),
        ('outbox', 'Outbox'),
        ('spam', 'Spam'),
        ('trash', 'Trash'),
        ('archived', 'Archived'),
        ('deleted', 'Deleted'),
        ('important', 'Important'),
        ('starred', 'Starred'),
        ('snoozed', 'Snoozed'),
    ]
    STATUS_CHOICES = [
        ('delivered', 'Delivered'),
        ('opened', 'Opened'),
        ('clicked', 'Clicked'),
        ('replied', 'Replied'),
        ('forwarded', 'Forwarded'),
        ('archived', 'Archived'),
        ('deleted', 'Deleted'),
        ('scheduled', 'Scheduled'),
        ('failed', 'Failed'),
    ]
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('normal', 'Normal'),
        ('low', 'Low'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='email_messages')
    account = models.ForeignKey(EmailAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    folder = models.CharField(max_length=30, choices=FOLDER_CHOICES, default='inbox', db_index=True)
    sender_email = models.EmailField(max_length=255)
    sender_name = models.CharField(max_length=255, blank=True, default='')
    to_recipients = models.JSONField(default=list, blank=True) # ['aditi@uwo24.com']
    cc_recipients = models.JSONField(default=list, blank=True)
    bcc_recipients = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=500)
    body_text = models.TextField(blank=True, default='')
    body_html = models.TextField(blank=True, default='')
    attachments = models.JSONField(default=list, blank=True) # [{'name': 'document.pdf', 'size': '2.4 MB', 'url': '...'}]
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='delivered', db_index=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    is_read = models.BooleanField(default=False)
    labels = models.JSONField(default=list, blank=True) # ['Sales', 'Support', 'Urgent']
    metadata = models.JSONField(default=dict, blank=True) # For provider IDs, thread IDs, etc.

    scheduled_at = models.DateTimeField(null=True, blank=True)
    recurring_rule = models.CharField(max_length=50, blank=True, default='') # daily, weekly, monthly
    timezone = models.CharField(max_length=50, default='UTC')

    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_emails')
    meeting_invite_data = models.JSONField(default=dict, blank=True) # {'title': '...', 'link': '...', 'status': 'accepted'}
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.folder.upper()}] {self.subject} - {self.sender_email}"


class EmailAutoReplyRule(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='email_auto_replies')
    name = models.CharField(max_length=255)
    subject_pattern = models.CharField(max_length=255, blank=True, default='')
    sender_pattern = models.CharField(max_length=255, blank=True, default='')
    keyword_match = models.CharField(max_length=255, blank=True, default='')
    
    REPLY_TYPE_CHOICES = [
        ('thank_you', 'Thank You Acknowledgment'),
        ('ticket', 'Support Ticket Number'),
        ('brochure', 'Sales Product Brochure'),
        ('out_of_office', 'Holiday Out of Office'),
        ('ai_generated', 'AI Generated Reply'),
    ]
    reply_type = models.CharField(max_length=30, choices=REPLY_TYPE_CHOICES, default='thank_you')
    reply_subject = models.CharField(max_length=255, blank=True, default='')
    reply_body = models.TextField()
    attachment_file = models.CharField(max_length=500, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AutoReply Rule: {self.name} ({self.reply_type})"


class EmailAutomationWorkflow(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='email_automations')
    name = models.CharField(max_length=255)
    subject_keyword = models.CharField(max_length=255, blank=True, default='')
    sender_domain = models.CharField(max_length=255, blank=True, default='')
    has_attachments = models.BooleanField(default=False)
    
    assign_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='automated_email_workflows')
    create_crm_lead = models.BooleanField(default=True)
    send_auto_reply = models.BooleanField(default=True)
    notify_admin = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Automation Workflow: {self.name}"


class EmailTeamNote(models.Model):
    message = models.ForeignKey(EmailMessage, on_delete=models.CASCADE, related_name='team_notes')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    note_text = models.TextField()
    mentions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Note by {self.author.username} on Msg #{self.message.id}"


class CallHistory(models.Model):
    CALL_TYPE_CHOICES = [
        ('VOICE', 'Voice'),
        ('VIDEO', 'Video'),
    ]
    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('MISSED', 'Missed'),
        ('REJECTED', 'Rejected'),
        ('FAILED', 'Failed'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='call_histories', null=True, blank=True)
    caller = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='outgoing_calls', null=True, blank=True)
    caller_name = models.CharField(max_length=255)
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='incoming_calls', null=True, blank=True)
    receiver_name = models.CharField(max_length=255)
    receiver_dept = models.CharField(max_length=100, null=True, blank=True)
    call_type = models.CharField(max_length=10, choices=CALL_TYPE_CHOICES, default='VOICE')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    duration = models.CharField(max_length=50, default='0s')
    session_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caller_name} -> {self.receiver_name} ({self.call_type})"


class ActiveCallSession(models.Model):
    """
    Persists live WebRTC call sessions in MongoDB so that Cloud Run stateless
    instances can share call state across requests.
    """
    STATUS_CHOICES = [
        ('RINGING', 'Ringing'),
        ('CONNECTED', 'Connected'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed'),
        ('MISSED', 'Missed'),
    ]

    session_id = models.CharField(max_length=200, unique=True)
    caller = models.CharField(max_length=255)
    caller_user_id = models.CharField(max_length=100, null=True, blank=True)
    client_id = models.CharField(max_length=100, null=True, blank=True)
    recipient = models.CharField(max_length=255)
    recipient_display = models.CharField(max_length=255, null=True, blank=True)
    receiver_user_id = models.CharField(max_length=100, null=True, blank=True)
    call_type = models.CharField(max_length=10, default='VOICE')
    is_video = models.BooleanField(default=False)
    sdp_offer = models.TextField(null=True, blank=True)
    sdp_answer = models.TextField(null=True, blank=True)
    ice_candidates = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RINGING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caller} -> {self.recipient} [{self.status}]"

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "caller": self.caller,
            "caller_user_id": self.caller_user_id,
            "client_id": self.client_id,
            "recipient": self.recipient,
            "recipient_display": self.recipient_display,
            "receiver_user_id": self.receiver_user_id,
            "call_type": self.call_type,
            "is_video": self.is_video,
            "sdp_offer": self.sdp_offer,
            "sdp_answer": self.sdp_answer,
            "ice_candidates": self.ice_candidates or [],
            "status": self.status,
        }







# ─────────────────────────────────────────────────────────────────────────────
# Per-Client Razorpay OAuth Gateway Models
# Each UWOConnect client connects their OWN Razorpay account via OAuth.
# Payments for their products use their own Razorpay account — never mixed.
# ─────────────────────────────────────────────────────────────────────────────

class RazorpayConnection(models.Model):
    """
    Stores the Razorpay OAuth connection for a specific client/workspace.
    Every client connects their own Razorpay account — strict workspace isolation.
    Tokens are NEVER exposed to the frontend.
    """
    MODE_CHOICES = [
        ('TEST', 'Test Mode'),
        ('LIVE', 'Live Mode'),
    ]
    STATUS_CHOICES = [
        ('CONNECTED', 'Connected'),
        ('DISCONNECTED', 'Disconnected'),
        ('ERROR', 'Error / Revoked'),
    ]

    client = models.OneToOneField(
        Client, on_delete=models.CASCADE, related_name='razorpay_connection'
    )
    # Razorpay account reference (from OAuth response)
    razorpay_account_id = models.CharField(max_length=200, null=True, blank=True)

    # OAuth tokens — stored backend-only, NEVER returned to frontend
    access_token = models.TextField(null=True, blank=True)
    refresh_token = models.TextField(null=True, blank=True)
    # Razorpay OAuth returns key_id/key_secret pairs for the linked account
    linked_key_id = models.CharField(max_length=200, null=True, blank=True)
    linked_key_secret = models.TextField(null=True, blank=True)  # encrypted/backend-only

    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='TEST')
    connection_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DISCONNECTED')

    # Webhook secret registered per workspace for event verification
    webhook_secret = models.CharField(max_length=255, null=True, blank=True)

    # Token expiry for refresh logic
    token_expires_at = models.DateTimeField(null=True, blank=True)

    connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.client.business_name} — Razorpay [{self.connection_status}] ({self.mode})"

    def is_connected(self):
        return self.connection_status == 'CONNECTED' and bool(self.linked_key_id)


class ProductPayment(models.Model):
    """
    Records every customer transaction for a client's product.
    Uses the client's own Razorpay account — strictly isolated per workspace.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
        ('PARTIALLY_REFUNDED', 'Partially Refunded'),
    ]

    # Workspace isolation — CRITICAL
    workspace = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name='product_payments'
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments'
    )
    razorpay_connection = models.ForeignKey(
        RazorpayConnection, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='product_payments'
    )

    # Razorpay IDs
    razorpay_order_id = models.CharField(max_length=200, null=True, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=200, null=True, blank=True, db_index=True)
    razorpay_signature = models.CharField(max_length=500, null=True, blank=True)

    # Payment details
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    payment_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=100, null=True, blank=True)  # UPI, Card, NetBanking, etc.

    # Customer info (collected at checkout)
    customer_name = models.CharField(max_length=255, null=True, blank=True)
    customer_email = models.EmailField(null=True, blank=True)
    customer_phone = models.CharField(max_length=50, null=True, blank=True)

    # Refund tracking
    refund_id = models.CharField(max_length=200, null=True, blank=True)
    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    # Reference to the Razorpay account that processed the payment
    gateway_account_reference = models.CharField(max_length=200, null=True, blank=True)

    # Idempotency — prevents duplicate webhook processing
    webhook_event_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"ProductPayment #{self.id} | {self.workspace.business_name} | "
            f"{self.product.name if self.product else 'N/A'} | "
            f"₹{self.amount} | {self.payment_status}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Quotation, Proposal & Invoice (Sales Document) Management Module Models
# ─────────────────────────────────────────────────────────────────────────────

class SalesDocumentTemplate(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('QUOTATION', 'Quotation'),
        ('PROPOSAL', 'Proposal'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='sales_document_templates')
    name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES, default='PROPOSAL')
    description = models.TextField(blank=True, default='')
    cover_design = models.JSONField(default=dict, blank=True)
    sections = models.JSONField(default=list, blank=True)
    terms = models.TextField(blank=True, default='')
    branding = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.document_type})"


class SalesDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('QUOTATION', 'Quotation'),
        ('PROPOSAL', 'Proposal'),
        ('INVOICE', 'Invoice'),
    ]
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('VIEWED', 'Viewed'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
        ('CONVERTED', 'Converted'),
        ('CANCELLED', 'Cancelled'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='sales_documents')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES, default='QUOTATION', db_index=True)
    document_number = models.CharField(max_length=100, db_index=True)
    
    # Customer Details
    customer = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales_documents')
    customer_name = models.CharField(max_length=255, null=True, blank=True)
    customer_company = models.CharField(max_length=255, null=True, blank=True)
    customer_email = models.EmailField(null=True, blank=True)
    customer_phone = models.CharField(max_length=50, null=True, blank=True)
    billing_address = models.TextField(null=True, blank=True)
    shipping_address = models.TextField(null=True, blank=True)
    tax_number = models.CharField(max_length=100, null=True, blank=True)
    
    # Admin Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_documents')
    salesperson = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='salesperson_documents')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    
    # Financial Details
    currency = models.CharField(max_length=10, default='USD')
    currency_symbol = models.CharField(max_length=10, default='$')
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, default=1.000000)
    
    document_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, null=True, blank=True)
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    
    # Price Summaries
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_type = models.CharField(max_length=20, choices=[('PERCENTAGE', 'Percentage'), ('FIXED', 'Fixed Amount')], default='FIXED')
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    additional_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Notes & Content
    customer_notes = models.TextField(blank=True, default='')
    internal_notes = models.TextField(blank=True, default='') # NEVER shown to customer
    terms_conditions = models.TextField(blank=True, default='')
    
    # Portal Access
    secure_token = models.CharField(max_length=64, unique=True, db_index=True)
    version = models.IntegerField(default=1)
    
    # Traceability links
    source_document = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='converted_documents')
    
    # Company Branding Snapshot
    company_details = models.JSONField(default=dict, blank=True)
    
    # Rich Content (Proposal sections, FAQs)
    proposal_sections = models.JSONField(default=list, blank=True)
    proposal_template = models.ForeignKey(SalesDocumentTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Digital acceptance info
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by_name = models.CharField(max_length=255, null=True, blank=True)
    accepted_by_email = models.EmailField(null=True, blank=True)
    accepted_comment = models.TextField(null=True, blank=True)
    accepted_ip = models.GenericIPAddressField(null=True, blank=True)
    accepted_user_agent = models.TextField(null=True, blank=True)
    
    # Digital rejection info
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    rejection_comment = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('client', 'document_number', 'version')

    def __str__(self):
        return f"{self.document_type} {self.document_number} v{self.version} ({self.status})"


class SalesDocumentItem(models.Model):
    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sku = models.CharField(max_length=100, null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1.00)
    unit = models.CharField(max_length=50, default='pcs')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Discount & Tax per item
    discount_type = models.CharField(max_length=20, choices=[('PERCENTAGE', 'Percentage'), ('FIXED', 'Fixed Amount')], default='FIXED')
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00) # e.g. 18.00 for 18%
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.name} x {self.quantity}"


class SalesDocumentActivity(models.Model):
    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=50) # CREATED, EDITED, SENT, VIEWED, DOWNLOADED, ACCEPTED, REJECTED, CONVERTED, REMINDER_SENT, CANCELLED
    details = models.TextField(blank=True, default='')
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    performed_by_name = models.CharField(max_length=255, default='System')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.activity_type} on {self.document.document_number} at {self.created_at}"


class Invoice(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PAID', 'Paid'),
        ('PENDING', 'Pending'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    INVOICE_STATUS_CHOICES = [
        ('GENERATED', 'Generated'),
        ('PENDING', 'Pending'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100, db_index=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    payment_record = models.ForeignKey(ProductPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    
    payment_id = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    transaction_id = models.CharField(max_length=255, null=True, blank=True)
    order_reference = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    channel = models.CharField(max_length=50, default='WEBSITE')
    secure_token = models.CharField(max_length=64, db_index=True, null=True, blank=True)
    
    currency = models.CharField(max_length=10, default='USD')
    currency_symbol = models.CharField(max_length=10, default='$')
    
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    shipping = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PAID', db_index=True)
    invoice_status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='GENERATED', db_index=True)
    payment_method = models.CharField(max_length=50, default='Razorpay')
    
    invoice_date = models.DateTimeField(default=timezone.now, db_index=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    
    seller_details = models.JSONField(default=dict, blank=True)
    billing_details = models.JSONField(default=dict, blank=True)
    shipping_details = models.JSONField(default=dict, blank=True)
    line_items = models.JSONField(default=list, blank=True)
    
    pdf_file_path = models.CharField(max_length=500, null=True, blank=True)
    error_log = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice_number} ({self.currency} {self.total})"


class GlobalConnector(models.Model):
    CATEGORY_CHOICES = [
        ('CORE', 'Core Messaging'),
        ('MESSAGING', 'Social & Messaging'),
        ('EMAIL', 'Email & Productivity'),
        ('STORAGE', 'Cloud Storage'),
        ('CRM', 'CRM & Pipeline'),
        ('MEDIA', 'Media & Content'),
        ('CONNECTOR', 'Other Connector'),
    ]

    connector_key = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=50, blank=True, default='')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='MESSAGING')
    is_active = models.BooleanField(default=True, db_index=True)
    is_coming_soon = models.BooleanField(default=False, db_index=True)
    is_core = models.BooleanField(default=False)
    icon_key = models.CharField(max_length=50, blank=True, default='')
    description = models.TextField(blank=True, default='')
    scheduled_live_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.CharField(max_length=255, default='Super Admin')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_core', 'name']

    def __str__(self):
        status_str = "ACTIVE" if self.is_active else "INACTIVE"
        return f"{self.name} ({self.connector_key}) - {status_str}"


class ClientConnectorAccess(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='connector_accesses')
    connector_key = models.CharField(max_length=50, db_index=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    updated_by = models.CharField(max_length=255, default='Admin')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'connector_key')
        ordering = ['client', 'connector_key']

    def __str__(self):
        return f"{self.client.business_name} -> {self.connector_key}: {'ENABLED' if self.is_enabled else 'DISABLED'}"


class TeamMemberConnectorAccess(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='team_connector_accesses')
    team_member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='connector_accesses')
    connector_key = models.CharField(max_length=50, db_index=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    updated_by = models.CharField(max_length=255, default='Admin')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'team_member', 'connector_key')
        ordering = ['client', 'team_member', 'connector_key']

    def __str__(self):
        return f"{self.team_member.username} ({self.client.business_name}) -> {self.connector_key}: {'ALLOWED' if self.is_enabled else 'REVOKED'}"


class ChannelAuditLog(models.Model):
    ACTION_CHOICES = [
        ('GLOBAL_ACTIVATED', 'Global Connector Activated'),
        ('GLOBAL_DEACTIVATED', 'Global Connector Deactivated'),
        ('ACCESS_GRANTED', 'Client Access Granted'),
        ('ACCESS_REVOKED', 'Client Access Revoked'),
        ('BULK_GRANTED', 'Bulk Access Granted'),
        ('BULK_REVOKED', 'Bulk Access Revoked'),
        ('MEMBER_ASSIGNED', 'Member Channel Assigned'),
        ('MEMBER_REVOKED', 'Member Channel Revoked'),
    ]

    admin_user = models.CharField(max_length=255, default='Admin')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='channel_audit_logs')
    client_name = models.CharField(max_length=255, blank=True, default='')
    team_member = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='channel_audit_logs')
    team_member_name = models.CharField(max_length=255, blank=True, default='')
    channel = models.CharField(max_length=50) # whatsapp, facebook, instagram, etc.
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    previous_state = models.JSONField(default=dict, blank=True)
    new_state = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default='')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        client_desc = self.client.business_name if self.client else (self.client_name or 'Global')

# ==============================================================================
# PLAN MANAGEMENT & FEATURE ENTITLEMENT SYSTEM MODELS
# ==============================================================================

class Feature(models.Model):
    CATEGORY_CHOICES = [
        ('COMMUNICATION', 'Communication Channels'),
        ('CONNECTORS', 'Productivity & Cloud Connectors'),
        ('MESSAGING', 'Messaging & Conversations'),
        ('AI', 'AI & Intelligence'),
        ('CRM', 'CRM & Leads'),
        ('SALES', 'Sales, Invoicing & Documents'),
        ('TEAM', 'Team & Operations'),
        ('DOCUMENTS', 'Knowledge & Documents'),
        ('REPORTING', 'Analytics & Reports'),
        ('SETTINGS', 'Settings & Administration'),
    ]

    TYPE_CHOICES = [
        ('BOOLEAN', 'Boolean (On / Off)'),
        ('LIMIT', 'Limit Based (Configurable Count)'),
        ('USAGE', 'Usage Based (Monthly Quota)'),
        ('CONNECTOR', 'Connector / Integration'),
        ('CHANNEL', 'Communication Channel'),
        ('MODULE', 'Functional Module'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('DEPRECATED', 'Deprecated'),
    ]

    key = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='COMMUNICATION', db_index=True)
    feature_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='BOOLEAN')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    is_coming_soon = models.BooleanField(default=False, db_index=True)
    icon = models.CharField(max_length=50, default='Box')
    default_enabled = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.key}) [{self.category}]"


class Plan(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('ARCHIVED', 'Archived'),
    ]

    BILLING_CYCLE_CHOICES = [
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
        ('CUSTOM', 'Custom'),
        ('ONE_TIME', 'One Time'),
        ('NO_BILLING', 'No Billing / Free'),
    ]

    PLAN_TYPE_CHOICES = [
        ('STANDARD', 'Standard Tier'),
        ('CUSTOM', 'Custom Tailored'),
        ('AGENCY', 'Agency White-Label'),
        ('ENTERPRISE', 'Enterprise SLA'),
    ]

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default='INR')
    billing_cycle = models.CharField(max_length=30, choices=BILLING_CYCLE_CHOICES, default='MONTHLY')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', db_index=True)
    plan_type = models.CharField(max_length=30, choices=PLAN_TYPE_CHOICES, default='STANDARD')
    display_order = models.IntegerField(default=0)
    is_default = models.BooleanField(default=False)
    badge_text = models.CharField(max_length=50, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'price', 'name']

    def __str__(self):
        return f"{self.name} ({self.currency} {self.price}/{self.billing_cycle}) - {self.status}"

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def monthly_price(self):
        if self.metadata and isinstance(self.metadata, dict) and 'monthly_price' in self.metadata:
            return float(self.metadata['monthly_price'])
        return float(self.price)

    @property
    def yearly_price(self):
        if self.metadata and isinstance(self.metadata, dict) and 'yearly_price' in self.metadata:
            return float(self.metadata['yearly_price'])
        # Default: 20% discount from monthly * 12
        return round(self.monthly_price * 12 * 0.8, 2)

    @property
    def yearly_discount_percent(self):
        if self.metadata and isinstance(self.metadata, dict) and 'yearly_discount_percent' in self.metadata:
            return float(self.metadata['yearly_discount_percent'])
        return 20.0

    @property
    def max_channels(self):
        if self.metadata and isinstance(self.metadata, dict) and 'max_channels' in self.metadata:
            return int(self.metadata['max_channels'])
        name_lower = self.name.lower()
        if 'starter' in name_lower:
            return 1
        elif 'growth' in name_lower:
            return 2
        elif 'advanced' in name_lower:
            return 3
        return 1

    @property
    def allowed_channels(self):
        if self.metadata and isinstance(self.metadata, dict) and 'allowed_channels' in self.metadata:
            return self.metadata['allowed_channels']
        if self.metadata and isinstance(self.metadata, dict) and 'channels' in self.metadata:
            return self.metadata['channels']
        return ['whatsapp', 'facebook', 'instagram']

    @property
    def allowed_connectors(self):
        if self.metadata and isinstance(self.metadata, dict) and 'allowed_connectors' in self.metadata:
            return self.metadata['allowed_connectors']
        if self.metadata and isinstance(self.metadata, dict) and 'connectors' in self.metadata:
            return self.metadata['connectors']
        return []

    @property
    def allowed_features(self):
        if self.metadata and isinstance(self.metadata, dict) and 'allowed_features' in self.metadata:
            return self.metadata['allowed_features']
        if self.metadata and isinstance(self.metadata, dict) and 'feature_keys' in self.metadata:
            return self.metadata['feature_keys']
        return []


class PlanFeature(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='plan_features')
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name='plan_features')
    enabled = models.BooleanField(default=True, db_index=True)
    limit_value = models.IntegerField(null=True, blank=True, default=None) # null = unlimited / not applicable
    limit_type = models.CharField(max_length=50, blank=True, default='') # e.g. "count", "monthly_quota", "unlimited"
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('plan', 'feature')
        ordering = ['plan', 'feature__category', 'feature__name']

    def __str__(self):
        limit_str = f" [Limit: {self.limit_value}]" if self.limit_value is not None else " [Unlimited]"
        return f"{self.plan.name} -> {self.feature.key}: {'ENABLED' if self.enabled else 'DISABLED'}{limit_str}"


class ClientFeatureOverride(models.Model):
    OVERRIDE_TYPE_CHOICES = [
        ('ADD', 'Custom Addition (+)'),
        ('REMOVE', 'Custom Restriction (-)'),
        ('LIMIT_OVERRIDE', 'Limit Override'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='feature_overrides')
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name='client_overrides')
    override_type = models.CharField(max_length=20, choices=OVERRIDE_TYPE_CHOICES, default='ADD')
    limit_value = models.IntegerField(null=True, blank=True, default=None)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_feature_overrides')
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('client', 'feature')
        ordering = ['client', 'feature__category', 'feature__name']

    def __str__(self):
        return f"{self.client.business_name} -> {self.feature.key}: {self.override_type} ({self.limit_value})"


class PlanAuditLog(models.Model):
    action = models.CharField(max_length=100)
    admin_user = models.CharField(max_length=255, default='Admin')
    plan_name = models.CharField(max_length=100, blank=True, default='')
    feature_name = models.CharField(max_length=100, blank=True, default='')
    client_name = models.CharField(max_length=150, blank=True, default='')
    previous_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp}] {self.admin_user} - {self.action} (Plan: {self.plan_name}, Feature: {self.feature_name})"



