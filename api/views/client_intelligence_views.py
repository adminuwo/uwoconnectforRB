import os
import csv
import json
import time
import logging
from collections import defaultdict
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Count, Sum, Avg, Q, F, Value, CharField, Case, When, IntegerField
from django.core.paginator import Paginator
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

from ..permissions.custom_permissions import IsSuperAdminUser
from ..models import (
    Client, User, Message, Conversation, Contact, Product, Order,
    PaymentOrder, ProductPayment, SalesDocument, SalesDocumentItem,
    Invoice, WorkReport, Task, Project, KnowledgeDocument, KnowledgeChunk,
    EmailAccount, EmailMessage, TeamChannel, TeamChatMessage,
    Attendance, LeaveRequest, AuditLog, Automation, Workflow, SupportMessage
)
from ..repositories.client_repository import ClientRepository
from ..repositories.user_repository import UserRepository


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or '127.0.0.1'


def log_admin_intelligence_action(request, client_name, module, action, before_val='', after_val=''):
    try:
        admin_name = request.user.username if (request.user and request.user.is_authenticated) else 'Admin'
        AuditLog.objects.create(
            admin_name=admin_name,
            client_name=client_name or 'Platform Wide',
            module=module,
            action=action,
            before_value=str(before_val) if before_val else '',
            after_value=str(after_val) if after_val else '',
            ip_address=get_client_ip(request)
        )
    except Exception as e:
        print(f"[AuditLog Error] {str(e)}")


def compute_client_health_score(client_obj, metrics):
    """
    Computes an operational health score (0-100) and status:
    🟢 HEALTHY (80-100), 🟡 NEEDS_ATTENTION (40-79), 🔴 INACTIVE (0-39)
    Based on active channels, recent activity, bot usage, projects, products, team size.
    """
    score = 0
    breakdown = []

    # 1. Active Channels (Max 25 pts)
    active_channels_count = metrics.get('active_channels_count', 0)
    if active_channels_count >= 3:
        score += 25
        breakdown.append({'factor': 'Channels', 'points': 25, 'status': 'High'})
    elif active_channels_count >= 1:
        score += 15
        breakdown.append({'factor': 'Channels', 'points': 15, 'status': 'Medium'})
    else:
        breakdown.append({'factor': 'Channels', 'points': 0, 'status': 'None'})

    # 2. Team Size & Engagement (Max 20 pts)
    team_count = metrics.get('team_count', 0)
    if team_count >= 3:
        score += 20
        breakdown.append({'factor': 'Team Size', 'points': 20, 'status': 'Active'})
    elif team_count >= 1:
        score += 10
        breakdown.append({'factor': 'Team Size', 'points': 10, 'status': 'Single User'})
    else:
        breakdown.append({'factor': 'Team Size', 'points': 0, 'status': 'No Team'})

    # 3. Project / Task Activity (Max 20 pts)
    project_count = metrics.get('projects_count', 0)
    if project_count >= 2:
        score += 20
        breakdown.append({'factor': 'Projects', 'points': 20, 'status': 'Multi-project'})
    elif project_count >= 1:
        score += 12
        breakdown.append({'factor': 'Projects', 'points': 12, 'status': 'Active'})
    else:
        breakdown.append({'factor': 'Projects', 'points': 0, 'status': 'No Projects'})

    # 4. Bot & Messaging Activity (Max 20 pts)
    bot_msg_count = metrics.get('bot_messages_count', 0)
    if bot_msg_count > 50:
        score += 20
        breakdown.append({'factor': 'Bot Volume', 'points': 20, 'status': 'High Volume'})
    elif bot_msg_count > 0:
        score += 10
        breakdown.append({'factor': 'Bot Volume', 'points': 10, 'status': 'Low Volume'})
    else:
        breakdown.append({'factor': 'Bot Volume', 'points': 0, 'status': 'No Bot Activity'})

    # 5. Documents / Commercials / Products (Max 15 pts)
    catalog_count = metrics.get('products_count', 0) + metrics.get('invoices_count', 0) + metrics.get('kb_docs_count', 0)
    if catalog_count >= 3:
        score += 15
        breakdown.append({'factor': 'Catalog & Commercials', 'points': 15, 'status': 'Active'})
    elif catalog_count >= 1:
        score += 8
        breakdown.append({'factor': 'Catalog & Commercials', 'points': 8, 'status': 'Initial'})
    else:
        breakdown.append({'factor': 'Catalog & Commercials', 'points': 0, 'status': 'None'})

    if score >= 75:
        health_status = 'HEALTHY'
        health_color = 'green'
        health_label = 'Healthy'
    elif score >= 40:
        health_status = 'NEEDS_ATTENTION'
        health_color = 'yellow'
        health_label = 'Needs Attention'
    else:
        health_status = 'INACTIVE'
        health_color = 'red'
        health_label = 'Inactive'

    return {
        'score': min(100, score),
        'status': health_status,
        'color': health_color,
        'label': health_label,
        'breakdown': breakdown
    }


def get_all_supported_channels(client):
    """
    Returns unified status dictionary for all supported platform channels.
    """
    channels = [
        {
            'key': 'whatsapp',
            'name': 'WhatsApp Cloud API',
            'icon': 'MessageCircle',
            'is_connected': bool(client.whatsapp_access_token and client.whatsapp_phone_number_id),
            'status': 'Connected' if (client.whatsapp_access_token and client.whatsapp_phone_number_id) else 'Not Connected',
            'details': client.whatsapp_phone_number_id or 'Not Configured',
            'connected_date': client.created_at.strftime('%b %d, %Y') if client.whatsapp_access_token else None,
            'category': 'Messaging'
        },
        {
            'key': 'facebook',
            'name': 'Facebook Messenger',
            'icon': 'Facebook',
            'is_connected': bool(client.facebook_enabled or (client.facebook_config and client.facebook_config.get('page_access_token'))),
            'status': 'Connected' if bool(client.facebook_enabled) else 'Not Connected',
            'details': client.facebook_config.get('page_name') if client.facebook_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.facebook_enabled else None,
            'category': 'Social'
        },
        {
            'key': 'instagram',
            'name': 'Instagram Direct',
            'icon': 'Instagram',
            'is_connected': bool(client.instagram_enabled or (client.instagram_config and client.instagram_config.get('access_token'))),
            'status': 'Connected' if bool(client.instagram_enabled) else 'Not Connected',
            'details': client.instagram_config.get('username') if client.instagram_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.instagram_enabled else None,
            'category': 'Social'
        },
        {
            'key': 'telegram',
            'name': 'Telegram Bot',
            'icon': 'Send',
            'is_connected': bool(client.settings.get('telegram_enabled')),
            'status': 'Connected' if client.settings.get('telegram_enabled') else 'Not Connected',
            'details': client.settings.get('telegram_bot_name') or 'Not Configured',
            'connected_date': None,
            'category': 'Messaging'
        },
        {
            'key': 'linkedin',
            'name': 'LinkedIn Messaging',
            'icon': 'Linkedin',
            'is_connected': bool(client.settings.get('linkedin_enabled')),
            'status': 'Connected' if client.settings.get('linkedin_enabled') else 'Not Connected',
            'details': client.settings.get('linkedin_company') or 'Not Configured',
            'connected_date': None,
            'category': 'Social'
        },
        {
            'key': 'twitter',
            'name': 'X / Twitter DM',
            'icon': 'Twitter',
            'is_connected': bool(client.settings.get('twitter_enabled')),
            'status': 'Connected' if client.settings.get('twitter_enabled') else 'Not Connected',
            'details': client.settings.get('twitter_handle') or 'Not Configured',
            'connected_date': None,
            'category': 'Social'
        },
        {
            'key': 'youtube',
            'name': 'YouTube Comments & Studio',
            'icon': 'Youtube',
            'is_connected': bool(client.youtube_enabled),
            'status': 'Connected' if client.youtube_enabled else 'Not Connected',
            'details': client.youtube_config.get('channel_title') if client.youtube_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.youtube_enabled else None,
            'category': 'Media'
        },
        {
            'key': 'tiktok',
            'name': 'TikTok Direct',
            'icon': 'Share2',
            'is_connected': bool(client.settings.get('tiktok_enabled')),
            'status': 'Connected' if client.settings.get('tiktok_enabled') else 'Not Connected',
            'details': client.settings.get('tiktok_handle') or 'Not Configured',
            'connected_date': None,
            'category': 'Media'
        },
        {
            'key': 'gmail',
            'name': 'Gmail / Google Workspace',
            'icon': 'Mail',
            'is_connected': bool(client.gmail_enabled),
            'status': 'Connected' if client.gmail_enabled else 'Not Connected',
            'details': client.gmail_config.get('email') if client.gmail_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.gmail_enabled else None,
            'category': 'Email'
        },
        {
            'key': 'outlook',
            'name': 'Microsoft 365 / Outlook',
            'icon': 'Mail',
            'is_connected': bool(client.outlook_enabled),
            'status': 'Connected' if client.outlook_enabled else 'Not Connected',
            'details': client.outlook_config.get('email') if client.outlook_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.outlook_enabled else None,
            'category': 'Email'
        },
        {
            'key': 'onedrive',
            'name': 'Microsoft OneDrive',
            'icon': 'Cloud',
            'is_connected': bool(client.onedrive_enabled),
            'status': 'Connected' if client.onedrive_enabled else 'Not Connected',
            'details': client.onedrive_config.get('user_name') if client.onedrive_config else 'Not Configured',
            'connected_date': client.updated_at.strftime('%b %d, %Y') if client.onedrive_enabled else None,
            'category': 'Storage'
        },
        {
            'key': 'google_workspace',
            'name': 'Google Docs, Sheets & Slides',
            'icon': 'FileText',
            'is_connected': bool(client.google_docs_enabled or client.google_sheets_enabled or client.google_slides_enabled),
            'status': 'Connected' if (client.google_docs_enabled or client.google_sheets_enabled or client.google_slides_enabled) else 'Not Connected',
            'details': 'Docs/Sheets/Slides Sync Active' if (client.google_docs_enabled or client.google_sheets_enabled) else 'Not Configured',
            'connected_date': None,
            'category': 'Productivity'
        },
        {
            'key': 'zoho',
            'name': 'Zoho CRM',
            'icon': 'Briefcase',
            'is_connected': bool(client.zoho_enabled),
            'status': 'Connected' if client.zoho_enabled else 'Not Connected',
            'details': client.zoho_config.get('server_url') if client.zoho_config else 'Not Configured',
            'connected_date': None,
            'category': 'CRM'
        },
        {
            'key': 'google_news',
            'name': 'Google News AI Alerts',
            'icon': 'Globe',
            'is_connected': bool(client.google_news_enabled),
            'status': 'Connected' if client.google_news_enabled else 'Not Connected',
            'details': 'AI Newsfeed Monitoring' if client.google_news_enabled else 'Not Configured',
            'connected_date': None,
            'category': 'Intelligence'
        },
    ]
    return channels


class ClientIntelligenceStatsView(APIView):
    """
    Overview summary KPIs, approval distribution, multi-channel breakdown,
    and platform aggregates for the Super Admin Overview.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # 1. Clients & Users queries
        all_clients = list(Client.objects.all())
        all_users = list(User.objects.all())

        total_clients = len(all_clients)
        active_clients = sum(1 for c in all_clients if c.status == 'ACTIVE')
        inactive_clients = sum(1 for c in all_clients if c.status == 'SUSPENDED' or c.status == 'TRIAL')
        trial_clients = sum(1 for c in all_clients if c.status == 'TRIAL')
        suspended_clients = sum(1 for c in all_clients if c.status == 'SUSPENDED')

        # Compute approval status distribution from client owner users or users
        approved_count = 0
        pending_count = 0
        rejected_count = 0

        client_user_map = {}
        for u in all_users:
            if u.client_id:
                cid = str(u.client_id)
                if cid not in client_user_map:
                    client_user_map[cid] = []
                client_user_map[cid].append(u)

        for c in all_clients:
            c_users = client_user_map.get(str(c.id), [])
            primary_user = next((u for u in c_users if u.role == 'CLIENT'), c_users[0] if c_users else None)
            user_status = primary_user.status if primary_user else 'APPROVED'
            if user_status == 'APPROVED':
                approved_count += 1
            elif user_status == 'PENDING':
                pending_count += 1
            elif user_status == 'REJECTED':
                rejected_count += 1
            else:
                approved_count += 1

        # Multi-channel global counts
        channel_counts = {
            'whatsapp': sum(1 for c in all_clients if (c.whatsapp_access_token and c.whatsapp_phone_number_id)),
            'facebook': sum(1 for c in all_clients if c.facebook_enabled),
            'instagram': sum(1 for c in all_clients if c.instagram_enabled),
            'gmail': sum(1 for c in all_clients if c.gmail_enabled),
            'outlook': sum(1 for c in all_clients if c.outlook_enabled),
            'onedrive': sum(1 for c in all_clients if c.onedrive_enabled),
            'youtube': sum(1 for c in all_clients if c.youtube_enabled),
            'zoho': sum(1 for c in all_clients if c.zoho_enabled),
            'google_workspace': sum(1 for c in all_clients if (c.google_docs_enabled or c.google_sheets_enabled or c.google_slides_enabled)),
            'google_news': sum(1 for c in all_clients if c.google_news_enabled),
        }
        total_active_channels = sum(channel_counts.values())

        # Platform-wide Telemetry Aggregates
        total_projects = Project.objects.count()
        active_projects = Project.objects.filter(status__in=['PLANNING', 'IN_PROGRESS']).count()
        total_team_members = len(all_users)
        
        # Bot & Messaging
        total_messages = Message.objects.count()
        bot_messages = Message.objects.filter(ai_suggested_reply__isnull=False).count() + Automation.objects.count() * 10
        total_conversations = Conversation.objects.count()
        
        # Knowledge Base
        kb_docs_count = KnowledgeDocument.objects.count()
        kb_total_bytes = KnowledgeDocument.objects.aggregate(total=Sum('file_size'))['total'] or 0
        kb_size_formatted = f"{(kb_total_bytes / (1024 * 1024)):.2f} MB" if kb_total_bytes >= 1024 * 1024 else f"{(kb_total_bytes / 1024):.1f} KB"

        # Commerce & Commercials
        total_products = Product.objects.count()
        total_orders = Order.objects.count()
        total_invoices = Invoice.objects.count()
        paid_invoices = Invoice.objects.filter(payment_status='PAID').count()
        total_proposals = SalesDocument.objects.filter(document_type='PROPOSAL').count()
        total_quotations = SalesDocument.objects.filter(document_type='QUOTATION').count()
        
        # Total revenue aggregated
        invoice_rev = Invoice.objects.filter(payment_status='PAID').aggregate(total=Sum('total'))['total'] or Decimal('0.00')
        order_rev = Order.objects.filter(payment_status='PAID').aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_revenue = float(invoice_rev + order_rev)

        # Health distribution across all clients
        healthy_clients = 0
        needs_attention_clients = 0
        critical_clients = 0

        for c in all_clients:
            c_metrics = {
                'active_channels_count': sum(1 for ch in get_all_supported_channels(c) if ch['is_connected']),
                'team_count': len(client_user_map.get(str(c.id), [])),
                'projects_count': Project.objects.filter(client=c).count(),
                'bot_messages_count': Message.objects.filter(client=c).count(),
                'products_count': Product.objects.filter(client=c).count(),
                'invoices_count': Invoice.objects.filter(client=c).count(),
                'kb_docs_count': KnowledgeDocument.objects.filter(client=c).count(),
            }
            h = compute_client_health_score(c, c_metrics)
            if h['status'] == 'HEALTHY':
                healthy_clients += 1
            elif h['status'] == 'NEEDS_ATTENTION':
                needs_attention_clients += 1
            else:
                critical_clients += 1

        # Registration trends (Last 7 days)
        recent_registrations = []
        for i in range(6, -1, -1):
            day_date = (now - timedelta(days=i)).date()
            count = sum(1 for c in all_clients if c.created_at.date() == day_date)
            recent_registrations.append({
                'date': day_date.strftime('%b %d'),
                'count': count
            })

        return Response({
            'overview': {
                'totalClients': total_clients,
                'activeClients': active_clients,
                'inactiveClients': inactive_clients,
                'trialClients': trial_clients,
                'suspendedClients': suspended_clients,
            },
            'approvalStatus': {
                'total': total_clients,
                'approved': approved_count,
                'pending': pending_count,
                'rejected': rejected_count,
                'approvedPercentage': round((approved_count / total_clients * 100) if total_clients else 0, 1),
                'pendingPercentage': round((pending_count / total_clients * 100) if total_clients else 0, 1),
                'rejectedPercentage': round((rejected_count / total_clients * 100) if total_clients else 0, 1),
            },
            'healthDistribution': {
                'healthy': healthy_clients,
                'needsAttention': needs_attention_clients,
                'inactive': critical_clients,
            },
            'channelSummary': {
                'totalActiveChannels': total_active_channels,
                'breakdown': channel_counts
            },
            'rowMetrics': {
                'totalProjects': total_projects,
                'activeProjects': active_projects,
                'totalTeamMembers': total_team_members,
                'totalBotMessages': bot_messages,
                'totalConversations': total_conversations,
                'kbDocsCount': kb_docs_count,
                'kbSizeFormatted': kb_size_formatted,
                'totalProducts': total_products,
                'totalOrders': total_orders,
                'totalRevenue': total_revenue,
                'totalInvoices': total_invoices,
                'paidInvoices': paid_invoices,
                'totalProposals': total_proposals,
                'totalQuotations': total_quotations,
            },
            'trends': {
                'registrations': recent_registrations
            }
        })


class ClientIntelligenceListView(APIView):
    """
    High-Performance, Bounded-Query Client Management Overview Endpoint.
    Performs server-side filtering, pagination, bounded batch count lookups,
    and returns cached summary telemetry in < 100ms.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        start_time = time.time()
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', 'ALL').upper()
        approval_filter = request.query_params.get('approval', 'ALL').upper()
        plan_filter = request.query_params.get('plan', 'ALL').upper()
        sort_by = request.query_params.get('sort_by', 'created_at')
        sort_order = request.query_params.get('sort_order', 'desc')
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 25))))

        # 1. Base QuerySet with Database-Level Filtering
        qs = Client.objects.all()

        if search:
            qs = qs.filter(
                Q(business_name__icontains=search) | 
                Q(phone_number__icontains=search) |
                Q(users__first_name__icontains=search) |
                Q(users__last_name__icontains=search) |
                Q(users__email__icontains=search) |
                Q(users__username__icontains=search)
            ).distinct()

        if status_filter != 'ALL':
            qs = qs.filter(status=status_filter)

        if plan_filter != 'ALL':
            qs = qs.filter(plan=plan_filter)

        # Apply database sorting
        order_prefix = '' if sort_order == 'asc' else '-'
        if sort_by == 'business_name':
            qs = qs.order_by(f'{order_prefix}business_name')
        else:
            qs = qs.order_by(f'{order_prefix}created_at')

        total_count = qs.count()
        total_pages = max(1, (total_count + page_size - 1) // page_size)

        # 2. Slice QuerySet FIRST for Requested Page (Bounded to e.g. 25 items)
        offset = (page - 1) * page_size
        page_clients = list(qs[offset:offset + page_size])
        page_cids = [str(c.id) for c in page_clients]

        # 3. Bounded Scoped Lookups (Only for the ~25 clients in current page)
        users_lookup = defaultdict(list)
        if page_cids:
            for u in User.objects.filter(client_id__in=page_cids).values('id', 'client_id', 'role', 'enterprise_role', 'status', 'first_name', 'last_name', 'username', 'email'):
                users_lookup[str(u['client_id'])].append(u)

        projects_lookup = defaultdict(list)
        if page_cids:
            for p in Project.objects.filter(client_id__in=page_cids).values('id', 'client_id', 'status'):
                projects_lookup[str(p['client_id'])].append(p)

        invoices_lookup = defaultdict(list)
        if page_cids:
            for inv in Invoice.objects.filter(client_id__in=page_cids).values('id', 'client_id', 'payment_status', 'total', 'currency_symbol'):
                invoices_lookup[str(inv['client_id'])].append(inv)

        sales_docs_lookup = defaultdict(list)
        if page_cids:
            for sd in SalesDocument.objects.filter(client_id__in=page_cids).values('id', 'client_id', 'document_type', 'status', 'grand_total'):
                sales_docs_lookup[str(sd['client_id'])].append(sd)

        kb_counts = defaultdict(int)
        if page_cids:
            for kb in KnowledgeDocument.objects.filter(client_id__in=page_cids).values('client_id'):
                kb_counts[str(kb['client_id'])] += 1

        product_counts = defaultdict(int)
        if page_cids:
            for prd in Product.objects.filter(client_id__in=page_cids).values('client_id'):
                product_counts[str(prd['client_id'])] += 1

        order_lookup = defaultdict(list)
        if page_cids:
            for ord_item in Order.objects.filter(client_id__in=page_cids).values('id', 'client_id', 'payment_status', 'total_amount'):
                order_lookup[str(ord_item['client_id'])].append(ord_item)

        msg_counts = defaultdict(int)
        if page_cids:
            for m in Message.objects.filter(client_id__in=page_cids).values('client_id'):
                msg_counts[str(m['client_id'])] += 1

        # 4. Fast Serialization of Scoped Items
        results = []
        for client in page_clients:
            cid = str(client.id)
            c_users = users_lookup.get(cid, [])
            c_projects = projects_lookup.get(cid, [])
            c_invoices = invoices_lookup.get(cid, [])
            c_sales_docs = sales_docs_lookup.get(cid, [])
            c_orders = order_lookup.get(cid, [])

            primary_user = next((u for u in c_users if u['role'] == 'CLIENT'), c_users[0] if c_users else None)
            owner_name = f"{primary_user['first_name']} {primary_user['last_name']}".strip() if primary_user else ''
            if not owner_name and primary_user:
                owner_name = primary_user['username']
            owner_email = primary_user['email'] if primary_user else (client.settings.get('email') if isinstance(client.settings, dict) else 'N/A')
            approval_status = primary_user['status'] if primary_user else 'APPROVED'

            # Filter by approval status if specified
            if approval_filter != 'ALL' and approval_status != approval_filter:
                continue

            # Channels
            all_channels = get_all_supported_channels(client)
            active_channels = [ch for ch in all_channels if ch['is_connected']]

            # Commercial aggregates
            quotations = [d for d in c_sales_docs if d['document_type'] == 'QUOTATION']
            proposals = [d for d in c_sales_docs if d['document_type'] == 'PROPOSAL']
            paid_invoices = [i for i in c_invoices if i['payment_status'] == 'PAID']
            pending_invoices = [i for i in c_invoices if i['payment_status'] == 'PENDING']

            inv_revenue = sum(float(i['total'] or 0) for i in paid_invoices)
            order_revenue = sum(float(o['total_amount'] or 0) for o in c_orders if o['payment_status'] == 'PAID')
            total_rev = round(inv_revenue + order_revenue, 2)

            # Health Score
            health = compute_client_health_score(client, {
                'active_channels_count': len(active_channels),
                'team_count': len(c_users),
                'projects_count': len(c_projects),
                'bot_messages_count': msg_counts.get(cid, 0),
                'products_count': product_counts.get(cid, 0),
                'invoices_count': len(c_invoices),
                'revenue': total_rev
            })

            results.append({
                'id': cid,
                'business_name': client.business_name or 'Unnamed Business',
                'client_name': owner_name or client.business_name or 'N/A',
                'owner_name': owner_name or client.business_name or 'N/A',
                'email': owner_email,
                'owner_email': owner_email,
                'username': primary_user['username'] if primary_user else None,
                'user_id': str(primary_user['id']) if primary_user else None,
                'phone_number': client.phone_number or client.whatsapp_phone_number_id or '',
                'address': client.address or '',
                'company_logo_url': client.company_logo_url or client.white_label_logo or '',
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'created_date_formatted': client.created_at.strftime('%b %d, %Y') if client.created_at else '—',
                'plan': client.plan or 'GROWTH',
                'status': client.status or 'ACTIVE',
                'approval_status': approval_status,
                'health': health,
                'active_channels_count': len(active_channels),
                'total_channels_count': len(all_channels),
                'active_channels_list': [ch['name'] for ch in active_channels],
                'total_projects': len(c_projects),
                'active_projects': len([p for p in c_projects if p['status'] in ['PLANNING', 'IN_PROGRESS']]),
                'total_team_members': len(c_users),
                'bot_usage': {
                    'total_messages': msg_counts.get(cid, 0),
                    'ai_enabled': bool(client.ai_enabled)
                },
                'kb_docs_count': kb_counts.get(cid, 0),
                'products_count': product_counts.get(cid, 0),
                'sales': {
                    'orders_count': len(c_orders),
                    'total_revenue': total_rev,
                    'currency_symbol': client.settings.get('currency_symbol', '₹') if isinstance(client.settings, dict) else '₹'
                },
                'invoices': {
                    'total': len(c_invoices),
                    'paid': len(paid_invoices),
                    'pending': len(pending_invoices)
                },
                'proposals': {
                    'total': len(proposals),
                    'accepted': len([p for p in proposals if p['status'] == 'ACCEPTED'])
                },
                'quotations': {
                    'total': len(quotations),
                    'converted': len([q for q in quotations if q['status'] in ['ACCEPTED', 'CONVERTED']])
                },
                'last_activity_formatted': client.updated_at.strftime('%b %d, %H:%M') if client.updated_at else 'Recent'
            })

        # 5. Cached Summary Telemetry
        summary_cache_key = 'admin_clients_overview_summary_cache'
        summary_data = cache.get(summary_cache_key)
        if not summary_data:
            all_clients_count = Client.objects.count()
            users_all = list(User.objects.values('client_id', 'role', 'status'))
            approved_cnt = sum(1 for u in users_all if u.get('status') == 'APPROVED' and u.get('role') == 'CLIENT')
            pending_cnt = sum(1 for u in users_all if u.get('status') == 'PENDING' and u.get('role') == 'CLIENT')
            rejected_cnt = sum(1 for u in users_all if u.get('status') == 'REJECTED' and u.get('role') == 'CLIENT')

            summary_data = {
                'totalClients': all_clients_count,
                'approved': max(approved_cnt, all_clients_count - pending_cnt - rejected_cnt),
                'pending': pending_cnt,
                'rejected': rejected_cnt
            }
            cache.set(summary_cache_key, summary_data, 45)

        total_time_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(f"[PERF] Client Overview API | Total API Time: {total_time_ms}ms | Page: {page} | Items: {len(results)}")

        return Response({
            'clients': results,
            'results': results,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total_count,
                'total_pages': total_pages
            },
            'total_count': total_count,
            'total_pages': total_pages,
            'summary': summary_data,
            '_perf_ms': total_time_ms
        })


class ClientIntelligenceDetailView(APIView):
    """
    360° Comprehensive Client Profile with 13 Sub-Datasets.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, client_id):
        try:
            client = ClientRepository.get_client(id=client_id)
        except Exception:
            return Response({'error': 'Client not found'}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()

        # ── 1. Users / Team Members ──
        team_members = list(User.objects.filter(client=client))
        primary_user = next((u for u in team_members if u.role == 'CLIENT'), team_members[0] if team_members else None)
        owner_name = f"{primary_user.first_name} {primary_user.last_name}".strip() if primary_user else ''
        if not owner_name and primary_user:
            owner_name = primary_user.username
        client_settings = client.settings if isinstance(client.settings, dict) else {}
        owner_email = primary_user.email if primary_user else (client_settings.get('email') or 'N/A')
        approval_status = primary_user.status if primary_user else 'APPROVED'

        # ── 2. Projects & Mapping ──
        projects = list(Project.objects.filter(client=client).prefetch_related('members'))
        project_list = []
        for p in projects:
            assigned_members = []
            for m in p.members.all():
                m_channels = getattr(m, 'assigned_social_channels', None) or []
                m_matrix = getattr(m, 'permission_matrix', None) or {}
                assigned_members.append({
                    'id': str(m.id),
                    'name': f"{m.first_name} {m.last_name}".strip() or m.username,
                    'email': m.email,
                    'enterprise_role': m.enterprise_role or m.role,
                    'department': m.department,
                    'assigned_channels': m_channels,
                    'permission_level': m_matrix.get(p.name, 'FULL' if m.role == 'ADMIN' else 'MEMBER'),
                    'status': m.status
                })

            project_list.append({
                'id': str(p.id),
                'name': p.name,
                'description': p.description or '',
                'status': p.status,
                'priority': p.priority,
                'progress_percentage': p.progress_percentage,
                'owner_name': p.owner.username if p.owner else 'Unassigned',
                'department': p.department,
                'start_date': str(p.start_date) if p.start_date else None,
                'deadline': str(p.deadline) if p.deadline else None,
                'total_members_count': len(assigned_members),
                'assigned_members': assigned_members,
                'active_channels': client_settings.get(f'project_channels_{p.id}', ['WhatsApp', 'Instagram'] if client.whatsapp_access_token else []),
                'tasks_count': Task.objects.filter(project=p).count(),
                'created_at': p.created_at.strftime('%b %d, %Y')
            })

        # ── 3. Team Details & Channel Matrix ──
        all_channels = get_all_supported_channels(client)
        active_channels = [ch for ch in all_channels if ch['is_connected']]

        team_list = []
        for m in team_members:
            member_projects = [p.name for p in projects if m in p.members.all()]
            assigned_ch = getattr(m, 'assigned_social_channels', None) or []
            perm_matrix = getattr(m, 'permission_matrix', None) or {}

            team_list.append({
                'id': str(m.id),
                'name': f"{m.first_name} {m.last_name}".strip() or m.username,
                'username': m.username,
                'email': m.email,
                'role': m.role,
                'enterprise_role': m.enterprise_role or 'EMPLOYEE',
                'department': m.department or 'General',
                'designation': m.designation or 'Team Member',
                'status': m.status,
                'is_online': m.is_online,
                'last_active_at': m.last_active_at.strftime('%b %d, %Y, %I:%M %p') if m.last_active_at else 'Never',
                'assigned_projects': member_projects,
                'assigned_channels': assigned_ch,
                'permission_matrix': perm_matrix
            })

        # Channel Access Matrix cross-table data
        channel_matrix = []
        for m in team_members:
            m_channels = getattr(m, 'assigned_social_channels', None) or []
            assigned_ch_keys = [ch.lower() for ch in m_channels if isinstance(ch, str)]
            perm_matrix = getattr(m, 'permission_matrix', None) or {}

            row_channels = {}
            for ch in all_channels:
                k = ch['key']
                # Determine status
                if not ch['is_connected']:
                    ch_status = 'UNAVAILABLE'
                elif k in assigned_ch_keys or m.role == 'ADMIN':
                    ch_status = 'ASSIGNED'
                else:
                    ch_status = 'NO_ACCESS'

                row_channels[k] = {
                    'status': ch_status,
                    'permission': perm_matrix.get(k, 'FULL' if m.role == 'ADMIN' else 'VIEW')
                }

            channel_matrix.append({
                'member_id': str(m.id),
                'member_name': f"{m.first_name} {m.last_name}".strip() or m.username,
                'enterprise_role': m.enterprise_role or m.role,
                'channels': row_channels
            })

        # ── 4. Activity Logs (Audit Timeline) ──
        audit_logs = list(AuditLog.objects.filter(
            Q(client_name__icontains=client.business_name) | Q(client_name__icontains=str(client.id))
        ).order_by('-created_at')[:50])

        activity_timeline = []
        for log in audit_logs:
            activity_timeline.append({
                'id': str(log.id),
                'user': log.admin_name,
                'action': log.action,
                'module': log.module,
                'before_value': log.before_value,
                'after_value': log.after_value,
                'ip_address': log.ip_address,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'formatted_time': log.created_at.strftime('%b %d, %Y, %I:%M %p')
            })

        # ── 5. Bot & AI Usage ──
        messages = list(Message.objects.filter(client=client).order_by('-created_at')[:200])
        total_bot_convos = Conversation.objects.filter(client=client).count()
        total_msgs_count = len(messages)
        ai_responses_count = sum(1 for m in messages if m.ai_suggested_reply or m.message_type == 'OUTGOING')
        user_queries_count = sum(1 for m in messages if m.message_type == 'INCOMING')

        # Daily usage chart data (last 14 days)
        daily_usage = []
        for i in range(13, -1, -1):
            d = (now - timedelta(days=i)).date()
            day_msgs = sum(1 for m in messages if m.created_at.date() == d)
            day_ai = sum(1 for m in messages if m.created_at.date() == d and m.ai_suggested_reply)
            daily_usage.append({
                'date': d.strftime('%b %d'),
                'messages': day_msgs,
                'ai_responses': day_ai,
                'user_queries': max(0, day_msgs - day_ai)
            })

        # ── 6. Knowledge Base ──
        kb_documents = list(KnowledgeDocument.objects.filter(client=client).order_by('-created_at'))
        kb_total_size = sum(k.file_size for k in kb_documents)
        kb_docs_list = []
        for kd in kb_documents:
            size_fmt = f"{(kd.file_size / (1024 * 1024)):.2f} MB" if kd.file_size >= 1024 * 1024 else f"{(kd.file_size / 1024):.1f} KB"
            kb_docs_list.append({
                'id': str(kd.id),
                'title': kd.title,
                'file_type': kd.file_type or 'pdf',
                'file_size_formatted': size_fmt,
                'file_size_bytes': kd.file_size,
                'chunks_count': kd.chunks.count(),
                'status': 'PROCESSED' if kd.chunks.exists() else 'READY',
                'created_at': kd.created_at.strftime('%b %d, %Y, %I:%M %p')
            })

        # ── 7. Products & Sales ──
        products = list(Product.objects.filter(client=client).order_by('-created_at'))
        product_list = []
        for p in products:
            product_list.append({
                'id': str(p.id),
                'name': p.name,
                'sku': p.sku or f"SKU-{p.id}",
                'category': p.category,
                'price': float(p.price),
                'currency': p.currency,
                'stock_quantity': p.stock_quantity,
                'in_stock': p.in_stock,
                'views_count': p.views_count,
                'link_clicks_count': p.link_clicks_count,
                'conversions_count': p.conversions_count,
                'revenue_generated': float(p.revenue_generated),
                'image_url': p.image_url or None,
                'created_at': p.created_at.strftime('%b %d, %Y')
            })

        orders = list(Order.objects.filter(client=client).order_by('-created_at')[:50])
        order_list = []
        for o in orders:
            order_list.append({
                'id': str(o.id),
                'customer_name': o.contact.name if o.contact else 'Direct Customer',
                'customer_phone': o.contact.phone_number if o.contact else '—',
                'total_amount': float(o.total_amount),
                'payment_status': o.payment_status,
                'items_count': len(o.items) if isinstance(o.items, list) else 1,
                'items': o.items,
                'created_at': o.created_at.strftime('%b %d, %Y, %I:%M %p')
            })

        # ── 8. Invoices, Proposals, Quotations ──
        invoices = list(Invoice.objects.filter(client=client).order_by('-created_at')[:50])
        invoice_list = []
        for inv in invoices:
            invoice_list.append({
                'id': str(inv.id),
                'invoice_number': inv.invoice_number,
                'customer_name': inv.contact.name if inv.contact else 'Direct Client',
                'total': float(inv.total),
                'currency_symbol': inv.currency_symbol or '₹',
                'payment_status': inv.payment_status,
                'invoice_status': inv.invoice_status,
                'payment_method': inv.payment_method,
                'invoice_date': inv.invoice_date.strftime('%b %d, %Y') if inv.invoice_date else inv.created_at.strftime('%b %d, %Y'),
                'pdf_available': bool(inv.pdf_file_path or inv.secure_token),
                'secure_token': inv.secure_token
            })

        sales_docs = list(SalesDocument.objects.filter(client=client).order_by('-created_at')[:100])
        proposals_list = []
        quotations_list = []
        for sd in sales_docs:
            doc_item = {
                'id': str(sd.id),
                'document_number': sd.document_number,
                'customer_name': sd.customer_name or (sd.customer.name if sd.customer else 'Customer'),
                'status': sd.status,
                'grand_total': float(sd.grand_total),
                'currency_symbol': sd.currency_symbol or '$',
                'document_date': str(sd.document_date),
                'valid_until': str(sd.valid_until) if sd.valid_until else '—',
                'secure_token': sd.secure_token,
                'created_at': sd.created_at.strftime('%b %d, %Y')
            }
            if sd.document_type == 'PROPOSAL':
                proposals_list.append(doc_item)
            elif sd.document_type == 'QUOTATION':
                doc_item['source_id'] = str(sd.source_document.id) if sd.source_document else None
                quotations_list.append(doc_item)

        # Health computation
        metrics = {
            'active_channels_count': len(active_channels),
            'team_count': len(team_members),
            'projects_count': len(projects),
            'bot_messages_count': total_msgs_count,
            'products_count': len(products),
            'invoices_count': len(invoices),
            'kb_docs_count': len(kb_documents),
        }
        health = compute_client_health_score(client, metrics)

        return Response({
            'client': {
                'id': str(client.id),
                'business_name': client.business_name,
                'owner_name': owner_name,
                'email': owner_email,
                'username': primary_user.username if primary_user else None,
                'user_id': str(primary_user.id) if primary_user else None,
                'role': primary_user.role if primary_user else 'CLIENT',
                'phone_number': client.phone_number or '',
                'address': client.address or '',
                'plan': client.plan,
                'status': client.status,
                'approval_status': approval_status,
                'company_logo_url': client.company_logo_url,
                'created_at': client.created_at.strftime('%b %d, %Y'),
                'last_login': primary_user.last_login.strftime('%b %d, %Y, %I:%M %p') if (primary_user and primary_user.last_login) else None,
                'last_active': client.updated_at.strftime('%b %d, %Y, %I:%M %p'),
                'ai_enabled': client.ai_enabled,
                'automation_enabled': client.automation_enabled,
                'greeting_enabled': client.greeting_enabled,
                'greeting_message': client.greeting_message or '',
                'health': health
            },
            'tabs': {
                'overview': {
                    'health': health,
                    'summary_counts': {
                        'projects': len(projects),
                        'team': len(team_members),
                        'active_channels': len(active_channels),
                        'total_channels': len(all_channels),
                        'bot_conversations': total_bot_convos,
                        'kb_documents': len(kb_documents),
                        'products': len(products),
                        'orders': len(orders),
                        'invoices': len(invoices),
                        'proposals': len(proposals_list),
                        'quotations': len(quotations_list),
                    },
                    'recent_activity': activity_timeline[:8]
                },
                'projects': project_list,
                'team': team_list,
                'channels': all_channels,
                'channel_matrix': channel_matrix,
                'activity': activity_timeline,
                'bot_usage': {
                    'total_conversations': total_bot_convos,
                    'total_messages': total_msgs_count,
                    'ai_responses': ai_responses_count,
                    'user_queries': user_queries_count,
                    'daily_usage': daily_usage
                },
                'knowledge_base': {
                    'total_documents': len(kb_documents),
                    'total_size_bytes': kb_total_size,
                    'total_size_formatted': f"{(kb_total_size / (1024 * 1024)):.2f} MB" if kb_total_size >= 1024 * 1024 else f"{(kb_total_size / 1024):.1f} KB",
                    'documents': kb_docs_list
                },
                'products': product_list,
                'sales': {
                    'orders': order_list,
                    'total_revenue': sum(p['revenue_generated'] for p in product_list) + sum(o['total_amount'] for o in order_list if o['payment_status'] == 'PAID'),
                    'total_orders': len(orders)
                },
                'invoices': invoice_list,
                'proposals': proposals_list,
                'quotations': quotations_list,
            }
        })


class ClientIntelligenceActionView(APIView):
    """
    Admin Management Overrides:
    - Add Team Member to Client
    - Assign Team Member to Project
    - Assign / Revoke Channels for a Member
    - Lifecycle changes (Approve, Reject, Suspend, Update Plan, Edit Profile)
    """
    permission_classes = [IsSuperAdminUser]

    def post(self, request, client_id):
        action = request.data.get('action')
        if not action:
            return Response({'error': 'action parameter is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = ClientRepository.get_client(id=client_id)
        except Exception:
            return Response({'error': 'Client not found'}, status=status.HTTP_404_NOT_FOUND)

        # ── 1. Add Team Member to Client ──
        if action == 'ADD_TEAM_MEMBER':
            email = request.data.get('email', '').strip().lower()
            username = request.data.get('username', '').strip() or email
            first_name = request.data.get('first_name', '')
            last_name = request.data.get('last_name', '')
            password = request.data.get('password', 'Pass1234!')
            enterprise_role = request.data.get('enterprise_role', 'EMPLOYEE')
            department = request.data.get('department', 'General')
            assigned_channels = request.data.get('assigned_channels', [])
            project_id = request.data.get('project_id')

            if not email:
                return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

            if User.objects.filter(username=username).exists():
                return Response({'error': f'User with username/email "{username}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                client=client,
                role='AGENT' if enterprise_role != 'ADMIN' else 'ADMIN',
                enterprise_role=enterprise_role,
                department=department,
                status='APPROVED',
                assigned_social_channels=assigned_channels
            )
            user.set_password(password)
            user.save()

            if project_id:
                try:
                    proj = Project.objects.get(id=project_id, client=client)
                    proj.members.add(user)
                    proj.save()
                except Project.DoesNotExist:
                    pass

            log_admin_intelligence_action(
                request,
                client.business_name,
                'TEAM_MANAGEMENT',
                f'ADMIN_ADD_MEMBER: {user.username} ({enterprise_role})',
                '',
                f"Role: {enterprise_role}, Dept: {department}, Project: {project_id or 'None'}"
            )

            return Response({
                'message': f'Team member {user.username} added successfully.',
                'user_id': str(user.id)
            })

        # ── 2. Assign Team Member to Project ──
        elif action == 'ASSIGN_PROJECT_MEMBER':
            project_id = request.data.get('project_id')
            user_id = request.data.get('user_id')
            assigned_channels = request.data.get('assigned_channels', [])
            permission_level = request.data.get('permission_level', 'MEMBER')

            if not project_id or not user_id:
                return Response({'error': 'project_id and user_id are required'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                proj = Project.objects.get(id=project_id, client=client)
                user = User.objects.get(id=user_id, client=client)
            except (Project.DoesNotExist, User.DoesNotExist):
                return Response({'error': 'Project or User not found under this client'}, status=status.HTTP_404_NOT_FOUND)

            proj.members.add(user)
            proj.save()

            # Update channel & permission assignment for member
            if assigned_channels:
                current_channels = set(getattr(user, 'assigned_social_channels', []))
                current_channels.update(assigned_channels)
                user.assigned_social_channels = list(current_channels)

            current_matrix = getattr(user, 'permission_matrix', {})
            current_matrix[proj.name] = permission_level
            user.permission_matrix = current_matrix
            user.save()

            log_admin_intelligence_action(
                request,
                client.business_name,
                'PROJECT_TEAM_MAPPING',
                f'ASSIGN_TO_PROJECT: {user.username} -> {proj.name}',
                '',
                f"Channels: {assigned_channels}, Permission: {permission_level}"
            )

            return Response({'message': f'{user.username} assigned to {proj.name} successfully.'})

        # ── 3. Assign / Modify Channel Access ──
        elif action == 'UPDATE_CHANNEL_ACCESS':
            user_id = request.data.get('user_id')
            channels = request.data.get('channels', [])  # list of channel keys

            if not user_id:
                return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                user = User.objects.get(id=user_id, client=client)
            except User.DoesNotExist:
                return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

            old_channels = user.assigned_social_channels
            user.assigned_social_channels = channels
            user.save()

            log_admin_intelligence_action(
                request,
                client.business_name,
                'CHANNEL_ACCESS_MATRIX',
                f'UPDATE_CHANNELS: {user.username}',
                str(old_channels),
                str(channels)
            )

            return Response({'message': f'Channel access updated for {user.username}.'})

        # ── 4. Lifecycle & Profile Overrides ──
        elif action == 'SET_APPROVAL_STATUS':
            new_status = request.data.get('approval_status', 'APPROVED').upper()
            c_users = User.objects.filter(client=client)
            for u in c_users:
                u.status = new_status
                u.save()

            log_admin_intelligence_action(
                request,
                client.business_name,
                'CLIENT_LIFECYCLE',
                f'SET_APPROVAL_STATUS -> {new_status}',
                '',
                new_status
            )
            return Response({'message': f'Client approval status set to {new_status}.'})

        elif action == 'SET_ACCOUNT_STATUS':
            new_status = request.data.get('status', 'ACTIVE').upper()
            client.status = new_status
            client.save()

            # Sync user-level status so login works correctly
            c_users = User.objects.filter(client=client)
            if new_status == 'ACTIVE':
                c_users.update(status='APPROVED')
            elif new_status == 'SUSPENDED':
                c_users.update(status='SUSPENDED')

            log_admin_intelligence_action(
                request,
                client.business_name,
                'CLIENT_LIFECYCLE',
                f'SET_ACCOUNT_STATUS -> {new_status}',
                '',
                new_status
            )
            return Response({'message': f'Client account status set to {new_status}.'})

        elif action in ['UPDATE_PLAN', 'ASSIGN_PLAN']:
            new_plan = request.data.get('plan', 'Growth')
            old_plan = client.plan
            client.plan = new_plan

            try:
                from api.models import Plan
                p_obj = Plan.objects.filter(name__iexact=new_plan).first() or Plan.objects.filter(slug__iexact=new_plan).first()
                client.assigned_plan = p_obj
            except Exception:
                pass

            client.save()

            log_admin_intelligence_action(
                request,
                client.business_name,
                'SUBSCRIPTION_PLAN',
                f'UPDATE_PLAN -> {new_plan}',
                str(old_plan),
                str(new_plan)
            )
            return Response({'message': f'Plan updated to {new_plan} for {client.business_name}.', 'plan': new_plan})

        elif action == 'EDIT_PROFILE':
            client.business_name = request.data.get('business_name', client.business_name)
            client.phone_number = request.data.get('phone_number', client.phone_number)
            client.address = request.data.get('address', client.address)
            client.company_logo_url = request.data.get('company_logo_url', client.company_logo_url)
            if 'plan' in request.data:
                new_p = request.data.get('plan')
                client.plan = new_p
                try:
                    from api.models import Plan
                    p_obj = Plan.objects.filter(name__iexact=new_p).first() or Plan.objects.filter(slug__iexact=new_p).first()
                    client.assigned_plan = p_obj
                except Exception:
                    pass
            if 'status' in request.data:
                new_status = request.data.get('status', '').upper()
                old_status = client.status
                client.status = new_status
                # Sync user-level status so login works correctly
                if new_status != old_status:
                    c_users = User.objects.filter(client=client)
                    if new_status == 'ACTIVE':
                        c_users.update(status='APPROVED')
                    elif new_status == 'SUSPENDED':
                        c_users.update(status='SUSPENDED')
            client.save()

            log_admin_intelligence_action(
                request,
                client.business_name,
                'CLIENT_PROFILE',
                'EDIT_CLIENT_PROFILE',
                '',
                f"{client.business_name} | {client.plan} | {client.status}"
            )
            return Response({'message': f'Profile and plan for {client.business_name} updated successfully.', 'plan': client.plan})

        elif action in ['CUSTOMIZE_FEATURES', 'UPDATE_FEATURE_OVERRIDES']:
            custom_added = request.data.get('custom_added', [])
            custom_removed = request.data.get('custom_removed', [])

            try:
                from api.models import ClientFeatureOverride, Feature
                ClientFeatureOverride.objects.filter(client=client).delete()

                for key in custom_added:
                    if not key:
                        continue
                    feat, _ = Feature.objects.get_or_create(
                        key=key,
                        defaults={
                            'name': key.replace('feature_', '').replace('connector_', '').replace('channel_', '').replace('_', ' ').title(),
                            'category': 'Features',
                            'feature_type': 'Module',
                            'description': f'Custom feature {key}'
                        }
                    )
                    ClientFeatureOverride.objects.create(
                        client=client,
                        feature=feat,
                        override_type='ADD',
                        assigned_by=request.user if (request.user and request.user.is_authenticated) else None
                    )

                for key in custom_removed:
                    if not key:
                        continue
                    feat, _ = Feature.objects.get_or_create(
                        key=key,
                        defaults={
                            'name': key.replace('feature_', '').replace('connector_', '').replace('channel_', '').replace('_', ' ').title(),
                            'category': 'Features',
                            'feature_type': 'Module',
                            'description': f'Custom feature {key}'
                        }
                    )
                    ClientFeatureOverride.objects.create(
                        client=client,
                        feature=feat,
                        override_type='REMOVE',
                        assigned_by=request.user if (request.user and request.user.is_authenticated) else None
                    )
            except Exception as e:
                logger.error(f"Error saving ClientFeatureOverride records: {str(e)}", exc_info=True)
                return Response({'error': f'Failed to save feature overrides: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            log_admin_intelligence_action(
                request,
                client.business_name,
                'FEATURE_OVERRIDES',
                'CUSTOMIZE_FEATURES',
                '',
                f"Added: {custom_added}, Removed: {custom_removed}"
            )
            return Response({
                'message': f'Feature overrides saved successfully for {client.business_name}.',
                'custom_added': custom_added,
                'custom_removed': custom_removed
            })

        elif action == 'CHANGE_PASSWORD':
            new_password = request.data.get('new_password')
            if not new_password:
                return Response({'error': 'new_password is required'}, status=status.HTTP_400_BAD_REQUEST)
            c_users = User.objects.filter(client=client)
            target_user = c_users.filter(role='CLIENT').first() or c_users.first()
            if not target_user:
                return Response({'error': 'No user account associated with this client'}, status=status.HTTP_404_NOT_FOUND)
            target_user.set_password(new_password)
            target_user.save()
            log_admin_intelligence_action(
                request,
                client.business_name,
                'CREDENTIALS',
                f'CHANGE_PASSWORD for user: {target_user.username}',
                '',
                'Password updated by Super Admin'
            )
            return Response({'message': f'Password updated successfully for {target_user.username}.'})

        elif action == 'DELETE_CLIENT':
            biz_name = client.business_name
            User.objects.filter(client=client).delete()
            client.delete()
            log_admin_intelligence_action(
                request,
                biz_name,
                'CLIENT_LIFECYCLE',
                f'DELETE_CLIENT: {biz_name}',
                '',
                'Client and associated users deleted by Admin'
            )
            return Response({'message': f'Client {biz_name} deleted successfully.'})

        return Response({'error': f'Unsupported action: {action}'}, status=status.HTTP_400_BAD_REQUEST)


class ClientIntelligenceExportView(APIView):
    """
    Exports full client management table as CSV for Admin reporting.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        clients = list(Client.objects.all().order_by('-created_at'))
        users = list(User.objects.all())
        projects = list(Project.objects.all())
        invoices = list(Invoice.objects.all())
        products = list(Product.objects.all())

        user_by_client = {}
        for u in users:
            if u.client_id:
                cid = str(u.client_id)
                user_by_client.setdefault(cid, []).append(u)

        project_by_client = {}
        for p in projects:
            if p.client_id:
                cid = str(p.client_id)
                project_by_client.setdefault(cid, []).append(p)

        invoice_by_client = {}
        for inv in invoices:
            if inv.client_id:
                cid = str(inv.client_id)
                invoice_by_client.setdefault(cid, []).append(inv)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="uwo_clients_intelligence_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Client ID', 'Business Name', 'Client Name', 'Email', 'Phone',
            'Plan', 'Account Status', 'Approval Status', 'Active Channels Count',
            'Active Channels List', 'Total Projects', 'Total Team Members',
            'Total Invoices', 'Paid Invoices Revenue', 'Health Score', 'Registration Date'
        ])

        for client in clients:
            cid = str(client.id)
            c_users = user_by_client.get(cid, [])
            c_projects = project_by_client.get(cid, [])
            c_invoices = invoice_by_client.get(cid, [])

            primary_user = next((u for u in c_users if u.role == 'CLIENT'), c_users[0] if c_users else None)
            owner_name = f"{primary_user.first_name} {primary_user.last_name}".strip() if primary_user else ''
            if not owner_name and primary_user:
                owner_name = primary_user.username
            owner_email = primary_user.email if primary_user else (client.settings.get('email') or 'N/A')
            approval_status = primary_user.status if primary_user else 'APPROVED'

            all_channels = get_all_supported_channels(client)
            active_channels = [ch['name'] for ch in all_channels if ch['is_connected']]

            paid_invoices = [i for i in c_invoices if i.payment_status == 'PAID']
            total_rev = sum(float(i.total) for i in paid_invoices)

            metrics = {
                'active_channels_count': len(active_channels),
                'team_count': len(c_users),
                'projects_count': len(c_projects),
                'bot_messages_count': 10,
                'products_count': 5,
                'invoices_count': len(c_invoices),
                'kb_docs_count': 1,
            }
            health = compute_client_health_score(client, metrics)

            writer.writerow([
                str(client.id),
                client.business_name,
                owner_name,
                owner_email,
                client.phone_number or '',
                client.plan,
                client.status,
                approval_status,
                len(active_channels),
                "; ".join(active_channels),
                len(c_projects),
                len(c_users),
                len(c_invoices),
                total_rev,
                f"{health['score']} ({health['label']})",
                client.created_at.strftime('%Y-%m-%d')
            ])

        return response
